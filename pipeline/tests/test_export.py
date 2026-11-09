# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

import vocalkeep.export as export_module
from conftest import piper_config, tiny_onnx
from vocalkeep.cli import main
from vocalkeep.errors import VocalkeepError
from vocalkeep.export import export_voice
from vocalkeep.voice import SONATA_VOICE_PATTERN, missing_config_keys


def make_run(root: Path, *, base: str = "en_US-ljspeech-medium", commercial: str = "yes") -> Path:
    run = root / "run"
    trainer_python = root / "trainer-python"
    trainer_python.write_text("")
    ckpt_dir = run / "training" / "lightning_logs" / "version_0" / "checkpoints"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "last.ckpt").write_bytes(b"fake checkpoint")
    (ckpt_dir / "epoch=1163-val_mel=0.3.ckpt").write_bytes(b"older")
    (run / "config.json").write_text(json.dumps(piper_config()), encoding="utf-8")
    run_json = {
        "format": "vocalkeep-run",
        "version": 1,
        "status": "finished",
        "base": {
            "id": base,
            "license": "Public domain",
            "commercial": commercial,
            "lineage": "Trained from scratch",
            "checkpointUrl": "https://huggingface.co/datasets/rhasspy/piper-checkpoints/resolve/main/x.ckpt",
        },
        "epochs": {"base": 1000, "extra": 150, "max": 1150, "quick": True},
        "python": str(trainer_python),
        "dataset": {
            "bankId": "bank-123",
            "speaker": {"name": "Zoë O'Brien", "language": "en-GB", "gender": "female"},
            "language": "en-GB",
            "utterances": 412,
            "minutes": 38.5,
        },
    }
    (run / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    return run


@pytest.fixture
def fake_exporter(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Path, Path]]:
    calls: list[tuple[str, Path, Path]] = []

    def fake(python: str, checkpoint: Path, output: Path) -> None:
        calls.append((python, checkpoint, output))
        tiny_onnx(output)

    monkeypatch.setattr(export_module, "run_export_command", fake)
    return calls


def test_export_makes_a_voice_folder(tmp_path: Path, fake_exporter) -> None:
    run = make_run(tmp_path)
    voice = export_voice(run, tmp_path / "voices")
    vid = "en_GB-zoe_o_brien-medium"
    assert voice.id == vid
    assert voice.root == tmp_path / "voices" / vid
    assert sorted(p.name for p in voice.root.iterdir()) == sorted(
        [f"{vid}.onnx", f"{vid}.onnx.json", "MODEL_CARD", "voice.json"]
    )
    python, ckpt, _out = fake_exporter[0]
    assert ckpt.name == "last.ckpt"
    assert python == str(tmp_path / "trainer-python"), "the run's training Python is used"
    assert SONATA_VOICE_PATTERN.match(voice.onnx.name)

    config = json.loads((voice.root / f"{vid}.onnx.json").read_text())
    assert not missing_config_keys(config)
    assert config["audio"] == {"sample_rate": 22050, "quality": "medium"}
    assert config["espeak"]["voice"] == "en-us"
    assert config["language"]["code"] == "en_GB"
    assert config["phoneme_id_map"]["_"] == [0]

    info = json.loads((voice.root / "voice.json").read_text())
    assert info["format"] == "vocalkeep-voice" and info["version"] == 1
    assert info["id"] == vid and info["name"] == "Zoë O'Brien"
    assert info["language"] == "en-GB" and info["gender"] == "female"
    assert info["sampleRate"] == 22050
    assert info["base"] == {
        "id": "en_US-ljspeech-medium",
        "license": "Public domain",
        "commercial": "yes",
        "lineage": "Trained from scratch",
    }
    assert info["bank"] == {"id": "bank-123", "takes": 412, "minutes": 38.5}
    assert info["onnxSha256"] == hashlib.sha256(voice.onnx.read_bytes()).hexdigest()
    assert info["vocalkeepVersion"] and info["createdAt"]

    card = (voice.root / "MODEL_CARD").read_text()
    assert "This is Zoë O'Brien's own voice. It belongs to Zoë O'Brien" in card
    assert "Vocalkeep" in card and "Piper" in card
    assert "LJ Speech" in card and "Public domain" in card
    assert "412 sentences" in card and "38 minutes" in card
    assert "Commercial use: allowed" in card
    assert "https://" in card
    assert not (tmp_path / "voices" / f".{vid}.exporting").exists()


def test_export_of_a_lessac_voice_says_not_commercial(tmp_path: Path, fake_exporter) -> None:
    run = make_run(tmp_path, base="en_US-lessac-medium", commercial="no")
    voice = export_voice(run, tmp_path / "voices", name="Sam")
    assert voice.id == "en_GB-sam-medium"
    card = voice.model_card_text
    assert "non-commercial purposes only" in card
    assert "Research only" in card


def test_export_from_another_computer_uses_this_python(tmp_path: Path, fake_exporter) -> None:
    run = make_run(tmp_path)
    (tmp_path / "trainer-python").unlink()
    export_voice(run, tmp_path / "voices")
    assert fake_exporter[0][0] == sys.executable


def test_export_again_replaces_the_voice(tmp_path: Path, fake_exporter) -> None:
    run = make_run(tmp_path)
    first = export_voice(run, tmp_path / "voices")
    (first.root / "stale.txt").write_text("old")
    second = export_voice(run, tmp_path / "voices")
    assert not (second.root / "stale.txt").exists()


def test_export_chosen_checkpoint(tmp_path: Path, fake_exporter) -> None:
    run = make_run(tmp_path)
    chosen = next(run.rglob("epoch=*.ckpt"))
    export_voice(run, tmp_path / "voices", checkpoint=chosen)
    assert fake_exporter[0][1] == chosen


def test_export_errors(tmp_path: Path, fake_exporter) -> None:
    with pytest.raises(VocalkeepError, match="isn't a Vocalkeep training run"):
        export_voice(tmp_path, tmp_path / "voices")
    run = make_run(tmp_path)
    (run / "config.json").write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    with pytest.raises(VocalkeepError, match="missing settings"):
        export_voice(run, tmp_path / "voices")
    (run / "config.json").unlink()
    with pytest.raises(VocalkeepError, match=r"no config\.json"):
        export_voice(run, tmp_path / "voices")


def test_failed_exporter_is_reported(tmp_path: Path, monkeypatch, capsys) -> None:
    run = make_run(tmp_path)

    def broken(python: str, checkpoint: Path, output: Path) -> None:
        raise VocalkeepError("Making the voice file failed (exit code 1).", "boom")

    monkeypatch.setattr(export_module, "run_export_command", broken)
    assert main(["export", str(run), "-o", str(tmp_path / "voices")]) == 1
    assert "Making the voice file failed" in capsys.readouterr().err
    assert not list((tmp_path / "voices").iterdir()), "nothing half-made is left behind"


def test_export_cli_json(tmp_path: Path, fake_exporter, capsys) -> None:
    run = make_run(tmp_path)
    assert main(["export", str(run), "-o", str(tmp_path / "v"), "--progress", "json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]["event"] == "stage" and events[0]["stage"] == "export"
    assert events[-1]["event"] == "done"
    assert events[-1]["voice"] == str(tmp_path / "v" / "en_GB-zoe_o_brien-medium")
