# SPDX-License-Identifier: GPL-3.0-or-later
"""The quality checker must agree with shared/fixtures/expected.json (as the Rust one does)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import FIXTURES, synth
from vocalkeep.audio import Clip, read_wav
from vocalkeep.quality import (
    ISSUE_CODES,
    ISSUE_MESSAGES,
    Issue,
    analyze,
    analyze_room,
    config,
    verdict_for,
)


def _cases() -> list[dict]:
    path = FIXTURES / "expected.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(not (FIXTURES / "expected.json").is_file(), reason="shared fixtures absent")
def test_fixtures_match_expected_verdicts() -> None:
    cases = _cases()
    assert len(cases) >= 10
    failures = []
    for case in cases:
        a = analyze(read_wav(FIXTURES / case["file"]), case["text"])
        got = sorted(a.codes)
        want = sorted(case["issues"])
        if a.verdict != case["verdict"] or got != want:
            failures.append(
                f"{case['file']}: expected {case['verdict']} {want}, got {a.verdict} {got} "
                f"(speech {a.speech_dbfs:.1f} dBFS, noise {a.noise_floor_dbfs:.1f} dBFS, "
                f"snr {a.snr_db:.1f} dB)"
            )
    assert not failures, "\n".join(failures)


def test_config_matches_shared_copy() -> None:
    cfg = config()
    assert cfg.version == 1
    assert cfg.quiet_redo_dbfs < cfg.quiet_warn_dbfs
    assert cfg.noise_warn_dbfs < cfg.noise_redo_dbfs
    assert cfg.snr_redo_db < cfg.snr_warn_db
    assert cfg.training.trim_pad_ms > 0
    assert cfg.training.min_verdict == "okay"


def test_clean_take_is_good() -> None:
    clip = Clip(16000, synth(16000))
    a = analyze(clip, "The quick brown fox jumps.")
    assert a.verdict == "good", a.codes
    assert a.snr_db > 40
    assert a.speech_start_ms is not None and a.speech_start_ms >= 300
    assert a.speech_end_ms is not None and a.speech_end_ms <= 2100


def test_empty_and_tiny_clips_have_no_speech() -> None:
    for samples in (np.zeros(0, dtype=np.float32), np.zeros(10, dtype=np.float32)):
        a = analyze(Clip(16000, samples), None)
        assert a.verdict == "redo"
        assert a.has("no-speech")


def test_single_click_is_not_speech() -> None:
    samples = synth(16000, speech=0.0, lead=1.0, tail=0.5, noise=-75.0)
    samples[8000] = 0.6
    a = analyze(Clip(16000, samples), None)
    assert a.has("no-speech"), a.codes


def test_dc_offset_is_noted_and_removed_before_measuring() -> None:
    samples = synth(16000) + np.float32(0.05)
    a = analyze(Clip(16000, samples), None)
    assert a.has("dc-offset")
    assert a.speech_ms > 500


def test_long_pause() -> None:
    a = analyze(Clip(16000, synth(16000, gap=3.0)), None)
    assert a.has("long-pause")
    assert a.longest_pause_ms >= 2900


def test_any_redo_issue_makes_redo() -> None:
    assert verdict_for([]) == "good"
    assert verdict_for([Issue("too-quiet", "warn")]) == "okay"
    assert verdict_for([Issue("too-quiet", "warn"), Issue("clipping", "redo")]) == "redo"


def test_every_issue_has_a_message() -> None:
    assert set(ISSUE_MESSAGES) == set(ISSUE_CODES)


def test_analysis_serialises_like_the_app() -> None:
    a = analyze(Clip(16000, synth(16000)), None)
    d = a.to_dict()
    assert set(d) == {
        "verdict",
        "issues",
        "sampleRate",
        "durationMs",
        "peakDbfs",
        "speechDbfs",
        "noiseFloorDbfs",
        "snrDb",
        "clippedSamples",
        "clipRuns",
        "dcOffset",
        "speechStartMs",
        "speechEndMs",
        "speechMs",
        "longestPauseMs",
    }


def test_room_levels() -> None:
    def room(db: float) -> str:
        clip = Clip(16000, synth(16000, speech=0.0, lead=2.0, tail=0.0, noise=db))
        return analyze_room(clip).level

    assert room(-70.0) == "quiet"
    assert room(-55.0) == "fine"
    assert room(-45.0) == "noisy"
    assert room(-30.0) == "too-noisy"
