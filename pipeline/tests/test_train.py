# SPDX-License-Identifier: GPL-3.0-or-later
"""Training: command construction, epoch maths, dry runs, downloads and a run with a fake Piper."""

from __future__ import annotations

import http.server
import io
import json
import shlex
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from conftest import posix_script
from vocalkeep.bank import open_bank
from vocalkeep.cli import main
from vocalkeep.dataset import prepare
from vocalkeep.download import NotFoundError, download_file, moved_checkpoint_url
from vocalkeep.errors import VocalkeepError
from vocalkeep.progress import NullReporter, Reporter
from vocalkeep.train import (
    DEFAULT_EXTRA_EPOCHS,
    QUICK_EXTRA_EPOCHS,
    TrainingMonitor,
    _follow_moved_checkpoint,
    _stream_lines,
    epoch_from_filename,
    find_latest_checkpoint,
    load_run,
    plan_training,
    run_training,
)

FAKE_PIPER = r"""
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ["-c"]:
    # Probes (doctor, checkpoint epoch): pretend to be a ready training environment.
    code = args[1]
    if "VOCALKEEP-EPOCH" in code:
        if os.environ.get("FAKE_EPOCH"):
            print("VOCALKEEP-EPOCH", os.environ["FAKE_EPOCH"])
        sys.exit(0)
    if "VOCALKEEP-PROBE" in code:
        print("VOCALKEEP-PROBE " + json.dumps({
            "python": "3.11.0", "executable": sys.argv[0], "piperDir": "/fake/piper",
            "onnxruntime": True, "espeakbridge": True, "espeakData": None, "trainCode": True,
            "monotonicAlign": True, "piperSource": None,
            "deps": {"torch": True, "lightning": True, "librosa": True,
                     "jsonargparse": True, "pysilero_vad": True}}))
        sys.exit(0)
    sys.exit(1)
assert args[:3] == ["-m", "piper.train", "fit"], args
opts = {}
i = 3
while i < len(args):
    opts[args[i]] = args[i + 1]
    i += 2
Path(os.environ["FAKE_LOG"]).write_text(json.dumps(args))
if os.environ.get("FAKE_FAIL"):
    print("Traceback (most recent call last):")
    print("torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB")
    sys.exit(3)
Path(opts["--data.config_path"]).write_text(json.dumps({
    "audio": {"sample_rate": 22050}, "espeak": {"voice": opts["--data.espeak_voice"]},
    "phoneme_type": "espeak", "num_symbols": 256, "num_speakers": 1,
    "phoneme_id_map": {"_": [0], "^": [1], "$": [2], " ": [3]}}))
ckpt_dir = Path(opts["--trainer.default_root_dir"]) / "lightning_logs" / "version_0" / "checkpoints"
ckpt_dir.mkdir(parents=True, exist_ok=True)
max_epochs = int(opts["--trainer.max_epochs"])
start = max_epochs - 3
print("GPU available: True (cuda), used: True")
for epoch in range(start, max_epochs):
    for pct in (0, 50, 100):
        bar = f"\rEpoch {epoch}:  {pct}%|#####     | 5/10 [00:01<00:01, 4.0it/s, v_num=0]"
        sys.stdout.write(bar)
        sys.stdout.flush()
    sys.stdout.write("\n")
    (ckpt_dir / "last.ckpt").write_bytes(b"ckpt")
(ckpt_dir / f"epoch={max_epochs - 1}-val_mel=0.3000.ckpt").write_bytes(b"ckpt")
print("`Trainer.fit` stopped: `max_epochs=%d` reached." % max_epochs)
"""


@pytest.fixture
def fake_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = posix_script(tmp_path / "bin" / "fake-python", FAKE_PIPER)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "fake-args.json"))
    return script


@pytest.fixture
def dataset_dir(bank_dir: Path, tmp_path: Path) -> Path:
    out = tmp_path / "dataset"
    with open_bank(bank_dir) as bank:
        prepare(bank, out)
    return out


def _opt(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


def test_epoch_from_filename() -> None:
    assert epoch_from_filename("epoch=2164-step=1355540.ckpt") == 2164
    assert epoch_from_filename("epoch%3D6679-step%3D1554200.ckpt") == 6679
    assert epoch_from_filename("lj-med_1000.ckpt") is None


def test_plan_for_lessac_adds_epochs_to_the_checkpoints(home: Path, dataset_dir: Path) -> None:
    plan = plan_training(dataset_dir, "lessac", home / "run")
    assert plan.base_epoch == 2164
    assert plan.epoch_source == "filename"
    assert plan.extra_epochs == DEFAULT_EXTRA_EPOCHS
    assert plan.max_epochs == 3164
    cmd = plan.command
    assert cmd[:4] == [sys.executable, "-m", "piper.train", "fit"]
    assert _opt(cmd, "--trainer.max_epochs") == "3164"
    assert _opt(cmd, "--data.csv_path") == str(dataset_dir / "metadata.csv")
    assert _opt(cmd, "--data.audio_dir") == str(dataset_dir / "wavs")
    assert _opt(cmd, "--model.sample_rate") == "22050"
    assert _opt(cmd, "--data.espeak_voice") == "en-us"
    assert _opt(cmd, "--data.config_path") == str(home / "run" / "config.json")
    assert _opt(cmd, "--data.cache_dir") == str(home / "run" / "cache")
    assert _opt(cmd, "--data.batch_size") == "16"
    assert _opt(cmd, "--trainer.accelerator") == "auto"
    assert _opt(cmd, "--trainer.devices") == "1"
    assert _opt(cmd, "--data.voice_name") == "Jane_Doe"
    ckpt = Path(_opt(cmd, "--ckpt_path"))
    assert ckpt == home / ".cache" / "vocalkeep" / "checkpoints" / plan.base.id / ckpt.name
    assert ckpt.name == "epoch=2164-step=1355540.ckpt"
    assert plan.needs_download
    assert plan.checkpoint_url and plan.checkpoint_url.endswith("epoch%3D2164-step%3D1355540.ckpt")


def test_plan_quick_and_custom_epochs(home: Path, dataset_dir: Path) -> None:
    quick = plan_training(dataset_dir, "ljspeech", home / "run", quick=True)
    assert quick.extra_epochs == QUICK_EXTRA_EPOCHS
    assert quick.base_epoch == 1000 and quick.epoch_source == "registry"
    assert quick.max_epochs == 1150
    custom = plan_training(
        dataset_dir, "kristin", home / "run", epochs=500, batch_size=8, accelerator="cpu"
    )
    assert custom.max_epochs == 2500
    assert _opt(custom.command, "--data.batch_size") == "8"
    assert _opt(custom.command, "--trainer.accelerator") == "cpu"


def test_plan_with_local_checkpoint(home: Path, dataset_dir: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "epoch=777-step=1.ckpt"
    ckpt.write_bytes(b"x")
    plan = plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=str(ckpt))
    assert plan.base_epoch == 777 and not plan.needs_download
    assert plan.max_epochs == 1777
    odd = tmp_path / "mine.ckpt"
    odd.write_bytes(b"x")
    plan = plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=str(odd))
    assert plan.epoch_source == "unknown" and plan.base_epoch == 0
    with pytest.raises(VocalkeepError, match="doesn't exist"):
        plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=str(tmp_path / "nope"))


def test_require_commercial_refuses_lessac_family(home: Path, dataset_dir: Path) -> None:
    for base in ("lessac", "ryan", "amy", "bryce"):
        with pytest.raises(VocalkeepError, match="isn't cleared for commercial use") as e:
            plan_training(dataset_dir, base, home / "run", require_commercial=True)
        assert "ljspeech" in (e.value.hint or "")
    assert plan_training(dataset_dir, "cori", home / "run", require_commercial=True)


def test_multi_speaker_bases_are_refused(home: Path, dataset_dir: Path) -> None:
    with pytest.raises(VocalkeepError, match="single-speaker"):
        plan_training(dataset_dir, "vctk", home / "run")


def test_not_a_dataset(home: Path, tmp_path: Path) -> None:
    with pytest.raises(VocalkeepError, match="isn't a prepared dataset"):
        plan_training(tmp_path, "ljspeech", home / "run")


def test_dry_run_cli_needs_no_torch(
    home: Path, dataset_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = home / "run"
    assert main(["train", str(dataset_dir), "--base", "lessac", "-o", str(run), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "--trainer.max_epochs 3164" in out
    assert "Commercial use: not allowed" in out
    last = out.strip().splitlines()[-1]
    assert " -m piper.train fit " in last
    if sys.platform != "win32":
        assert shlex.split(last)[1:4] == ["-m", "piper.train", "fit"]
    assert not run.exists(), "a dry run writes nothing"


def test_dry_run_json(home: Path, dataset_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["train", str(dataset_dir), "--base", "ljspeech", "-o", str(home / "r")]
    assert main([*args, "--dry-run", "--quick", "--progress", "json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    done = events[-1]
    assert done["event"] == "done" and done["dryRun"] is True
    assert done["maxEpochs"] == 1150
    assert done["command"][2:4] == ["piper.train", "fit"]
    assert done["download"].startswith("https://huggingface.co/")


def test_require_commercial_cli_exits_1(
    home: Path, dataset_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["train", str(dataset_dir), "--base", "lessac", "-o", str(home / "r"), "--dry-run"]
    assert main([*args, "--require-commercial"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: The base voice")
    assert "Traceback" not in err


def test_monitor_parses_lightning_progress() -> None:
    out = io.StringIO()
    log = io.StringIO()
    reporter = Reporter("json", out, min_interval=0)
    monitor = TrainingMonitor(reporter, start_epoch=2164, max_epochs=3164, log=log)
    _stream_lines(
        io.BytesIO(
            b"GPU available: True (cuda)\n"
            b"Epoch 2164:   0%|          | 0/10 [00:00<?, ?it/s]\r"
            b"Epoch 2164:  50%|#####     | 5/10 [00:01<00:01]\r"
            b"Validation DataLoader 0: 100%|##########| 2/2\r"
            b"Epoch 2300: 100%|##########| 10/10 [00:02<00:00]\n"
            b"Epoch 2300, global step 5: 'val_mel' reached 0.31\n"
        ),
        monitor.feed,
    )
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    progress = [e for e in events if e["event"] == "progress"]
    logs = [e["message"] for e in events if e["event"] == "log"]
    assert progress[0]["message"] == "Epoch 2164 of 3164"
    assert progress[1]["fraction"] == pytest.approx(0.0005)
    assert progress[-1]["epoch"] == 2300
    assert progress[-1]["fraction"] == pytest.approx(0.137)
    assert progress[-1]["message"].startswith("Epoch 2300 of 3164")
    assert logs == [
        "GPU available: True (cuda)",
        "Epoch 2300, global step 5: 'val_mel' reached 0.31",
    ]
    assert "Validation" in log.getvalue()


def test_run_training_with_a_fake_piper(
    home: Path, dataset_dir: Path, fake_python: Path, tmp_path: Path
) -> None:
    ckpt = tmp_path / "epoch=2164-step=1.ckpt"
    ckpt.write_bytes(b"base")
    run_dir = home / "run"
    plan = plan_training(
        dataset_dir, "ljspeech", run_dir, epochs=5, checkpoint=str(ckpt), python=str(fake_python)
    )
    out = io.StringIO()
    run = run_training(plan, reporter=Reporter("json", out, min_interval=0))
    assert run["status"] == "finished"
    assert run["epochs"] == {"base": 2164, "extra": 5, "max": 2169, "quick": False}
    assert Path(run["checkpoint"]).name == "last.ckpt"
    stored = load_run(run_dir)
    assert stored is not None and stored["status"] == "finished"
    assert stored["base"]["id"] == "en_US-ljspeech-medium"
    assert stored["base"]["commercial"] == "yes"
    assert stored["dataset"]["utterances"] == 4
    assert stored["command"][2:4] == ["piper.train", "fit"]
    assert (run_dir / "config.json").is_file()
    assert "Epoch 2168" in (run_dir / "train.log").read_text(encoding="utf-8")
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    stages = [e["stage"] for e in events if e["event"] == "stage"]
    assert stages == ["download", "train"]
    progress = [e for e in events if e["event"] == "progress" and e["stage"] == "train"]
    assert progress[-1]["fraction"] == 1.0
    assert any(e["message"].startswith("Epoch 2168 of 2169") for e in progress)
    args = json.loads(Path(tmp_path / "fake-args.json").read_text(encoding="utf-8"))
    assert args[args.index("--ckpt_path") + 1] == str(ckpt)


def test_epoch_read_from_checkpoint_wins(
    home: Path, dataset_dir: Path, fake_python: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_EPOCH", "999")
    ckpt = tmp_path / "base.ckpt"
    ckpt.write_bytes(b"base")
    plan = plan_training(
        dataset_dir,
        "ljspeech",
        home / "run",
        epochs=5,
        checkpoint=str(ckpt),
        python=str(fake_python),
    )
    assert plan.epoch_source == "unknown"
    run = run_training(plan)
    assert run["epochs"]["max"] == 1004
    assert run["base"]["epochSource"] == "checkpoint"


def test_failed_training_explains_itself(
    home: Path, dataset_dir: Path, fake_python: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("FAKE_FAIL", "1")
    ckpt = tmp_path / "epoch=10-step=1.ckpt"
    ckpt.write_bytes(b"base")
    plan = plan_training(
        dataset_dir, "ljspeech", home / "run", checkpoint=str(ckpt), python=str(fake_python)
    )
    with pytest.raises(VocalkeepError, match="exit code 3") as e:
        run_training(plan)
    assert "--batch-size 8" in (e.value.hint or "")
    assert load_run(home / "run")["status"] == "failed"


def test_interrupted_run_carries_on_from_last_checkpoint(
    home: Path, dataset_dir: Path, fake_python: Path, tmp_path: Path
) -> None:
    ckpt = tmp_path / "epoch=100-step=1.ckpt"
    ckpt.write_bytes(b"base")
    run_dir = home / "run"
    kwargs = {"epochs": 50, "checkpoint": str(ckpt), "python": str(fake_python)}
    run_training(plan_training(dataset_dir, "ljspeech", run_dir, **kwargs))
    stored = load_run(run_dir)
    stored["status"] = "stopped"
    (run_dir / "run.json").write_text(json.dumps(stored), encoding="utf-8")
    plan = plan_training(dataset_dir, "ljspeech", run_dir, **kwargs)
    run = run_training(plan)
    assert run["resumedFrom"] == str(
        run_dir / "training/lightning_logs/version_0/checkpoints/last.ckpt"
    )
    args = json.loads(Path(tmp_path / "fake-args.json").read_text(encoding="utf-8"))
    assert args[args.index("--ckpt_path") + 1].endswith("last.ckpt")
    assert args[args.index("--trainer.max_epochs") + 1] == "150"
    # A finished run with the same settings starts again from the base voice.
    run_training(plan_training(dataset_dir, "ljspeech", run_dir, **kwargs))
    args = json.loads(Path(tmp_path / "fake-args.json").read_text(encoding="utf-8"))
    assert args[args.index("--ckpt_path") + 1] == str(ckpt)


def test_run_dir_with_other_files_is_refused(
    home: Path, dataset_dir: Path, fake_python: Path, tmp_path: Path
) -> None:
    run_dir = home / "run"
    run_dir.mkdir()
    (run_dir / "thesis.docx").write_text("precious", encoding="utf-8")
    ckpt = tmp_path / "epoch=1-step=1.ckpt"
    ckpt.write_bytes(b"x")
    plan = plan_training(
        dataset_dir, "ljspeech", run_dir, checkpoint=str(ckpt), python=str(fake_python)
    )
    with pytest.raises(VocalkeepError, match="already has other files"):
        run_training(plan)


def test_training_environment_is_checked(home: Path, dataset_dir: Path, tmp_path: Path) -> None:
    ckpt = tmp_path / "epoch=1-step=1.ckpt"
    ckpt.write_bytes(b"x")
    plan = plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=str(ckpt))
    with pytest.raises(VocalkeepError, match="isn't set up to train") as e:
        run_training(plan)  # this test environment has no piper.train
    assert "piper1-gpl" in (e.value.hint or "")
    assert not (home / "run").exists()


def test_find_latest_checkpoint_prefers_newest_version(tmp_path: Path) -> None:
    for version in (0, 1, 10):
        d = tmp_path / "training" / "lightning_logs" / f"version_{version}" / "checkpoints"
        d.mkdir(parents=True)
        (d / "epoch=5-val_mel=0.3.ckpt").write_bytes(b"x")
    assert find_latest_checkpoint(tmp_path).parent.parent.name == "version_10"
    (tmp_path / "training/lightning_logs/version_10/checkpoints/last.ckpt").write_bytes(b"x")
    assert find_latest_checkpoint(tmp_path).name == "last.ckpt"
    assert find_latest_checkpoint(tmp_path / "nothing") is None


# --- downloads -------------------------------------------------------------------------------

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB
HF = "/datasets/rhasspy/piper-checkpoints/resolve/main"
OLD_AMY = f"{HF}/en/en_US/amy/medium/epoch%3D6679-step%3D1554200.ckpt"
GONE = {OLD_AMY, f"{HF}/en/en_US/gone/medium/x.ckpt"}


class _RangeHandler(http.server.BaseHTTPRequestHandler):
    calls: ClassVar[list[str | None]] = []

    def log_message(self, *args: object) -> None:
        return

    def do_GET(self) -> None:
        _RangeHandler.calls.append(self.headers.get("Range"))
        if self.path.startswith("/api/"):
            # Hugging Face's folder listing: Piper renamed amy's checkpoint; "gone" is empty.
            listing = (
                [
                    {"type": "file", "path": "en/en_US/amy/medium/config.json"},
                    {"type": "file", "path": "en/en_US/amy/medium/epoch=999-step=1.ckpt"},
                    {"type": "file", "path": "en/en_US/amy/medium/epoch=1999-step=164000.ckpt"},
                ]
                if self.path.endswith("/amy/medium")
                else []
            )
            body = json.dumps(listing).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/missing.ckpt" or self.path in GONE:
            self.send_error(404)
            return
        if self.path == "/page.ckpt":
            body = b"<html>sign in</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            body = PAYLOAD[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        else:
            body = PAYLOAD
            self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[str]:
    _RangeHandler.calls = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RangeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


def test_download_and_resume(server: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    dest = tmp_path / "c" / "base.ckpt"
    out = io.StringIO()
    download_file(f"{server}/base.ckpt", dest, reporter=Reporter("json", out, min_interval=0))
    assert dest.read_bytes() == PAYLOAD
    events = [json.loads(line) for line in out.getvalue().splitlines()]
    assert events[-1]["fraction"] == 1.0 and events[-1]["totalBytes"] == len(PAYLOAD)

    dest.unlink()
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(PAYLOAD[:1000])
    download_file(f"{server}/base.ckpt", dest)
    assert dest.read_bytes() == PAYLOAD
    assert _RangeHandler.calls[-1] == "bytes=1000-"
    assert not part.exists()


def test_download_errors(server: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with pytest.raises(VocalkeepError, match="404") as e:
        download_file(f"{server}/missing.ckpt", tmp_path / "m.ckpt")
    assert "--checkpoint" in (e.value.hint or "")
    with pytest.raises(VocalkeepError, match="web page"):
        download_file(f"{server}/page.ckpt", tmp_path / "p.ckpt")
    with pytest.raises(VocalkeepError, match="Couldn't connect"):
        download_file("http://127.0.0.1:9/x.ckpt", tmp_path / "x.ckpt", timeout=2)


def test_a_renamed_checkpoint_is_found(server: str, monkeypatch) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    # The most trained of the checkpoints now in the folder.
    assert moved_checkpoint_url(server + OLD_AMY) == (
        f"{server}{HF}/en/en_US/amy/medium/epoch%3D1999-step%3D164000.ckpt"
    )
    assert moved_checkpoint_url(f"{server}{HF}/en/en_US/gone/medium/x.ckpt") is None
    assert moved_checkpoint_url(f"{server}/missing.ckpt") is None, "not a repository address"


def test_training_follows_a_renamed_checkpoint(
    server: str, home: Path, dataset_dir: Path, monkeypatch
) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    old = server + OLD_AMY
    plan = plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=old)
    assert plan.base_epoch == 6679 and plan.needs_download
    with pytest.raises(NotFoundError):
        download_file(old, plan.checkpoint)
    _follow_moved_checkpoint(plan, old, NullReporter())
    assert plan.checkpoint.name == "epoch=1999-step=164000.ckpt"
    assert plan.checkpoint.read_bytes() == PAYLOAD
    assert plan.checkpoint_url and plan.checkpoint_url.endswith("epoch%3D1999-step%3D164000.ckpt")
    assert (plan.base_epoch, plan.epoch_source) == (1999, "filename")
    assert "--ckpt_path" in plan.command and str(plan.checkpoint) in plan.command


def test_a_vanished_checkpoint_is_explained(
    server: str, home: Path, dataset_dir: Path, monkeypatch
) -> None:
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    gone = f"{server}{HF}/en/en_US/gone/medium/x.ckpt"
    plan = plan_training(dataset_dir, "ljspeech", home / "run", checkpoint=gone)
    with pytest.raises(NotFoundError, match="isn't in Piper's repository") as e:
        _follow_moved_checkpoint(plan, gone, NullReporter())
    assert "--checkpoint" in (e.value.hint or "")
