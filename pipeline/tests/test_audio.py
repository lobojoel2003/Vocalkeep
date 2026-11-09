# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest

from conftest import write_raw_wav
from vocalkeep.audio import (
    MIN_DBFS,
    Clip,
    amplitude_to_dbfs,
    dbfs_to_amplitude,
    peak_dbfs,
    power_to_dbfs,
    read_wav,
    resample,
    rms_dbfs,
    write_wav,
)
from vocalkeep.errors import VocalkeepError

VALUES = np.array([0.0, 0.5, -0.5, 0.25, -1.0, 0.75], dtype=np.float32)


def test_decibels() -> None:
    assert amplitude_to_dbfs(1.0) == pytest.approx(0.0)
    assert amplitude_to_dbfs(0.5) == pytest.approx(-6.0206, abs=1e-3)
    assert amplitude_to_dbfs(0.0) == MIN_DBFS
    assert power_to_dbfs(0.0) == MIN_DBFS
    assert dbfs_to_amplitude(-20.0) == pytest.approx(0.1)
    sine = 0.5 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)
    assert peak_dbfs(sine) - rms_dbfs(sine) == pytest.approx(3.01, abs=0.05)


def test_round_trip_16_bit(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "take.wav"
    write_wav(path, Clip(22050, np.array([0.0, 0.5, -0.5, 1.0, -1.0, 2.0], dtype=np.float32)))
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
    back = read_wav(path)
    assert back.sample_rate == 22050
    assert len(back.samples) == 6
    assert back.samples[1] == pytest.approx(0.5, abs=1e-3)
    assert back.samples[5] <= 1.0


@pytest.mark.parametrize(
    ("tag", "bits", "encode"),
    [
        (1, 8, lambda v: (np.round(v * 127) + 128).astype(np.uint8).tobytes()),
        (1, 16, lambda v: np.round(v * 32767).astype("<i2").tobytes()),
        (
            1,
            24,
            lambda v: b"".join(
                int(x).to_bytes(3, "little", signed=True) for x in np.round(v * 8388607)
            ),
        ),
        (1, 32, lambda v: np.round(v * 2147483647).astype("<i4").tobytes()),
        (3, 32, lambda v: v.astype("<f4").tobytes()),
        (3, 64, lambda v: v.astype("<f8").tobytes()),
    ],
)
@pytest.mark.parametrize("extensible", [False, True])
def test_reads_common_wav_formats(tmp_path: Path, tag, bits, encode, extensible) -> None:
    path = tmp_path / "x.wav"
    write_raw_wav(
        path, encode(VALUES), tag=tag, channels=1, rate=44100, bits=bits, extensible=extensible
    )
    clip = read_wav(path)
    assert clip.sample_rate == 44100
    tolerance = 1 / 100 if bits == 8 else 1e-4
    np.testing.assert_allclose(clip.samples, VALUES, atol=tolerance)


def test_stereo_is_mixed_to_mono(tmp_path: Path) -> None:
    stereo = np.array([1.0, 0.0, 0.5, 0.5, -0.5, 0.0], dtype=np.float32)
    path = tmp_path / "s.wav"
    write_raw_wav(path, stereo.astype("<f4").tobytes(), tag=3, channels=2, rate=48000, bits=32)
    clip = read_wav(path)
    np.testing.assert_allclose(clip.samples, [0.5, 0.5, -0.25])


def test_truncated_data_chunk_is_read(tmp_path: Path) -> None:
    path = tmp_path / "t.wav"
    write_raw_wav(path, np.zeros(100, "<i2").tobytes(), tag=1, channels=1, rate=8000, bits=16)
    data = bytearray(path.read_bytes())
    data += b"\x01\x00" * 10  # samples after the declared end are ignored, short files are fine
    path.write_bytes(bytes(data[:-50]))
    assert len(read_wav(path).samples) > 0


def test_kind_errors(tmp_path: Path) -> None:
    with pytest.raises(VocalkeepError, match="missing"):
        read_wav(tmp_path / "nope.wav")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"ID3 not a wav at all")
    with pytest.raises(VocalkeepError, match="isn't a WAV file"):
        read_wav(bad)
    mp3ish = tmp_path / "comp.wav"
    write_raw_wav(mp3ish, b"\x00" * 10, tag=0x55, channels=1, rate=8000, bits=16)
    with pytest.raises(VocalkeepError, match="isn't plain PCM"):
        read_wav(mp3ish)


def test_resample_changes_length_and_keeps_level() -> None:
    t = np.arange(48000) / 48000
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    out = resample(tone, 48000, 22050)
    assert abs(len(out) - 22050) <= 2
    assert out.dtype == np.float32
    assert rms_dbfs(out) == pytest.approx(rms_dbfs(tone), abs=0.1)
    assert resample(tone, 22050, 22050) is not tone
