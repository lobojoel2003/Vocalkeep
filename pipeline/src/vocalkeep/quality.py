# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording quality checks.

This is the same algorithm, with the same thresholds, as ``crates/vocalkeep-core/src/quality.rs``
in the desktop app. Both are tested against ``shared/fixtures/``, so they never drift apart. When
you change one, change the other.

The pipeline runs the checks again on every take instead of trusting the results stored in
``bank.json``: recordings may have been edited, copied from elsewhere, or checked by an older
version of the app.

How it works, in short:

1. The DC offset (mean) and clipping (runs of samples at full scale) are measured on the raw
   signal.
2. The signal is cut into 20 ms frames (a final partial frame counts if it is at least half a
   frame) and each frame's power is measured with the DC offset removed.
3. The background level is the mean power of the quietest tenth of frames. Frames more than
   ``speech_margin_db`` above it (and above ``speech_floor_dbfs``) are speech, except runs shorter
   than ``min_speech_run_frames`` (clicks and taps).
4. Issues are noted from those measurements; any issue with severity "redo" makes the verdict
   "redo", other issues make it "okay", none makes it "good".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from vocalkeep.audio import MIN_DBFS, Clip, amplitude_to_dbfs, power_to_dbfs

Verdict = Literal["good", "okay", "redo"]
Severity = Literal["warn", "redo"]

#: Every issue code, in the order the checks run. The app turns each into a kind message.
ISSUE_CODES = (
    "no-speech",
    "too-short",
    "clipping",
    "near-clipping",
    "too-quiet",
    "too-loud",
    "noisy",
    "low-snr",
    "cut-off-start",
    "cut-off-end",
    "long-pause",
    "too-fast",
    "too-slow",
    "dc-offset",
)

#: Plain-language descriptions, used by ``vocalkeep check``.
ISSUE_MESSAGES = {
    "no-speech": "no speech was found",
    "too-short": "the speech is very short",
    "clipping": "it was too loud and the sound broke up (clipping)",
    "near-clipping": "it came close to being too loud",
    "too-quiet": "it is quiet",
    "too-loud": "it is quite loud",
    "noisy": "there is background noise",
    "low-snr": "the voice is not much louder than the background",
    "cut-off-start": "the recording may have started a moment late",
    "cut-off-end": "the end of the sentence was cut off",
    "long-pause": "there is a long pause in the middle",
    "too-fast": "it seems shorter than the sentence (maybe cut short)",
    "too-slow": "it seems long for the sentence",
    "dc-offset": "the microphone adds a small electrical offset",
}

_VERDICT_RANK = {"redo": 0, "okay": 1, "good": 2}


def verdict_rank(verdict: str) -> int:
    """Orders verdicts: redo < okay < good."""
    return _VERDICT_RANK[verdict]


@dataclass(frozen=True)
class RoomConfig:
    seconds: int
    quiet_dbfs: float
    fine_dbfs: float
    noisy_dbfs: float


@dataclass(frozen=True)
class TrainingConfig:
    """How recordings are prepared for training."""

    trim_pad_ms: int
    target_dbfs: float
    min_verdict: Verdict


@dataclass(frozen=True)
class QualityConfig:
    """Thresholds from ``shared/quality.json`` (a copy ships inside the package)."""

    version: int
    frame_ms: int
    min_speech_run_frames: int
    speech_margin_db: float
    speech_floor_dbfs: float
    clip_level: float
    clip_run_samples: int
    clip_runs_redo: int
    near_clip_peak_dbfs: float
    quiet_warn_dbfs: float
    quiet_redo_dbfs: float
    loud_warn_dbfs: float
    noise_warn_dbfs: float
    noise_redo_dbfs: float
    snr_warn_db: float
    snr_redo_db: float
    dc_offset_warn: float
    min_speech_ms: int
    edge_margin_ms: int
    long_silence_warn_ms: int
    chars_per_second_max: float
    chars_per_second_min: float
    room: RoomConfig
    training: TrainingConfig

    @staticmethod
    def from_dict(data: dict[str, Any]) -> QualityConfig:
        room = data["room"]
        training = data.get("training", {})
        return QualityConfig(
            version=int(data["version"]),
            frame_ms=int(data["frame_ms"]),
            min_speech_run_frames=int(data["min_speech_run_frames"]),
            speech_margin_db=float(data["speech_margin_db"]),
            speech_floor_dbfs=float(data["speech_floor_dbfs"]),
            clip_level=float(data["clip_level"]),
            clip_run_samples=int(data["clip_run_samples"]),
            clip_runs_redo=int(data["clip_runs_redo"]),
            near_clip_peak_dbfs=float(data["near_clip_peak_dbfs"]),
            quiet_warn_dbfs=float(data["quiet_warn_dbfs"]),
            quiet_redo_dbfs=float(data["quiet_redo_dbfs"]),
            loud_warn_dbfs=float(data["loud_warn_dbfs"]),
            noise_warn_dbfs=float(data["noise_warn_dbfs"]),
            noise_redo_dbfs=float(data["noise_redo_dbfs"]),
            snr_warn_db=float(data["snr_warn_db"]),
            snr_redo_db=float(data["snr_redo_db"]),
            dc_offset_warn=float(data["dc_offset_warn"]),
            min_speech_ms=int(data["min_speech_ms"]),
            edge_margin_ms=int(data["edge_margin_ms"]),
            long_silence_warn_ms=int(data["long_silence_warn_ms"]),
            chars_per_second_max=float(data["chars_per_second_max"]),
            chars_per_second_min=float(data["chars_per_second_min"]),
            room=RoomConfig(
                seconds=int(room["seconds"]),
                quiet_dbfs=float(room["quiet_dbfs"]),
                fine_dbfs=float(room["fine_dbfs"]),
                noisy_dbfs=float(room["noisy_dbfs"]),
            ),
            training=TrainingConfig(
                trim_pad_ms=int(training.get("trim_pad_ms", 120)),
                target_dbfs=float(training.get("target_dbfs", -20.0)),
                min_verdict=training.get("min_verdict", "okay"),
            ),
        )


@lru_cache(maxsize=1)
def config() -> QualityConfig:
    """The thresholds shipped with this version of Vocalkeep."""
    text = resources.files("vocalkeep").joinpath("data/quality.json").read_text(encoding="utf-8")
    return QualityConfig.from_dict(json.loads(text))


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity}


@dataclass
class Analysis:
    """Measurements and verdict for one take (same fields as the Rust ``Analysis``)."""

    verdict: Verdict
    issues: list[Issue] = field(default_factory=list)
    sample_rate: int = 0
    duration_ms: int = 0
    #: Highest sample, dBFS.
    peak_dbfs: float = MIN_DBFS
    #: Average level while speaking, dBFS.
    speech_dbfs: float = MIN_DBFS
    #: Background level between words, dBFS.
    noise_floor_dbfs: float = MIN_DBFS
    #: Speech level above the background, dB.
    snr_db: float = 0.0
    #: Samples at or above the clipping level.
    clipped_samples: int = 0
    #: Runs of consecutive clipped samples (flattened peaks).
    clip_runs: int = 0
    dc_offset: float = 0.0
    speech_start_ms: int | None = None
    speech_end_ms: int | None = None
    speech_ms: int = 0
    longest_pause_ms: int = 0

    def has(self, code: str) -> bool:
        return any(i.code == code for i in self.issues)

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.issues]

    def to_dict(self) -> dict[str, Any]:
        """The camelCase form stored in ``bank.json``."""
        return {
            "verdict": self.verdict,
            "issues": [i.to_dict() for i in self.issues],
            "sampleRate": self.sample_rate,
            "durationMs": self.duration_ms,
            "peakDbfs": round(self.peak_dbfs, 2),
            "speechDbfs": round(self.speech_dbfs, 2),
            "noiseFloorDbfs": round(self.noise_floor_dbfs, 2),
            "snrDb": round(self.snr_db, 2),
            "clippedSamples": self.clipped_samples,
            "clipRuns": self.clip_runs,
            "dcOffset": round(self.dc_offset, 5),
            "speechStartMs": self.speech_start_ms,
            "speechEndMs": self.speech_end_ms,
            "speechMs": self.speech_ms,
            "longestPauseMs": self.longest_pause_ms,
        }


def verdict_for(issues: list[Issue]) -> Verdict:
    """The verdict a list of issues adds up to."""
    if any(i.severity == "redo" for i in issues):
        return "redo"
    if not issues:
        return "good"
    return "okay"


def _frame_powers(samples: npt.NDArray[np.float32], frame_len: int, dc: float) -> list[float]:
    """Mean power of each frame with the DC offset removed.

    Frames are consecutive chunks of ``frame_len`` samples; the last, shorter chunk counts only if
    it holds at least half a frame (``len * 2 >= frame_len``), as in the Rust code.
    """
    n = len(samples)
    full = n // frame_len
    centred = (samples - np.float32(dc)).astype(np.float64)
    squares = centred * centred
    powers: list[float] = []
    if full:
        powers.extend(squares[: full * frame_len].reshape(full, frame_len).mean(axis=1).tolist())
    rest = n - full * frame_len
    if rest and rest * 2 >= frame_len:
        powers.append(float(squares[full * frame_len :].mean()))
    return powers


def _clipping(samples: npt.NDArray[np.float32], level: float, min_run: int) -> tuple[int, int]:
    """Counts clipped samples and runs of at least ``min_run`` consecutive clipped samples."""
    clipped = np.abs(samples) >= np.float32(level)
    count = int(np.count_nonzero(clipped))
    if count == 0:
        return 0, 0
    # Run lengths of True values.
    padded = np.concatenate(([False], clipped, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    lengths = edges[1::2] - edges[0::2]
    runs = int(np.count_nonzero(lengths >= max(min_run, 1)))
    return count, runs


def _quietest_tenth_dbfs(powers: list[float]) -> float:
    ordered = sorted(powers)
    n = max(len(ordered) // 10, 1)
    return power_to_dbfs(sum(ordered[:n]) / n)


def _drop_short_runs(active: list[bool], min_run: int) -> None:
    """Clears runs of ``True`` shorter than ``min_run`` (clicks and taps are not speech)."""
    i = 0
    while i < len(active):
        if active[i]:
            start = i
            while i < len(active) and active[i]:
                i += 1
            if i - start < min_run:
                for j in range(start, i):
                    active[j] = False
        else:
            i += 1


def _longest_false_run(active: list[bool]) -> int:
    best = 0
    run = 0
    for a in active:
        if a:
            run = 0
        else:
            run += 1
            best = max(best, run)
    return best


def _letters(text: str) -> int:
    """Letters and digits in the sentence (Rust's ``char::is_alphanumeric``).

    Python's ``str.isalnum`` agrees for Latin, Greek, Cyrillic and CJK text. It differs only for
    a few combining vowel signs in scripts such as Devanagari, which Rust counts as letters.
    """
    return sum(1 for c in text if c.isalnum())


def analyze(clip: Clip, text: str | None = None, cfg: QualityConfig | None = None) -> Analysis:
    """Checks a take.

    ``text`` is the sentence that was read, if any; it enables the speaking-rate check that
    catches a sentence cut short.
    """
    cfg = cfg or config()
    sr = max(clip.sample_rate, 1)
    samples = np.asarray(clip.samples, dtype=np.float32)
    duration_ms = (len(samples) * 1000) // sr
    frame_len = max((sr * cfg.frame_ms) // 1000, 1)

    # DC offset and clipping are measured on the raw signal.
    dc = float(np.float32(samples.astype(np.float64).sum() / len(samples))) if samples.size else 0.0
    clipped_samples, clip_runs = _clipping(samples, cfg.clip_level, cfg.clip_run_samples)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    peak_dbfs = amplitude_to_dbfs(peak)

    # Frame powers with the DC offset removed.
    powers = _frame_powers(samples, frame_len, dc)
    frame_db = [power_to_dbfs(p) for p in powers]

    issues: list[Issue] = []

    def push(code: str, severity: Severity) -> None:
        issues.append(Issue(code, severity))

    if not frame_db:
        push("no-speech", "redo")
        return Analysis(
            verdict="redo",
            issues=issues,
            sample_rate=sr,
            duration_ms=duration_ms,
            peak_dbfs=peak_dbfs,
            speech_dbfs=MIN_DBFS,
            noise_floor_dbfs=MIN_DBFS,
            snr_db=0.0,
            clipped_samples=clipped_samples,
            clip_runs=clip_runs,
            dc_offset=dc,
        )

    # Background: the mean power of the quietest tenth of frames.
    noise_floor_dbfs = _quietest_tenth_dbfs(powers)
    threshold = max(noise_floor_dbfs + cfg.speech_margin_db, cfg.speech_floor_dbfs)
    active = [db > threshold for db in frame_db]
    _drop_short_runs(active, cfg.min_speech_run_frames)

    speech_idx = [i for i, a in enumerate(active) if a]
    first = speech_idx[0] if speech_idx else None
    last = speech_idx[-1] if speech_idx else None
    speech_frames = len(speech_idx)
    speech_ms = speech_frames * cfg.frame_ms
    speech_power = sum(powers[i] for i in speech_idx) / speech_frames if speech_frames else 0.0
    speech_dbfs = power_to_dbfs(speech_power)
    snr_db = speech_dbfs - noise_floor_dbfs if speech_frames else 0.0
    longest_pause_ms = 0
    if first is not None and last is not None:
        longest_pause_ms = _longest_false_run(active[first : last + 1]) * cfg.frame_ms
    speech_start_ms = first * cfg.frame_ms if first is not None else None
    speech_end_ms = (last + 1) * cfg.frame_ms if last is not None else None

    if first is not None and last is not None:
        if speech_ms < cfg.min_speech_ms:
            push("too-short", "redo")
        edge_frames = max(cfg.edge_margin_ms // max(cfg.frame_ms, 1), 1)
        if first < edge_frames:
            push("cut-off-start", "warn")
        if len(active) - 1 - last < edge_frames:
            push("cut-off-end", "redo")
    else:
        push("no-speech", "redo")

    # Loudness and clipping.
    if clip_runs >= cfg.clip_runs_redo:
        push("clipping", "redo")
    elif clipped_samples > 0 or peak_dbfs > cfg.near_clip_peak_dbfs:
        push("near-clipping", "warn")
    level_issue = False
    if speech_frames > 0:
        if speech_dbfs < cfg.quiet_redo_dbfs:
            push("too-quiet", "redo")
            level_issue = True
        elif speech_dbfs < cfg.quiet_warn_dbfs:
            push("too-quiet", "warn")
            level_issue = True
        elif speech_dbfs > cfg.loud_warn_dbfs and clip_runs == 0:
            push("too-loud", "warn")

    # Background noise, then signal-to-noise when neither explains it already.
    if noise_floor_dbfs > cfg.noise_redo_dbfs:
        push("noisy", "redo")
        level_issue = True
    elif noise_floor_dbfs > cfg.noise_warn_dbfs:
        push("noisy", "warn")
        level_issue = True
    if speech_frames > 0 and not level_issue:
        if snr_db < cfg.snr_redo_db:
            push("low-snr", "redo")
        elif snr_db < cfg.snr_warn_db:
            push("low-snr", "warn")

    if abs(dc) > cfg.dc_offset_warn:
        push("dc-offset", "warn")
    if longest_pause_ms > cfg.long_silence_warn_ms:
        push("long-pause", "warn")

    # Speaking rate against the sentence: catches a take that stopped early or ran on.
    if text is not None and speech_start_ms is not None and speech_end_ms is not None:
        letters = _letters(text)
        span_s = max(speech_end_ms - speech_start_ms, 0) / 1000.0
        if letters >= 10 and span_s > 0.0:
            cps = letters / span_s
            if cps > cfg.chars_per_second_max:
                push("too-fast", "warn")
            elif cps < cfg.chars_per_second_min:
                push("too-slow", "warn")

    return Analysis(
        verdict=verdict_for(issues),
        issues=issues,
        sample_rate=sr,
        duration_ms=duration_ms,
        peak_dbfs=peak_dbfs,
        speech_dbfs=speech_dbfs,
        noise_floor_dbfs=noise_floor_dbfs,
        snr_db=snr_db,
        clipped_samples=clipped_samples,
        clip_runs=clip_runs,
        dc_offset=dc,
        speech_start_ms=speech_start_ms,
        speech_end_ms=speech_end_ms,
        speech_ms=speech_ms,
        longest_pause_ms=longest_pause_ms,
    )


RoomLevel = Literal["quiet", "fine", "noisy", "too-noisy"]


@dataclass(frozen=True)
class RoomCheck:
    level: RoomLevel
    noise_floor_dbfs: float
    peak_dbfs: float
    sample_rate: int


def analyze_room(clip: Clip, cfg: QualityConfig | None = None) -> RoomCheck:
    """How quiet the room is, from a few seconds of silence (as in the desktop app)."""
    cfg = cfg or config()
    frame_len = max((max(clip.sample_rate, 1) * cfg.frame_ms) // 1000, 1)
    powers = sorted(_frame_powers(np.asarray(clip.samples, dtype=np.float32), frame_len, 0.0))
    # The median frame ignores a single cough or door; the peak reports it.
    noise = power_to_dbfs(powers[len(powers) // 2]) if powers else MIN_DBFS
    level: RoomLevel
    if noise <= cfg.room.quiet_dbfs:
        level = "quiet"
    elif noise <= cfg.room.fine_dbfs:
        level = "fine"
    elif noise <= cfg.room.noisy_dbfs:
        level = "noisy"
    else:
        level = "too-noisy"
    peak = float(np.max(np.abs(clip.samples))) if clip.samples.size else 0.0
    return RoomCheck(level, noise, amplitude_to_dbfs(peak), clip.sample_rate)


def describe(analysis: Analysis) -> str:
    """A short plain-language summary of a take's issues."""
    if not analysis.issues:
        return "sounds good"
    return "; ".join(ISSUE_MESSAGES.get(i.code, i.code) for i in analysis.issues)
