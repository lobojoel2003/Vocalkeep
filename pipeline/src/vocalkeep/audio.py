# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio helpers: decibels, reading and writing WAV files, and resampling.

Vocalkeep records 16-bit PCM mono WAV at the microphone's own rate. This module reads that and
anything else a WAV file commonly holds (8/16/24/32-bit PCM, 32/64-bit float, the "extensible"
header, more than one channel) using only the standard library and numpy, so people can bring
recordings made elsewhere too. Writing is always 16-bit PCM mono, which is what Piper trains on.

The conversions match ``crates/vocalkeep-core/src/audio.rs`` so both quality checkers measure
the same numbers.
"""

from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from vocalkeep.errors import VocalkeepError

#: The quietest level we report. Digital silence would otherwise be minus infinity.
MIN_DBFS = -96.0

FloatArray = npt.NDArray[np.float32]

_WAVE_FORMAT_PCM = 0x0001
_WAVE_FORMAT_IEEE_FLOAT = 0x0003
_WAVE_FORMAT_EXTENSIBLE = 0xFFFE


def amplitude_to_dbfs(amplitude: float) -> float:
    """Converts a linear amplitude (0..1) to dBFS."""
    if amplitude <= 0.0 or not math.isfinite(amplitude):
        return MIN_DBFS
    return max(20.0 * math.log10(amplitude), MIN_DBFS)


def power_to_dbfs(power: float) -> float:
    """Converts mean power (mean of squared samples) to dBFS."""
    if power <= 0.0 or not math.isfinite(power):
        return MIN_DBFS
    return max(10.0 * math.log10(power), MIN_DBFS)


def dbfs_to_amplitude(dbfs: float) -> float:
    """Converts dBFS to a linear amplitude."""
    return float(10.0 ** (dbfs / 20.0))


def rms_dbfs(samples: npt.NDArray[np.floating]) -> float:
    """Root-mean-square level of a block in dBFS."""
    if samples.size == 0:
        return MIN_DBFS
    values = samples.astype(np.float64)
    return power_to_dbfs(float(np.mean(values * values)))


def peak_dbfs(samples: npt.NDArray[np.floating]) -> float:
    """Peak absolute sample value of a block in dBFS."""
    if samples.size == 0:
        return MIN_DBFS
    return amplitude_to_dbfs(float(np.max(np.abs(samples))))


@dataclass
class Clip:
    """A mono recording in memory: float samples in -1..1."""

    sample_rate: int
    samples: FloatArray

    @property
    def duration_ms(self) -> int:
        if self.sample_rate <= 0:
            return 0
        return (len(self.samples) * 1000) // self.sample_rate

    def samples_for_ms(self, ms: int) -> int:
        """Samples for ``ms`` milliseconds at this clip's rate."""
        return (self.sample_rate * ms) // 1000


@dataclass(frozen=True)
class WavFormat:
    """What a WAV file's header says about its audio."""

    format_tag: int
    channels: int
    sample_rate: int
    bits_per_sample: int

    @property
    def is_float(self) -> bool:
        return self.format_tag == _WAVE_FORMAT_IEEE_FLOAT


def _not_wav(path: Path, why: str) -> VocalkeepError:
    return VocalkeepError(
        f"{path.name} couldn't be read as a WAV recording ({why}).",
        "Vocalkeep needs WAV files. If this recording came from elsewhere, "
        "save it again as WAV and try once more.",
    )


def _parse_wav(path: Path, data: bytes) -> tuple[WavFormat, bytes]:
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        if data[0:4] == b"RF64":
            raise _not_wav(path, "it is a very large RF64 file, which isn't supported")
        raise _not_wav(path, "it isn't a WAV file")
    fmt: WavFormat | None = None
    audio: bytes | None = None
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        body_start = pos + 8
        body_end = min(body_start + size, len(data))
        if chunk_id == b"fmt ":
            if body_end - body_start < 16:
                raise _not_wav(path, "its format header is damaged")
            tag, channels, rate, _byte_rate, _align, bits = struct.unpack_from(
                "<HHIIHH", data, body_start
            )
            if tag == _WAVE_FORMAT_EXTENSIBLE and body_end - body_start >= 40:
                # The real format is the first two bytes of the sub-format GUID.
                (tag,) = struct.unpack_from("<H", data, body_start + 24)
            fmt = WavFormat(tag, channels, rate, bits)
        elif chunk_id == b"data":
            # Recorders that were interrupted sometimes leave a wrong size; read what is there.
            audio = data[body_start:body_end]
            if fmt is not None:
                break
        pos = body_start + size + (size & 1)
    if fmt is None:
        raise _not_wav(path, "it has no format header")
    if audio is None:
        raise _not_wav(path, "it has no audio in it")
    return fmt, audio


def _decode(path: Path, fmt: WavFormat, audio: bytes) -> FloatArray:
    bits = fmt.bits_per_sample
    channels = max(fmt.channels, 1)
    if fmt.format_tag == _WAVE_FORMAT_IEEE_FLOAT:
        if bits == 32:
            dtype: str = "<f4"
        elif bits == 64:
            dtype = "<f8"
        else:
            raise _not_wav(path, f"{bits}-bit floating point audio isn't supported")
        width = bits // 8
        usable = len(audio) - len(audio) % (width * channels)
        values = np.frombuffer(audio[:usable], dtype=dtype).astype(np.float32)
    elif fmt.format_tag == _WAVE_FORMAT_PCM:
        if bits not in (8, 16, 24, 32):
            raise _not_wav(path, f"{bits}-bit audio isn't supported")
        width = bits // 8
        usable = len(audio) - len(audio) % (width * channels)
        raw = audio[:usable]
        scale = np.float32(1 << (bits - 1))
        ints: npt.NDArray[np.int64]
        if bits == 8:
            ints = np.frombuffer(raw, dtype=np.uint8).astype(np.int64) - 128
        elif bits == 16:
            ints = np.frombuffer(raw, dtype="<i2").astype(np.int64)
        elif bits == 24:
            b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
            ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
            ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        else:
            ints = np.frombuffer(raw, dtype="<i4").astype(np.int64)
        values = ints.astype(np.float32) / scale
    else:
        raise _not_wav(path, f"its encoding (format {fmt.format_tag}) isn't plain PCM")
    if channels > 1:
        frames = values.reshape(-1, channels)
        values = (frames.sum(axis=1, dtype=np.float32) / np.float32(channels)).astype(np.float32)
    return np.ascontiguousarray(values, dtype=np.float32)


def read_wav(path: str | Path) -> Clip:
    """Reads a PCM or float WAV file and mixes it to mono."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise VocalkeepError(f"The recording {path} is missing.") from None
    except OSError as e:
        raise VocalkeepError(f"The recording {path} couldn't be opened: {e.strerror}.") from e
    fmt, audio = _parse_wav(path, data)
    if fmt.sample_rate <= 0:
        raise _not_wav(path, "its sample rate is 0")
    return Clip(fmt.sample_rate, _decode(path, fmt, audio))


def to_int16(samples: npt.NDArray[np.floating]) -> npt.NDArray[np.int16]:
    """Float samples to 16-bit PCM. Full scale maps to ±32767 so a round trip never clips."""
    clean = np.nan_to_num(samples.astype(np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
    return np.round(np.clip(clean, -1.0, 1.0) * 32767.0).astype(np.int16)


def write_wav(path: str | Path, clip: Clip) -> None:
    """Writes a mono clip as 16-bit PCM WAV. Samples outside -1..1 are clamped."""
    path = Path(path)
    if clip.sample_rate <= 0:
        raise VocalkeepError("A WAV file can't be written with a sample rate of 0.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(clip.sample_rate)
        w.writeframes(to_int16(clip.samples).astype("<i2").tobytes())


def resample(samples: FloatArray, from_rate: int, to_rate: int) -> FloatArray:
    """Changes the sample rate with a high-quality resampler (libsoxr)."""
    if from_rate == to_rate or samples.size == 0:
        return np.array(samples, dtype=np.float32, copy=True)
    import soxr

    out = soxr.resample(np.asarray(samples, dtype=np.float32), from_rate, to_rate, quality="VHQ")
    return np.ascontiguousarray(out, dtype=np.float32)
