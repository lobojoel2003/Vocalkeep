# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional: speak and package with a real Piper voice.

    VOCALKEEP_TEST_VOICE=/path/to/voice-folder-or-model.onnx pytest -m integration

Needs piper-tts (``pip install 'vocalkeep[runtime]'``).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import wave
from pathlib import Path

import pytest

from vocalkeep.cli import main
from vocalkeep.voice import load_voice

VOICE = os.environ.get("VOCALKEEP_TEST_VOICE")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not VOICE, reason="set VOCALKEEP_TEST_VOICE to a Piper voice"),
]


@pytest.fixture(scope="module")
def voice_path() -> Path:
    pytest.importorskip("piper")
    assert VOICE
    return Path(VOICE)


def test_speak_to_file(voice_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "hello.wav"
    assert main(["speak", str(voice_path), "Hello, this is a test.", "-o", str(out)]) == 0
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getframerate() == load_voice(voice_path).sample_rate
        assert w.getnframes() > w.getframerate() // 2  # at least half a second of speech
    slow = tmp_path / "slow.wav"
    assert (
        main(
            [
                "speak",
                str(voice_path),
                "Hello, this is a test.",
                "-o",
                str(slow),
                "--length-scale",
                "1.5",
            ]
        )
        == 0
    )
    with wave.open(str(out)) as a, wave.open(str(slow)) as b:
        assert b.getnframes() > a.getnframes()


def test_package_every_format(voice_path: Path, tmp_path: Path, capsys) -> None:
    assert main(["package", str(voice_path), "--format", "all", "-o", str(tmp_path), "--json"]) == 0
    import json

    paths = [Path(p) for p in json.loads(capsys.readouterr().out)]
    assert any(p.name.startswith("vits-piper-") for p in paths)
    sherpa = next(p for p in paths if p.name.endswith(".tar.bz2"))
    with tarfile.open(sherpa) as tar:
        names = tar.getnames()
    assert any(n.endswith("espeak-ng-data/phontab") for n in names)
    assert any(n.endswith("tokens.txt") for n in names)


def test_linux_wrapper_makes_audio(voice_path: Path, tmp_path: Path, monkeypatch) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux only")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert main(["install", str(voice_path), "--target", "linux"]) == 0
    wrapper = home / ".local" / "share" / "vocalkeep" / "bin" / "vocalkeep-speak"
    raw = tmp_path / "out.raw"
    env = dict(os.environ, VOCALKEEP_PLAYER=f"cat > {raw}")
    voice_id = load_voice(voice_path).id
    proc = subprocess.run(
        [str(wrapper), voice_id, "0"],
        input=b"Hello from Speech Dispatcher.",
        env=env,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode()
    data = raw.read_bytes()
    assert len(data) > 22050  # more than half a second of 16-bit audio
    assert len(data) % 2 == 0
