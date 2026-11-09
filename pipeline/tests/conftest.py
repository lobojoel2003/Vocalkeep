# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared test helpers: synthetic voice banks, tiny voices and a temporary home folder."""

from __future__ import annotations

import json
import math
import os
import struct
import sys
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest

PIPELINE = Path(__file__).resolve().parent.parent
REPO = PIPELINE.parent
FIXTURES = REPO / "shared" / "fixtures"

TEXT = "The quick brown fox jumps."


def db_to_amp(db: float) -> float:
    return float(10 ** (db / 20))


def synth(
    rate: int = 48000,
    lead: float = 0.4,
    speech: float = 1.6,
    gap: float = 0.0,
    tail: float = 0.4,
    level: float = -20.0,
    noise: float = -70.0,
    seed: int = 42,
) -> np.ndarray:
    """A take: noise, then a voiced, syllable-shaped tone (like scripts/make_fixtures.py)."""
    rng = np.random.default_rng(seed)
    total = lead + speech + gap + tail
    n = round(rate * total)
    samples = (rng.random(n) * 2 - 1) * db_to_amp(noise) * math.sqrt(3)
    half = speech / 2
    voiced = np.zeros(n)
    mask = np.zeros(n, dtype=bool)
    for start, length in ((lead, half), (lead + half + gap, speech - half)):
        first = int(start * rate)
        count = int(length * rate)
        if count <= 0:
            continue
        t = np.arange(count) / rate
        f0 = 140 + 12 * np.sin(2 * np.pi * 0.7 * t)
        phase = 2 * np.pi * f0 * t
        tone = sum(np.sin(phase * h) / h for h in range(1, 7))
        syllable = np.abs(np.sin(np.pi * 4 * t)) ** 0.6
        end = min(first + count, n)
        voiced[first:end] = (tone * syllable)[: end - first]
        mask[first:end] = True
    if mask.any():
        rms = math.sqrt(float(np.mean(voiced[mask] ** 2)))
        samples = samples + voiced * (db_to_amp(level) / rms)
    return np.clip(samples, -1, 1).astype(np.float32)


def write_wav16(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ints = np.round(np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(ints.tobytes())


@dataclass
class TakeSpec:
    prompt_id: str
    text: str = TEXT
    set_id: str = "arctic-en"
    params: dict[str, Any] = field(default_factory=dict)
    write_audio: bool = True


def make_bank(
    root: Path,
    takes: list[TakeSpec],
    *,
    rate: int = 48000,
    name: str = "Jane Doe",
    language: str = "en-US",
    gender: str | None = "female",
    bank_id: str = "0b1c2d3e-0000-4000-8000-000000000001",
) -> Path:
    """Writes a voice bank (bank.json + 16-bit WAVs at ``rate``) like the desktop app does."""
    root.mkdir(parents=True, exist_ok=True)
    manifest_takes = []
    for i, spec in enumerate(takes):
        rel = f"recordings/{spec.set_id}/{spec.prompt_id}.wav"
        samples = synth(rate, seed=100 + i, **spec.params)
        if spec.write_audio:
            write_wav16(root / rel, samples, rate)
        manifest_takes.append(
            {
                "promptId": spec.prompt_id,
                "setId": spec.set_id,
                "text": spec.text,
                "file": rel,
                "sampleRate": rate,
                "durationMs": len(samples) * 1000 // rate,
                "recordedAt": "2026-10-01T10:00:00Z",
                "sessionId": "s1",
                "attempts": 1,
                # Deliberately optimistic: the pipeline must re-check the audio itself.
                "quality": {"verdict": "good", "issues": []},
            }
        )
    speaker: dict[str, Any] = {"name": name, "language": language}
    if gender:
        speaker["gender"] = gender
    manifest = {
        "format": "vocalkeep-bank",
        "version": 1,
        "id": bank_id,
        "createdAt": "2026-10-01T09:00:00Z",
        "updatedAt": "2026-10-01T11:00:00Z",
        "appVersion": "0.1.0",
        "speaker": speaker,
        "takes": manifest_takes,
        "sessions": [],
        "customPrompts": [],
        "legacy": [],
    }
    (root / "bank.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return root


LONG = {"speech": 2.5}


def default_takes() -> list[TakeSpec]:
    return [
        TakeSpec("arctic_a0001", "Author of the danger trail, Philip Steels, etc.", params=LONG),
        TakeSpec(
            "arctic_a0002", "Not at this particular case, Tom, apologized Whittemore.", params=LONG
        ),
        TakeSpec(
            "arctic_a0003",
            "For the twentieth time | that evening\nthe two men shook hands.",
            params=LONG,
        ),
        TakeSpec("quiet_one", TEXT, params={"level": -34.0, "noise": -85.0}),
        TakeSpec("clipped_one", TEXT, params={"level": 2.0}),
        TakeSpec("missing_one", TEXT, write_audio=False),
        TakeSpec("no_text", "   "),
    ]


# A small but realistic Piper phoneme map (the real one has ~150 symbols).
PHONEME_ID_MAP: dict[str, list[int]] = {
    "_": [0],
    "^": [1],
    "$": [2],
    " ": [3],
    "!": [4],
    "'": [5],
    "\n": [6],
    ",": [8],
    ".": [10],
    "a": [14],
    "b": [15],
    "ə": [59],
    "ˈ": [120],
}


def piper_config(sample_rate: int = 22050, espeak: str = "en-us") -> dict[str, Any]:
    return {
        "audio": {"sample_rate": sample_rate},
        "espeak": {"voice": espeak},
        "phoneme_type": "espeak",
        "num_symbols": 256,
        "num_speakers": 1,
        "inference": {"noise_scale": 0.667, "length_scale": 1.0, "noise_w": 0.8},
        "phoneme_id_map": PHONEME_ID_MAP,
        "speaker_id_map": {},
        "piper_version": "1.5.0",
    }


def tiny_onnx(path: Path, padding: int = 0) -> Path:
    """A valid, tiny ONNX model with Piper's input/output names (it doesn't speak)."""
    import onnx
    from onnx import TensorProto, helper

    inputs = [
        helper.make_tensor_value_info("input", TensorProto.INT64, ["batch_size", "phonemes"]),
        helper.make_tensor_value_info("input_lengths", TensorProto.INT64, ["batch_size"]),
        helper.make_tensor_value_info("scales", TensorProto.FLOAT, [3]),
    ]
    output = helper.make_tensor_value_info("output", TensorProto.FLOAT, ["batch_size", "phonemes"])
    nodes = [helper.make_node("Cast", ["input"], ["output"], to=TensorProto.FLOAT)]
    initializers = []
    if padding:
        initializers.append(
            helper.make_tensor("pad", TensorProto.FLOAT, [padding], [0.0] * padding)
        )
    graph = helper.make_graph(nodes, "tiny_piper", inputs, [output], initializer=initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 15)])
    model.metadata_props.add(key="old", value="should be removed")
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))
    return path


def make_voice(
    root: Path,
    voice_id: str = "en_US-jane_doe-medium",
    *,
    with_info: bool = True,
    gender: str | None = "female",
) -> Path:
    """A voice folder like 'vocalkeep export' makes, with a tiny model."""
    folder = root / voice_id
    tiny_onnx(folder / f"{voice_id}.onnx", padding=64)
    config = piper_config()
    config["language"] = {"code": voice_id.split("-", maxsplit=1)[0]}
    (folder / f"{voice_id}.onnx.json").write_text(
        json.dumps(config, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "MODEL_CARD").write_text(
        f"# Model card for {voice_id}\n\nThis is Jane Doe's own voice.\n", encoding="utf-8"
    )
    if with_info:
        (folder / "voice.json").write_text(
            json.dumps(
                {
                    "format": "vocalkeep-voice",
                    "version": 1,
                    "id": voice_id,
                    "name": "Jane Doe",
                    "language": "en-US",
                    "gender": gender,
                    "sampleRate": 22050,
                }
            ),
            encoding="utf-8",
        )
    return folder


def make_espeak_data(root: Path) -> Path:
    data = root / "espeak-ng-data"
    (data / "voices" / "gmw").mkdir(parents=True)
    (data / "phontab").write_bytes(b"\x00" * 16)
    (data / "en_dict").write_bytes(b"dict")
    (data / "voices" / "gmw" / "en-US").write_text("name English (America)\n")
    return data


def write_raw_wav(
    path: Path, data: bytes, *, tag: int, channels: int, rate: int, bits: int, extensible=False
) -> None:
    """Writes a WAV with any format tag (the stdlib can't write float or extensible)."""
    block = channels * bits // 8
    if extensible:
        guid_tail = b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt = (
            struct.pack(
                "<HHIIHHHHI", 0xFFFE, channels, rate, rate * block, block, bits, 22, bits, 0
            )
            + struct.pack("<H", tag)
            + guid_tail
        )
    else:
        fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"LIST" + struct.pack("<I", 4) + b"INFO"  # an extra chunk to skip
    body += b"data" + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


def posix_script(path: Path, body: str) -> Path:
    """An executable script run by this Python; stands in for another interpreter in tests.

    Windows can't run a script file as a program without a launcher, so such tests skip there.
    """
    if os.name == "nt":
        pytest.skip("uses a POSIX script as a stand-in Python")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A temporary home folder with every location Vocalkeep writes to inside it."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("VOCALKEEP_CACHE_DIR", str(h / ".cache" / "vocalkeep"))
    monkeypatch.setenv("LOCALAPPDATA", str(h / "AppData" / "Local"))
    yield h


@pytest.fixture
def bank_dir(tmp_path: Path) -> Path:
    return make_bank(tmp_path / "Jane's voice bank", default_takes())
