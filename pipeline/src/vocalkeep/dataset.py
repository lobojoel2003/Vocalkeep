# SPDX-License-Identifier: GPL-3.0-or-later
"""Checking a voice bank and preparing it as a Piper training dataset.

``prepare`` writes::

    DATASET/
      wavs/<promptId>.wav   22050 Hz mono 16-bit, trimmed around the speech, level-matched
      metadata.csv          "<promptId>.wav|text" per line, no header (Piper's format)
      dataset.json          what went in, what was left out and why

Every take is checked again from its audio (the stored results are not trusted). Takes marked
"redo", missing or unreadable files and takes without text are left out.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from vocalkeep import __version__
from vocalkeep.audio import Clip, dbfs_to_amplitude, read_wav, resample, write_wav
from vocalkeep.bank import Bank, Take, safe_name
from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import espeak_voice_for, normalize_tag
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.quality import Analysis, QualityConfig, analyze, config, describe, verdict_rank

DATASET_FORMAT = "vocalkeep-dataset"
DATASET_VERSION = 1
DEFAULT_SAMPLE_RATE = 22050
#: Peak level after normalising, dBFS. Leaves headroom for resampling and training.
PEAK_LIMIT_DBFS = -1.0
#: Kept sentences the app suggests before building a voice for everyday use.
RECOMMENDED_TAKES = 600
#: Below this a voice is only a preview.
PREVIEW_TAKES = 100

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Text safe for Piper's CSV: no ``|``, no line breaks or control characters."""
    text = text.replace("|", " ")
    text = _CONTROL.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Assessment:
    """One take, checked again from its audio."""

    take: Take
    path: Path | None
    text: str
    analysis: Analysis | None = None
    #: Why the take can't be used at all: "missing-file", "unreadable", "unsafe-path".
    problem: str | None = None
    detail: str = ""
    clip: Clip | None = field(default=None, repr=False)

    @property
    def verdict(self) -> str | None:
        return self.analysis.verdict if self.analysis else None


def assess_take(
    bank: Bank, take: Take, cfg: QualityConfig | None = None, keep_audio: bool = False
) -> Assessment:
    """Reads one take and runs the quality checks on it."""
    text = clean_text(take.text)
    try:
        path = bank.resolve(take.file) if take.file else None
    except VocalkeepError as e:
        return Assessment(take, None, text, problem="unsafe-path", detail=e.message)
    if path is None or not path.is_file():
        return Assessment(
            take,
            path,
            text,
            problem="missing-file",
            detail=f"{take.file or '(no file)'} is missing",
        )
    try:
        clip = read_wav(path)
    except VocalkeepError as e:
        return Assessment(take, path, text, problem="unreadable", detail=e.message)
    analysis = analyze(clip, text or None, cfg or config())
    return Assessment(take, path, text, analysis=analysis, clip=clip if keep_audio else None)


def check_bank(bank: Bank, reporter: Reporter | None = None) -> dict[str, Any]:
    """Re-checks every take. Returns a report (camelCase keys, ready for JSON)."""
    reporter = reporter or NullReporter()
    cfg = config()
    counts: Counter[str] = Counter()
    takes: list[dict[str, Any]] = []
    redo: list[dict[str, Any]] = []
    speech_ms = 0
    total = len(bank.takes)
    for i, take in enumerate(bank.takes, start=1):
        a = assess_take(bank, take, cfg)
        stored = (take.stored_quality or {}).get("verdict")
        entry: dict[str, Any] = {
            "promptId": take.prompt_id,
            "setId": take.set_id,
            "text": take.text,
            "file": take.file,
            "storedVerdict": stored,
        }
        if a.analysis is None:
            counts[a.problem or "unreadable"] += 1
            entry.update(verdict=None, problem=a.problem, message=a.detail, issues=[])
            redo.append(entry)
        else:
            counts[a.analysis.verdict] += 1
            speech_ms += a.analysis.speech_ms
            entry.update(
                verdict=a.analysis.verdict,
                issues=[iss.to_dict() for iss in a.analysis.issues],
                message=describe(a.analysis),
                changed=stored is not None and stored != a.analysis.verdict,
                quality=a.analysis.to_dict(),
            )
            entry["hasText"] = bool(a.text)
            if a.analysis.verdict == "redo":
                redo.append(entry)
            elif not a.text:
                counts["no-text"] += 1
        takes.append(entry)
        reporter.progress("check", i / max(total, 1), f"{i} of {total} recordings")
    return {
        "bank": {
            "id": bank.id,
            "path": str(bank.source or bank.root),
            "speaker": bank.speaker.to_dict(),
        },
        "counts": {
            "takes": total,
            "good": counts["good"],
            "okay": counts["okay"],
            "redo": counts["redo"],
            "missing": counts["missing-file"],
            "unreadable": counts["unreadable"] + counts["unsafe-path"],
            "noText": counts["no-text"],
            # What 'prepare' would use with the default settings.
            "usable": counts["good"] + counts["okay"] - counts["no-text"],
        },
        "speechMinutes": round(speech_ms / 60000, 2),
        "takes": takes,
        "redo": [
            {k: e.get(k) for k in ("promptId", "text", "file", "verdict", "problem", "message")}
            for e in redo
        ],
    }


def _prepare_output_dir(out: Path) -> None:
    if out.exists() and not out.is_dir():
        raise VocalkeepError(f"{out} is a file. Choose a folder for the dataset.")
    if out.is_dir() and any(out.iterdir()):
        if not (out / "dataset.json").is_file():
            raise VocalkeepError(
                f"{out} already has other files in it.",
                "Choose a new or empty folder for the dataset, so nothing of yours is replaced.",
            )
        # A dataset we made before: replace it.
        shutil.rmtree(out / "wavs", ignore_errors=True)
        for name in ("metadata.csv", "dataset.json"):
            (out / name).unlink(missing_ok=True)
    (out / "wavs").mkdir(parents=True, exist_ok=True)


def process_clip(
    clip: Clip,
    analysis: Analysis,
    sample_rate: int,
    trim_pad_ms: int,
    target_dbfs: float,
    peak_limit_dbfs: float = PEAK_LIMIT_DBFS,
) -> Clip:
    """Trims a take around its speech, removes DC offset, resamples and sets its level.

    The speech is brought to ``target_dbfs`` (RMS of the speech frames) unless that would push
    the peak above ``peak_limit_dbfs``; then the peak decides.
    """
    start_ms = max((analysis.speech_start_ms or 0) - trim_pad_ms, 0)
    end_ms = min((analysis.speech_end_ms or clip.duration_ms) + trim_pad_ms, clip.duration_ms)
    first = clip.samples_for_ms(start_ms)
    last = min(clip.samples_for_ms(end_ms), len(clip.samples))
    segment = clip.samples[first:last].astype(np.float32) - np.float32(analysis.dc_offset)
    segment = resample(segment, clip.sample_rate, sample_rate)
    gain = dbfs_to_amplitude(target_dbfs - analysis.speech_dbfs)
    peak = float(np.max(np.abs(segment))) if segment.size else 0.0
    limit = dbfs_to_amplitude(peak_limit_dbfs)
    if peak * gain > limit and peak > 0:
        gain = limit / peak
    out = np.clip(segment * np.float32(gain), -1.0, 1.0).astype(np.float32)
    return Clip(sample_rate, out)


def prepare(
    bank: Bank,
    out_dir: str | Path,
    *,
    min_verdict: str | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    espeak_voice: str | None = None,
    reporter: Reporter | None = None,
) -> dict[str, Any]:
    """Prepares a training dataset from a bank. Returns the contents of ``dataset.json``."""
    reporter = reporter or NullReporter()
    cfg = config()
    min_verdict = min_verdict or cfg.training.min_verdict
    if min_verdict not in ("okay", "good"):
        raise VocalkeepError("--min-verdict must be 'okay' or 'good'.")
    if not 8000 <= sample_rate <= 48000:
        raise VocalkeepError("--sample-rate must be between 8000 and 48000 (Piper uses 22050).")
    out = Path(out_dir).expanduser().resolve()
    if not bank.takes:
        raise VocalkeepError(
            "This voice bank has no recordings yet.",
            "Record some sentences in the Vocalkeep app first.",
        )
    _prepare_output_dir(out)

    language = normalize_tag(bank.speaker.language or "en-US")
    espeak = espeak_voice or espeak_voice_for(language)
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    csv_lines: list[str] = []
    used_names: set[str] = set()
    verdicts: Counter[str] = Counter()
    total_samples = 0
    speech_ms = 0
    total = len(bank.takes)

    for i, take in enumerate(bank.takes, start=1):
        reporter.progress("prepare", (i - 1) / total, f"{i} of {total} recordings")

        def leave_out(reason: str, detail: str, take: Take = take) -> None:
            excluded.append(
                {"promptId": take.prompt_id, "file": take.file, "reason": reason, "detail": detail}
            )

        a = assess_take(bank, take, cfg, keep_audio=True)
        if a.problem:
            leave_out(a.problem, a.detail)
            continue
        if a.analysis is None or a.clip is None:  # pragma: no cover - set when no problem
            leave_out("unreadable", a.detail)
            continue
        if not a.text:
            leave_out("empty-text", "the recording has no sentence text")
            continue
        if a.analysis.verdict == "redo":
            leave_out("redo", describe(a.analysis))
            continue
        if verdict_rank(a.analysis.verdict) < verdict_rank(min_verdict):
            leave_out("below-min-verdict", f"{a.analysis.verdict}: {describe(a.analysis)}")
            continue
        name = safe_name(take.prompt_id)
        if name in used_names:
            leave_out("duplicate", f"another recording is already named {name}.wav")
            continue
        used_names.add(name)

        processed = process_clip(
            a.clip,
            a.analysis,
            sample_rate,
            cfg.training.trim_pad_ms,
            cfg.training.target_dbfs,
        )
        file_name = f"{name}.wav"
        write_wav(out / "wavs" / file_name, processed)
        csv_lines.append(f"{file_name}|{a.text}\n")
        verdicts[a.analysis.verdict] += 1
        total_samples += len(processed.samples)
        speech_ms += a.analysis.speech_ms
        included.append(
            {
                "promptId": take.prompt_id,
                "file": f"wavs/{file_name}",
                "text": a.text,
                "verdict": a.analysis.verdict,
                "durationMs": processed.duration_ms,
            }
        )
    reporter.progress("prepare", 1.0, f"{total} of {total} recordings")

    if not included:
        reasons = Counter(e["reason"] for e in excluded)
        summary = ", ".join(f"{n} {r}" for r, n in reasons.most_common())
        shutil.rmtree(out / "wavs", ignore_errors=True)
        raise VocalkeepError(
            f"None of the {total} recordings could be used ({summary}).",
            "Run 'vocalkeep check' on the voice bank to see which recordings to redo.",
        )

    (out / "metadata.csv").write_text("".join(csv_lines), encoding="utf-8", newline="\n")
    minutes = total_samples / sample_rate / 60
    info: dict[str, Any] = {
        "format": DATASET_FORMAT,
        "version": DATASET_VERSION,
        "createdAt": _now(),
        "vocalkeepVersion": __version__,
        "bank": {
            "id": bank.id,
            "path": str(bank.source or bank.root),
            "takes": total,
        },
        "speaker": bank.speaker.to_dict(),
        "language": language,
        "espeakVoice": espeak,
        "sampleRate": sample_rate,
        "minVerdict": min_verdict,
        "trimPadMs": cfg.training.trim_pad_ms,
        "targetDbfs": cfg.training.target_dbfs,
        "counts": {
            "takes": total,
            "included": len(included),
            "excluded": len(excluded),
            "good": verdicts["good"],
            "okay": verdicts["okay"],
        },
        "minutes": round(minutes, 2),
        "speechMinutes": round(speech_ms / 60000, 2),
        "utterances": included,
        "excluded": excluded,
    }
    (out / "dataset.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if excluded:
        reporter.log(f"{len(excluded)} recording(s) were left out; dataset.json lists why.")
    if len(included) < PREVIEW_TAKES:
        reporter.warn(
            f"With {len(included)} sentences you can try things out, but the voice will sound "
            f"rough. About {RECOMMENDED_TAKES} or more gives a natural voice."
        )
    elif len(included) < RECOMMENDED_TAKES:
        reporter.log(
            f"{len(included)} sentences makes a recognisable voice. "
            f"About {RECOMMENDED_TAKES} or more makes it sound more natural."
        )
    return info


def load_dataset_info(dataset_dir: str | Path) -> dict[str, Any]:
    """Reads ``dataset.json`` from a prepared dataset, with a kind error if it isn't one."""
    path = Path(dataset_dir).expanduser()
    info_path = path / "dataset.json"
    if not info_path.is_file() or not (path / "metadata.csv").is_file():
        raise VocalkeepError(
            f"{path} isn't a prepared dataset (it has no dataset.json and metadata.csv).",
            "Run 'vocalkeep prepare BANK -o DATASET' first, or use 'vocalkeep build' "
            "to do everything in one go.",
        )
    try:
        info: dict[str, Any] = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise VocalkeepError(f"{info_path} is damaged ({e}). Run 'vocalkeep prepare' again.") from e
    if info.get("format") != DATASET_FORMAT:
        raise VocalkeepError(f"{info_path} wasn't made by Vocalkeep.")
    return info
