# SPDX-License-Identifier: GPL-3.0-or-later
"""The command-line contract the desktop app relies on."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import vocalkeep.export as export_module
from conftest import posix_script, tiny_onnx
from test_train import FAKE_PIPER
from vocalkeep import __version__
from vocalkeep.cli import main

DOCTOR_KEYS = {
    "version": str,
    "python": str,
    "platform": str,
    "piperRuntime": bool,
    "piperTrain": bool,
    "torch": bool,
    "cuda": bool,
    "canSpeak": bool,
    "canTrain": bool,
    "nextSteps": list,
}


def _json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.mark.parametrize("extra", [["--no-torch"], []])
def test_doctor_json(capsys: pytest.CaptureFixture[str], extra: list[str]) -> None:
    assert main(["doctor", "--json", *extra]) == 0
    report = json.loads(capsys.readouterr().out)
    for key, kind in DOCTOR_KEYS.items():
        assert isinstance(report[key], kind), key
    assert report["version"] == __version__
    assert report["gpuName"] is None or isinstance(report["gpuName"], str)
    assert report["espeakData"] is None or isinstance(report["espeakData"], str)
    assert report["nextStep"] is None or report["nextStep"] == report["nextSteps"][0]
    assert all(k[0].islower() and "_" not in k for k in report)
    if not report["canTrain"]:
        assert any("piper1-gpl" in s for s in report["nextSteps"])


def test_doctor_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--no-torch"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Vocalkeep {__version__}")
    assert "Can train voices" in out


def test_doctor_with_another_python(capsys, tmp_path: Path) -> None:
    fake = posix_script(tmp_path / "py", FAKE_PIPER)
    assert main(["doctor", "--json", "--python", str(fake)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["piperTrain"] is True and report["canTrain"] is True
    assert main(["doctor", "--json", "--python", str(tmp_path / "nope")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["canTrain"] is False and "There is no Python" in report["nextStep"]


def test_bases_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bases", "--json"]) == 0
    bases = json.loads(capsys.readouterr().out)
    assert isinstance(bases, list) and len(bases) >= 20
    first = bases[0]
    for key in (
        "id",
        "name",
        "language",
        "quality",
        "dataset",
        "license",
        "commercial",
        "lineage",
        "recommended",
        "notes",
        "checkpointUrl",
        "sources",
    ):
        assert key in first
    assert first["recommended"] is True
    assert first["id"] == "en_US-ljspeech-medium"
    assert first["name"] == "LJ Speech (US English)"


def test_bases_filters(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bases", "--json", "--commercial", "--language", "en-US"]) == 0
    ids = [b["id"] for b in json.loads(capsys.readouterr().out)]
    assert ids[:2] == ["en_US-ljspeech-medium", "en_US-kristin-medium"]
    assert "en_US-lessac-medium" not in ids and "en_GB-cori-medium" not in ids
    assert main(["bases"]) == 0
    assert "LJ Speech" in capsys.readouterr().out


def test_usage_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["train"]) == 2
    assert main(["package", "x", "--format", "piper"]) == 2  # -o missing
    assert main(["nonsense"]) == 2
    assert main([]) == 2
    capsys.readouterr()


def test_user_errors_exit_1_without_traceback(tmp_path: Path, capsys) -> None:
    assert main(["check", str(tmp_path / "nothing")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: There is no voice bank")
    assert "Traceback" not in err
    assert main(["--debug", "check", str(tmp_path / "nothing")]) == 1
    assert "Traceback" in capsys.readouterr().err
    assert main(["check", str(tmp_path / "nothing"), "--debug"]) == 1
    assert "Traceback" in capsys.readouterr().err


def test_json_progress_errors_are_events(tmp_path: Path, capsys) -> None:
    code = main(["prepare", str(tmp_path / "x"), "-o", str(tmp_path / "d"), "--progress", "json"])
    assert code == 1
    captured = capsys.readouterr()
    events = _json_lines(captured.out)
    assert events[-1]["event"] == "error"
    assert "There is no voice bank" in events[-1]["message"]
    assert "Error:" in captured.err


def test_speak_without_runtime_is_kind(tmp_path: Path, capsys, monkeypatch) -> None:
    from conftest import make_voice

    monkeypatch.setitem(sys.modules, "piper", None)  # as if piper-tts weren't installed
    voice = make_voice(tmp_path)
    assert main(["speak", str(voice), "Hello", "-o", str(tmp_path / "o.wav")]) == 1
    err = capsys.readouterr().err
    assert "Piper's runtime" in err and "vocalkeep[runtime]" in err


def test_build_dry_run(home: Path, bank_dir: Path, capsys) -> None:
    out = home / "voices"
    args = ["build", str(bank_dir), "--base", "kristin", "-o", str(out), "--dry-run"]
    assert main([*args, "--work", str(home / "work"), "--progress", "json"]) == 0
    done = _json_lines(capsys.readouterr().out)[-1]
    assert done["event"] == "done" and done["dryRun"] is True
    assert done["maxEpochs"] == 3000
    assert done["usableRecordings"] == 4
    assert done["voice"] == str(out / "en_US-jane_doe-medium")
    assert "--data.csv_path" in done["command"]
    assert not out.exists() and not (home / "work").exists()


def test_build_end_to_end_with_fake_piper(
    home: Path, bank_dir: Path, tmp_path: Path, capsys, monkeypatch
) -> None:
    fake = posix_script(tmp_path / "fake-python", FAKE_PIPER)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "fake-args.json"))
    base_ckpt = tmp_path / "epoch=1000-step=1.ckpt"
    base_ckpt.write_bytes(b"base")
    monkeypatch.setattr(
        export_module, "run_export_command", lambda python, ckpt, output: tiny_onnx(output)
    )
    voices = home / "voices"
    work = home / "work"
    args = [
        "build",
        str(bank_dir),
        "--base",
        "ljspeech",
        "-o",
        str(voices),
        "--work",
        str(work),
        "--quick",
        "--checkpoint",
        str(base_ckpt),
        "--python",
        str(fake),
        "--progress",
        "json",
    ]
    assert main(args) == 0
    events = _json_lines(capsys.readouterr().out)
    stages = [e["stage"] for e in events if e["event"] == "stage"]
    assert stages == ["prepare", "download", "train", "export"]
    done = events[-1]
    assert done["event"] == "done"
    assert done["voice"] == str(voices / "en_US-jane_doe-medium")
    assert done["message"].startswith("Your voice is ready")
    assert (work / "dataset" / "metadata.csv").is_file()
    assert (work / "run" / "run.json").is_file()
    info = json.loads((voices / "en_US-jane_doe-medium" / "voice.json").read_text(encoding="utf-8"))
    assert info["bank"]["takes"] == 4
    assert info["base"]["id"] == "en_US-ljspeech-medium"
    fake_args = json.loads((tmp_path / "fake-args.json").read_text(encoding="utf-8"))
    assert fake_args[fake_args.index("--trainer.max_epochs") + 1] == "1150"

    # Building again reuses the work folder: a fresh dataset, a fresh run.
    assert main(args) == 0
    events = _json_lines(capsys.readouterr().out)
    assert events[-1]["event"] == "done"


def test_console_script_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "vocalkeep", "bases", "--json", "--commercial"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert all(b["commercial"] == "yes" for b in json.loads(proc.stdout))
