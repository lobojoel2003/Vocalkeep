#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate shared/fixtures/: short synthetic takes with the verdict each should get.

    python3 scripts/make_fixtures.py

Both quality checkers (Rust in crates/vocalkeep-core, Python in pipeline/) are tested against
these files, so a change to one that isn't made to the other fails CI. Standard library only.
"""

from __future__ import annotations

import json
import math
import random
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "shared" / "fixtures"
RATE = 8000

TEXT = "The quick brown fox jumps."
LONG_TEXT = "This sentence has far too many letters to fit in a little over half a second."

# name: (synth parameters, text, expected verdict, expected issue codes)
CASES: dict[str, tuple[dict, str | None, str, list[str]]] = {
    "good": ({}, TEXT, "good", []),
    "quiet": ({"level": -34.0, "noise": -85.0}, TEXT, "okay", ["too-quiet"]),
    "very-quiet": ({"level": -46.0, "noise": -85.0}, TEXT, "redo", ["too-quiet"]),
    "clipped": ({"level": 2.0}, TEXT, "redo", ["clipping"]),
    "noisy": ({"noise": -34.0}, TEXT, "redo", ["noisy"]),
    "low-snr": ({"level": -28.0, "noise": -52.0}, TEXT, "okay", ["low-snr"]),
    "cut-off-end": ({"tail": 0.0}, TEXT, "redo", ["cut-off-end"]),
    "early-start": ({"lead": 0.0}, TEXT, "okay", ["cut-off-start"]),
    "long-pause": ({"gap": 3.0}, TEXT, "okay", ["long-pause"]),
    "too-fast": ({"speech": 0.6}, LONG_TEXT, "okay", ["too-fast"]),
    "silence": ({"speech": 0.0, "lead": 1.0, "tail": 0.5}, None, "redo", ["no-speech"]),
}


def db_to_amp(db: float) -> float:
    return 10 ** (db / 20)


def synth(
    lead: float = 0.4,
    speech: float = 1.6,
    gap: float = 0.0,
    tail: float = 0.4,
    level: float = -20.0,
    noise: float = -70.0,
    seed: int = 42,
) -> list[float]:
    rng = random.Random(seed)
    total = lead + speech + gap + tail
    n = round(RATE * total)
    amp = db_to_amp(noise) * math.sqrt(3)
    samples = [(rng.random() * 2 - 1) * amp for _ in range(n)]
    half = speech / 2
    voiced: list[tuple[int, float]] = []
    for start, length in ((lead, half), (lead + half + gap, speech - half)):
        first = int(start * RATE)
        for i in range(int(length * RATE)):
            t = i / RATE
            f0 = 140 + 12 * math.sin(2 * math.pi * 0.7 * t)
            phase = 2 * math.pi * f0 * t
            tone = sum(math.sin(phase * h) / h for h in range(1, 7))
            syllable = abs(math.sin(math.pi * 4 * t)) ** 0.6
            voiced.append((first + i, tone * syllable))
    if voiced:
        rms = math.sqrt(sum(v * v for _, v in voiced) / len(voiced))
        gain = db_to_amp(level) / rms
        for i, v in voiced:
            if i < n:
                samples[i] = max(-1.0, min(1.0, samples[i] + v * gain))
    return samples


def write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(
            b"".join(struct.pack("<h", round(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expected = []
    for name, (params, text, verdict, issues) in CASES.items():
        write_wav(OUT / f"{name}.wav", synth(**params))
        expected.append({"file": f"{name}.wav", "text": text, "verdict": verdict, "issues": issues})
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(expected)} fixtures to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
