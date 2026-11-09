# SPDX-License-Identifier: GPL-3.0-or-later
"""Speaking a sentence with a voice.

Needs Piper's runtime: ``pip install 'vocalkeep[runtime]'`` (or ``pip install piper-tts``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

from vocalkeep.errors import VocalkeepError
from vocalkeep.voice import Voice


def _piper() -> Any:
    try:
        import piper
    except ImportError as e:
        raise VocalkeepError(
            "Speaking needs Piper's runtime, which isn't installed.",
            "Install it with:  pip install 'vocalkeep[runtime]'   (or: pip install piper-tts)",
        ) from e
    return piper


def synthesize(voice: Voice, text: str, out: Path, length_scale: float = 1.0) -> Path:
    """Writes ``text`` spoken by ``voice`` to the WAV file ``out``."""
    text = text.strip()
    if not text:
        raise VocalkeepError("There is no text to speak.")
    if not 0.1 <= length_scale <= 10:
        raise VocalkeepError("--length-scale should be between 0.1 and 10 (1.0 is normal speed).")
    piper = _piper()
    try:
        model = piper.PiperVoice.load(str(voice.onnx), config_path=str(voice.config_path))
    except Exception as e:  # onnxruntime raises its own exception types
        raise VocalkeepError(f"The voice {voice.id} couldn't be loaded: {e}") from e
    syn_config = piper.SynthesisConfig(length_scale=length_scale)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wav:
        model.synthesize_wav(text, wav, syn_config=syn_config)
    return out


def _player_for(path: Path) -> list[str] | None:
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", str(path)]
    for cmd in (["paplay"], ["pw-play"], ["aplay", "-q"], ["ffplay", "-nodisp", "-autoexit"]):
        if shutil.which(cmd[0]):
            return [*cmd, str(path)]
    return None


def play(path: Path) -> None:
    """Plays a WAV file through the speakers."""
    if sys.platform == "win32":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return
    cmd = _player_for(path)
    if cmd is None:
        raise VocalkeepError(
            "No audio player was found to play the sound.",
            "Save it to a file instead with -o out.wav, or install pulseaudio-utils "
            "(paplay) or alsa-utils (aplay).",
        )
    proc = subprocess.run(
        cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise VocalkeepError(
            f"The sound couldn't be played ({cmd[0]}: {detail[-1] if detail else 'failed'}).",
            "Check that the speakers or headphones are connected, or save it to a file "
            "with -o out.wav.",
        )


def speak(
    voice: Voice, text: str, out: Path | None = None, length_scale: float = 1.0
) -> Path | None:
    """Speaks ``text``: to ``out`` if given, otherwise through the speakers."""
    if out is not None:
        return synthesize(voice, text, out, length_scale)
    with tempfile.TemporaryDirectory(prefix="vocalkeep-speak-") as tmp:
        wav = synthesize(voice, text, Path(tmp) / "speech.wav", length_scale)
        play(wav)
    return None
