# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning a finished training run into a voice folder.

The checkpoint is exported to ONNX with Piper's own exporter
(``python -m piper.train.export_onnx --checkpoint X.ckpt --output-file model.onnx``). The
exporter writes no settings file: the ``.onnx.json`` is the config Piper wrote during training
(``RUN/config.json``), copied next to the model with a few descriptive fields added.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from vocalkeep import __version__
from vocalkeep.bases import commercial_text, find_base
from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import language_name, normalize_tag, piper_language_code
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.train import find_latest_checkpoint, load_run
from vocalkeep.voice import (
    QUALITY,
    VOICE_FORMAT,
    VOICE_VERSION,
    Voice,
    load_voice,
    make_voice_id,
    validate_config,
)

PROJECT_URL = "https://github.com/lobojoel2003/Vocalkeep"
PIPER_URL = "https://github.com/OHF-Voice/piper1-gpl"


def run_export_command(python: str, checkpoint: Path, output: Path) -> None:
    """Runs Piper's ONNX exporter. (Tests replace this function.)"""
    cmd = [
        python,
        "-m",
        "piper.train.export_onnx",
        "--checkpoint",
        str(checkpoint),
        "--output-file",
        str(output),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
    except OSError as e:
        raise VocalkeepError(f"The exporter couldn't start: {e}.") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
        raise VocalkeepError(
            f"Making the voice file failed (exit code {proc.returncode}).",
            tail or "Run 'vocalkeep doctor' to check that Piper's training tools are installed.",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _country(tag: str) -> str:
    parts = normalize_tag(tag).split("-")
    return parts[1] if len(parts) > 1 else ""


def model_card(
    *,
    voice_id: str,
    speaker_name: str,
    language: str,
    sample_rate: int,
    run: dict[str, Any],
    created: str,
) -> str:
    """The plain-text MODEL_CARD that travels with the voice."""
    base_info = run.get("base", {})
    dataset = run.get("dataset", {})
    epochs = run.get("epochs", {})
    who = speaker_name or "the person who recorded it"
    try:
        base = find_base(str(base_info.get("id", "")))
        base_line = f'"{base.name}" ({base.id}), {base.lineage[0].lower()}{base.lineage[1:]}'
        licence = base.license
        licence_url = base.license_url
        dataset_line = base.dataset + (f" - {base.dataset_url}" if base.dataset_url else "")
        commercial: str = base.commercial
        reason = base.commercial_reason
        sources = list(base.sources)
    except VocalkeepError:
        base_line = str(base_info.get("id") or "an unknown Piper voice")
        licence = str(base_info.get("license") or "unknown")
        licence_url = None
        dataset_line = str(base_info.get("dataset") or "unknown")
        commercial = str(base_info.get("commercial") or "unknown")
        reason = ""
        sources = []
    country = _country(language)
    lang_text = language_name(language) + (f", {country}" if country else "")
    sentences = dataset.get("utterances") or 0
    minutes = dataset.get("minutes") or 0
    if commercial == "yes":
        use = (
            "The starting voice's licence puts no limits on this voice. Use it however "
            f"{who} wishes."
        )
    else:
        use = (
            "Because of the starting voice's licence, this voice may be used for personal, "
            "non-commercial purposes only (such as speaking for yourself every day). It must "
            "not be sold or used in a commercial product."
        )
    lines = [
        f"# Model card for {voice_id}",
        "",
        f"This is {who}'s own voice. It belongs to {who}, the person who recorded it.",
        "Please use it only with their permission, and never to pretend to be them.",
        "",
        f"* Language: {piper_language_code(language)} ({lang_text})",
        "* Speakers: 1",
        f"* Quality: {QUALITY}",
        f"* Sample rate: {sample_rate:,} Hz",
        f"* Created: {created[:10]}",
        f"* Made with: Vocalkeep {__version__} ({PROJECT_URL}) and Piper ({PIPER_URL})",
        "",
        "## Recordings",
        "",
        f"{sentences} sentences ({minutes:.0f} minutes of audio) recorded by {who} "
        "in the Vocalkeep app.",
        "",
        "## Training",
        "",
        f"Fine-tuned for {epochs.get('extra', '?')} epochs from the Piper voice {base_line}.",
        f"* The starting voice learned from: {dataset_line}",
        f"* Licence of those recordings: {licence}" + (f" ({licence_url})" if licence_url else ""),
        f"* {commercial_text(commercial)} {reason}".rstrip(),
    ]
    if base_info.get("checkpointUrl"):
        lines.append(f"* Starting checkpoint: {base_info['checkpointUrl']}")
    if sources:
        lines.append("* Sources: " + ", ".join(sources))
    lines += ["", "## Use", "", use, ""]
    return "\n".join(lines)


def export_voice(
    run_dir: str | Path,
    voices_dir: str | Path,
    *,
    name: str | None = None,
    checkpoint: str | Path | None = None,
    python: str | None = None,
    reporter: Reporter | None = None,
) -> Voice:
    """Exports the run's checkpoint into ``VOICES_DIR/<id>/`` and returns the voice."""
    reporter = reporter or NullReporter()
    run_path = Path(run_dir).expanduser().resolve()
    run = load_run(run_path)
    if run is None:
        raise VocalkeepError(
            f"{run_path} isn't a Vocalkeep training run (it has no run.json).",
            "Give the folder you passed to 'vocalkeep train -o'.",
        )
    config_path = run_path / "config.json"
    if not config_path.is_file():
        raise VocalkeepError(
            f"{run_path} has no config.json, which Piper writes when training starts.",
            "Train the voice first with 'vocalkeep train'.",
        )
    try:
        config: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise VocalkeepError(f"{config_path} is damaged ({e}).") from e
    validate_config(config, config_path)

    if checkpoint:
        ckpt = Path(checkpoint).expanduser().resolve()
        if not ckpt.is_file():
            raise VocalkeepError(f"The checkpoint {ckpt} doesn't exist.")
    else:
        found = find_latest_checkpoint(run_path)
        if found is None:
            raise VocalkeepError(
                f"No trained checkpoint was found in {run_path}.",
                "Train the voice first with 'vocalkeep train'.",
            )
        ckpt = found

    dataset = run.get("dataset", {})
    speaker = dataset.get("speaker", {}) or {}
    speaker_name = str(name or speaker.get("name") or "").strip()
    language = normalize_tag(str(dataset.get("language") or speaker.get("language") or "en-US"))
    voice_id = make_voice_id(language, speaker_name or "vocalkeep")
    voices = Path(voices_dir).expanduser().resolve()
    target = voices / voice_id
    staging = voices / f".{voice_id}.exporting"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    reporter.stage("export", "Making the voice file")
    reporter.log(f"Exporting {ckpt.name}")
    if not python:
        # The Python that trained, unless the run was copied from another computer.
        stored = str(run.get("python") or "")
        python = stored if stored and (Path(stored).exists() or shutil.which(stored)) else None
    onnx_path = staging / f"{voice_id}.onnx"
    try:
        run_export_command(python or sys.executable, ckpt, onnx_path)
        if not onnx_path.is_file() or onnx_path.stat().st_size == 0:
            raise VocalkeepError("The exporter finished but didn't write the voice file.")
        reporter.progress("export", 0.6, "Voice file made")

        created = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
        out_config = dict(config)
        out_config["dataset"] = voice_id.split("-")[1]
        audio = dict(out_config.get("audio", {}))
        audio["quality"] = QUALITY
        out_config["audio"] = audio
        family, _, region = piper_language_code(language).partition("_")
        out_config["language"] = {
            "code": piper_language_code(language),
            "family": family,
            "region": region,
            "name_english": language_name(language),
        }
        (staging / f"{voice_id}.onnx.json").write_text(
            json.dumps(out_config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (staging / "MODEL_CARD").write_text(
            model_card(
                voice_id=voice_id,
                speaker_name=speaker_name,
                language=language,
                sample_rate=int(config["audio"]["sample_rate"]),
                run=run,
                created=created,
            ),
            encoding="utf-8",
        )
        base = run.get("base", {})
        info = {
            "format": VOICE_FORMAT,
            "version": VOICE_VERSION,
            "id": voice_id,
            "name": speaker_name or voice_id.split("-")[1],
            "language": language,
            "gender": speaker.get("gender"),
            "sampleRate": int(config["audio"]["sample_rate"]),
            "base": {
                "id": base.get("id"),
                "license": base.get("license"),
                "commercial": base.get("commercial"),
                "lineage": base.get("lineage"),
            },
            "bank": {
                "id": dataset.get("bankId"),
                "takes": dataset.get("utterances"),
                "minutes": dataset.get("minutes"),
            },
            "epochs": run.get("epochs", {}).get("extra"),
            "checkpoint": ckpt.name,
            "createdAt": created,
            "vocalkeepVersion": __version__,
            "onnxSha256": sha256_file(onnx_path),
        }
        (staging / "voice.json").write_text(
            json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if target.exists():
            shutil.rmtree(target)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    reporter.progress("export", 1.0, f"Voice ready: {target}")
    return load_voice(target)
