# SPDX-License-Identifier: GPL-3.0-or-later
"""Package contents for every format, and Saywell's import rules (VoiceStore.kt)."""

from __future__ import annotations

import json
import re
import tarfile
import zipfile
from pathlib import Path

import pytest

from conftest import make_espeak_data, make_voice
from vocalkeep.cli import main
from vocalkeep.errors import VocalkeepError
from vocalkeep.package import expand_formats, package_voice
from vocalkeep.sherpa import read_metadata
from vocalkeep.voice import SONATA_VOICE_PATTERN, load_voice

VID = "en_US-jane_doe-medium"


@pytest.fixture
def voice(tmp_path: Path):
    return load_voice(make_voice(tmp_path / "voices"))


@pytest.fixture
def espeak(tmp_path: Path) -> Path:
    return make_espeak_data(tmp_path / "espeak")


def _extract(tar: tarfile.TarFile, dest: Path) -> None:
    if hasattr(tarfile, "data_filter"):
        tar.extractall(dest, filter="data")
    else:  # Python < 3.10.12: names are checked by the caller
        tar.extractall(dest)  # noqa: S202


def _unpack_tar(path: Path, dest: Path) -> list[str]:
    with tarfile.open(path) as tar:
        names = tar.getnames()
        for member in tar.getmembers():
            assert member.uid == 0 and member.uname == ""
            assert not member.name.startswith(("/", "..")) and ".." not in member.name
        _extract(tar, dest)
    return names


def test_piper_and_nvda_package(voice, tmp_path: Path) -> None:
    made = package_voice(voice, ["piper"], tmp_path / "out")
    assert [p.name for p in made] == [f"{VID}.tar.gz"]
    names = _unpack_tar(made[0], tmp_path / "x")
    assert sorted(names) == sorted([f"{VID}.onnx", f"{VID}.onnx.json", "MODEL_CARD"])
    # Sonata (NVDA) takes the first *.json as the config and parses the name from the .onnx.
    jsons = [n for n in names if n.endswith(".json")]
    assert jsons == [f"{VID}.onnx.json"]
    m = SONATA_VOICE_PATTERN.match(f"{VID}.onnx")
    assert m and m.group("name") == "jane_doe"
    assert (tmp_path / "x" / f"{VID}.onnx").read_bytes() == voice.onnx.read_bytes()
    assert package_voice(voice, ["nvda"], tmp_path / "out")[0] == made[0]


def test_sherpa_package(voice, espeak: Path, tmp_path: Path) -> None:
    made = package_voice(voice, ["sherpa"], tmp_path / "out", espeak_data=espeak)
    assert [p.name for p in made] == [f"vits-piper-{VID}.tar.bz2"]
    names = _unpack_tar(made[0], tmp_path / "x")
    folder = f"vits-piper-{VID}"
    assert names[0] == folder
    for expected in (
        f"{folder}/{VID}.onnx",
        f"{folder}/{VID}.onnx.json",
        f"{folder}/tokens.txt",
        f"{folder}/MODEL_CARD",
        f"{folder}/espeak-ng-data/phontab",
        f"{folder}/espeak-ng-data/voices/gmw/en-US",
    ):
        assert expected in names
    root = tmp_path / "x" / folder
    meta = read_metadata(root / f"{VID}.onnx")
    assert meta["model_type"] == "vits" and meta["comment"] == "piper"
    assert meta["language"] == "English" and meta["voice"] == "en-us"
    assert meta["has_espeak"] == "1" and meta["n_speakers"] == "1"
    assert "old" not in meta
    tokens = (root / "tokens.txt").read_text(encoding="utf-8")
    assert "  3\n" in tokens and "_ 0\n" in tokens
    assert read_metadata(voice.onnx) == {"old": "should be removed"}, "source voice untouched"


def test_sherpa_without_espeak_data_warns(voice, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("vocalkeep.package.find_espeak_data", lambda explicit=None: None)
    from io import StringIO

    from vocalkeep.progress import Reporter

    log = StringIO()
    made = package_voice(voice, ["saywell"], tmp_path / "out", reporter=Reporter("text", log))
    with tarfile.open(made[0]) as tar:
        assert not any("espeak-ng-data" in n for n in tar.getnames())
    assert "No espeak-ng data was found" in log.getvalue()


def test_sherpatts_package(voice, tmp_path: Path) -> None:
    made = package_voice(voice, ["sherpatts"], tmp_path / "out")
    assert [p.name for p in made] == [f"{VID}-sherpatts.zip"]
    with zipfile.ZipFile(made[0]) as z:
        names = set(z.namelist())
        assert names == {
            "modelDir/model.onnx",
            "modelDir/tokens.txt",
            "modelDir/lang",
            "modelDir/MODEL_CARD",
            "HOW-TO-INSTALL.txt",
        }
        assert z.read("modelDir/lang").decode() == "eng\nJane Doe\n"
        howto = z.read("HOW-TO-INSTALL.txt").decode()
        assert "Install from SD Card" in howto and "adb push modelDir" in howto
        assert "org.woheller69.ttsengine" in howto and "eng" in howto
        z.extract("modelDir/model.onnx", tmp_path / "x")
    assert read_metadata(tmp_path / "x" / "modelDir" / "model.onnx")["comment"] == "piper"


def test_voicegarden_package(voice, espeak: Path, tmp_path: Path) -> None:
    made = package_voice(voice, ["voicegarden"], tmp_path / "out", espeak_data=espeak)
    assert [p.name for p in made] == [f"{VID}-windows-sapi.zip"]
    with zipfile.ZipFile(made[0]) as z:
        names = set(z.namelist())
        for expected in (
            f"{VID}/model.onnx",
            f"{VID}/tokens.txt",
            f"{VID}/espeak-ng-data/phontab",
            f"{VID}/MODEL_CARD",
            "HOW-TO-INSTALL.txt",
            "register-sapi.reg",
        ):
            assert expected in names
        howto = z.read("HOW-TO-INSTALL.txt").decode()
        assert "VoiceGardenSAPIAdapter\\models" in howto and "Install to SAPI" in howto
        reg = z.read("register-sapi.reg").decode("utf-16")
    assert reg.startswith("Windows Registry Editor Version 5.00")
    assert "EXPERIMENTAL" in reg
    token = rf"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\Sherpa-{VID}"
    assert f"[{token}]" in reg
    assert f"[{token}\\Attributes]" in reg and f"[{token}\\VoiceGardenConfig]" in reg
    assert rf"Speech_OneCore\Voices\Tokens\Sherpa-{VID}" in reg
    assert '"CLSID"="{013AB33B-AD1A-401C-8BEE-F6E2B046A94E}"' in reg
    assert '"Gender"="Female"' in reg and '"Language"="409"' in reg
    assert '"Locale"="en-US"' in reg and '"Vendor"="K2FSA"' in reg
    assert '"VoiceGardenType"="Sherpa;Offline"' in reg
    assert '"SherpaOnnxModelType"=dword:00000000' in reg
    assert f"models\\\\{VID}\\\\model.onnx" in reg


def test_voicegarden_needs_espeak_data(voice, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("vocalkeep.package.find_espeak_data", lambda explicit=None: None)
    with pytest.raises(VocalkeepError, match="needs espeak-ng's data"):
        package_voice(voice, ["voicegarden"], tmp_path / "out")
    made = package_voice(voice, ["all"], tmp_path / "out")
    assert not any(p.name.endswith("windows-sapi.zip") for p in made)


def test_all_formats(voice, espeak: Path, tmp_path: Path) -> None:
    made = package_voice(voice, ["all"], tmp_path / "out", espeak_data=espeak)
    assert [p.name for p in made] == [
        f"{VID}.tar.gz",
        f"vits-piper-{VID}.tar.bz2",
        f"{VID}-sherpatts.zip",
        f"{VID}-windows-sapi.zip",
    ]
    for p in made:  # every archive carries the model card
        if p.suffix == ".zip":
            with zipfile.ZipFile(p) as z:
                assert any(n.endswith("MODEL_CARD") for n in z.namelist())
        else:
            with tarfile.open(p) as tar:
                assert any(n.endswith("MODEL_CARD") for n in tar.getnames())
    assert not list((tmp_path / "out").glob("*.part"))


def test_expand_formats() -> None:
    assert expand_formats(["piper", "nvda", "sherpa", "saywell"]) == ["piper", "sherpa"]
    with pytest.raises(VocalkeepError, match="Unknown package format"):
        expand_formats(["mp3"])


def test_bad_espeak_folder(voice, tmp_path: Path) -> None:
    with pytest.raises(VocalkeepError, match="isn't an espeak-ng data folder"):
        package_voice(voice, ["sherpa"], tmp_path / "out", espeak_data=tmp_path)


def test_package_cli_json(voice, espeak: Path, tmp_path: Path, capsys) -> None:
    args = ["package", str(voice.root), "--format", "piper,sherpatts", "-o", str(tmp_path / "o")]
    assert main([*args, "--json"]) == 0
    captured = capsys.readouterr()
    paths = json.loads(captured.out)
    assert paths == [
        str((tmp_path / "o" / f"{VID}.tar.gz").resolve()),
        str((tmp_path / "o" / f"{VID}-sherpatts.zip").resolve()),
    ]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == paths


# --- Saywell -----------------------------------------------------------------------------------


def saywell_install(staging: Path) -> dict[str, str]:
    """Saywell's VoiceStore.installFrom(), re-implemented: what it would install."""
    files = [p for p in staging.rglob("*") if p.is_file()]
    models = [p for p in files if p.name.endswith(".onnx")]
    if not models:
        raise AssertionError("This file doesn't contain a voice model (.onnx).")
    model = max(models, key=lambda p: p.stat().st_size)
    tokens = next((p for p in files if p.name == "tokens.txt" and p.parent == model.parent), None)
    tokens = tokens or next((p for p in files if p.name == "tokens.txt"), None)
    if tokens is None:
        raise AssertionError("This voice is missing tokens.txt.")
    root = model.parent
    voice_id = root.name.removeprefix("vits-piper-") if root.name != staging.name else model.stem
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", voice_id)
    espeak = next((p.parent for p in files if p.name == "phontab"), None)
    parts = safe_id.split("-")
    return {
        "id": safe_id,
        "model": str(model.relative_to(staging)),
        "tokens": str(tokens.relative_to(staging)),
        "card": "yes" if (root / "MODEL_CARD").is_file() else "no",
        "espeak": "yes" if espeak else "no",
        "name": parts[1].replace("_", " ").capitalize() if len(parts) > 1 else safe_id,
        "language": parts[0].replace("_", "-"),
        "quality": parts[2] if len(parts) > 2 else "",
    }


def test_saywell_accepts_the_package(voice, espeak: Path, tmp_path: Path) -> None:
    made = package_voice(voice, ["saywell"], tmp_path / "out", espeak_data=espeak)
    staging = tmp_path / "voice-install-123"
    staging.mkdir()
    with tarfile.open(made[0]) as tar:
        _extract(tar, staging)
    result = saywell_install(staging)
    assert result == {
        "id": VID,
        "model": f"vits-piper-{VID}/{VID}.onnx",
        "tokens": f"vits-piper-{VID}/tokens.txt",
        "card": "yes",
        "espeak": "yes",
        "name": "Jane doe",
        "language": "en-US",
        "quality": "medium",
    }
    # Saywell refuses archives over 600 MB once unpacked.
    unpacked = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    assert unpacked < 600 * 1024 * 1024
    # Saywell sniffs the archive type from its first bytes: bzip2 must start with "BZh".
    assert made[0].read_bytes()[:3] == b"BZh"
