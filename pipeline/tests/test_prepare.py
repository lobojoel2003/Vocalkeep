# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import wave
import zipfile
from pathlib import Path

import numpy as np
import pytest

from conftest import TakeSpec, make_bank
from vocalkeep.audio import read_wav
from vocalkeep.bank import open_bank
from vocalkeep.cli import main
from vocalkeep.dataset import check_bank, clean_text, load_dataset_info, prepare
from vocalkeep.errors import VocalkeepError
from vocalkeep.quality import analyze, config


def _prepare(bank_dir: Path, out: Path, **kwargs) -> dict:
    with open_bank(bank_dir) as bank:
        return prepare(bank, out, **kwargs)


def test_prepare_writes_a_piper_dataset(bank_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    info = _prepare(bank_dir, out)

    wavs = sorted(p.name for p in (out / "wavs").iterdir())
    assert wavs == ["arctic_a0001.wav", "arctic_a0002.wav", "arctic_a0003.wav", "quiet_one.wav"]
    for name in wavs:
        with wave.open(str(out / "wavs" / name)) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (22050, 1, 2)

    lines = (out / "metadata.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "arctic_a0001.wav|Author of the danger trail, Philip Steels, etc."
    assert (
        lines[2] == "arctic_a0003.wav|For the twentieth time that evening the two men shook hands."
    )
    for line in lines:
        assert line.count("|") == 1
        file, text = line.split("|")
        assert file.endswith(".wav") and text == text.strip() and text

    stored = json.loads((out / "dataset.json").read_text())
    assert stored == info
    assert info["format"] == "vocalkeep-dataset"
    assert info["sampleRate"] == 22050
    assert info["espeakVoice"] == "en-us"
    assert info["language"] == "en-US"
    assert info["speaker"]["name"] == "Jane Doe"
    assert info["bank"]["id"].startswith("0b1c")
    assert info["counts"] == {"takes": 7, "included": 4, "excluded": 3, "good": 3, "okay": 1}
    reasons = {e["promptId"]: e["reason"] for e in info["excluded"]}
    assert reasons == {
        "clipped_one": "redo",
        "missing_one": "missing-file",
        "no_text": "empty-text",
    }
    assert info["minutes"] > 0
    assert load_dataset_info(out)["counts"]["included"] == 4


def test_prepared_audio_is_trimmed_and_level_matched(bank_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    _prepare(bank_dir, out)
    cfg = config()
    original = read_wav(bank_dir / "recordings/arctic-en/arctic_a0001.wav")
    a_orig = analyze(original)
    prepared = read_wav(out / "wavs" / "arctic_a0001.wav")
    assert prepared.sample_rate == 22050

    # Trimmed to the speech plus the padding on each side.
    expected_ms = (a_orig.speech_end_ms - a_orig.speech_start_ms) + 2 * cfg.training.trim_pad_ms
    assert abs(prepared.duration_ms - expected_ms) <= 25
    assert prepared.duration_ms < original.duration_ms

    # Speech brought to the target level, peaks at most -1 dBFS.
    a_new = analyze(prepared)
    assert a_new.speech_dbfs == pytest.approx(cfg.training.target_dbfs, abs=1.0)
    assert float(np.max(np.abs(prepared.samples))) <= 10 ** (-1 / 20) + 1e-3

    # A quiet take is lifted to the same level.
    quiet = analyze(read_wav(out / "wavs" / "quiet_one.wav"))
    assert quiet.speech_dbfs == pytest.approx(cfg.training.target_dbfs, abs=1.0)


def test_peak_limit_wins_over_loudness(tmp_path: Path) -> None:
    # Speech with a big peak: reaching -20 dBFS RMS would clip, so the peak decides.
    bank = make_bank(tmp_path / "b", [TakeSpec("p", params={"level": -38.0, "noise": -90.0})])
    wav = bank / "recordings/arctic-en/p.wav"
    clip = read_wav(wav)
    clip.samples[len(clip.samples) // 2] = 0.9
    from conftest import write_wav16

    write_wav16(wav, clip.samples, clip.sample_rate)
    out = tmp_path / "d"
    _prepare(bank, out)
    prepared = read_wav(out / "wavs" / "p.wav")
    assert float(np.max(np.abs(prepared.samples))) <= 10 ** (-1 / 20) + 1e-3


def test_min_verdict_good_leaves_out_okay_takes(bank_dir: Path, tmp_path: Path) -> None:
    info = _prepare(bank_dir, tmp_path / "d", min_verdict="good")
    assert info["counts"]["included"] == 3
    reasons = {e["promptId"]: e["reason"] for e in info["excluded"]}
    assert reasons["quiet_one"] == "below-min-verdict"


def test_other_sample_rate(bank_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "d"
    _prepare(bank_dir, out, sample_rate=16000)
    with wave.open(str(out / "wavs" / "arctic_a0001.wav")) as w:
        assert w.getframerate() == 16000


def test_refuses_a_folder_with_other_files(bank_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "busy"
    out.mkdir()
    (out / "my-notes.txt").write_text("keep me")
    with pytest.raises(VocalkeepError, match="already has other files"):
        _prepare(bank_dir, out)
    assert (out / "my-notes.txt").read_text() == "keep me"


def test_preparing_again_replaces_the_dataset(bank_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "d"
    _prepare(bank_dir, out)
    (out / "wavs" / "stale.wav").write_bytes(b"old")
    info = _prepare(bank_dir, out, min_verdict="good")
    assert not (out / "wavs" / "stale.wav").exists()
    assert len(list((out / "wavs").iterdir())) == info["counts"]["included"] == 3


def test_nothing_usable_is_a_kind_error(tmp_path: Path) -> None:
    bank = make_bank(tmp_path / "b", [TakeSpec("c", params={"level": 2.0})])
    with pytest.raises(VocalkeepError, match="None of the 1 recordings") as e:
        _prepare(bank, tmp_path / "d")
    assert "vocalkeep check" in (e.value.hint or "")


def test_empty_bank(tmp_path: Path) -> None:
    bank = make_bank(tmp_path / "b", [])
    with pytest.raises(VocalkeepError, match="no recordings yet"):
        _prepare(bank, tmp_path / "d")


def test_prepare_from_zip_via_cli(bank_dir: Path, tmp_path: Path, capsys) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for f in bank_dir.rglob("*"):
            if f.is_file():
                z.write(f, "Vocalkeep voice bank - Jane/" + f.relative_to(bank_dir).as_posix())
    out = tmp_path / "dataset"
    assert main(["prepare", str(archive), "-o", str(out), "--progress", "json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0] == {"event": "stage", "stage": "prepare", "message": events[0]["message"]}
    assert any(e["event"] == "progress" for e in events)
    assert events[-1]["event"] == "done"
    assert events[-1]["included"] == 4
    assert (out / "metadata.csv").is_file()


def test_clean_text() -> None:
    assert clean_text("  a | b\nc\t\td\r\n ") == "a b c d"
    assert clean_text("|||") == ""


def test_check_reports_takes_to_redo(bank_dir: Path) -> None:
    with open_bank(bank_dir) as bank:
        report = check_bank(bank)
    c = report["counts"]
    assert c["takes"] == 7
    assert c["redo"] == 1
    assert c["missing"] == 1
    assert c["good"] == 4  # the take without text still sounds good
    assert c["okay"] == 1
    assert c["noText"] == 1
    assert c["usable"] == 4
    redo_ids = {e["promptId"] for e in report["redo"]}
    assert redo_ids == {"clipped_one", "missing_one"}
    clipped = next(t for t in report["takes"] if t["promptId"] == "clipped_one")
    assert clipped["storedVerdict"] == "good" and clipped["changed"] is True
    assert {"code": "clipping", "severity": "redo"} in clipped["issues"]


def test_check_cli(bank_dir: Path, capsys) -> None:
    assert main(["check", str(bank_dir)]) == 0
    out = capsys.readouterr().out
    assert "Worth recording again" in out and "clipped_one" in out
    assert main(["check", str(bank_dir), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["redo"] == 1
