# SPDX-License-Identifier: GPL-3.0-or-later
"""Fine-tuning a Piper voice on a prepared dataset.

This builds and runs Piper's own training command (``python -m piper.train fit``, from
piper1-gpl) and turns its output into progress events. The command it runs is::

    python -m piper.train fit \\
      --data.voice_name NAME --data.csv_path DATASET/metadata.csv --data.audio_dir DATASET/wavs \\
      --model.sample_rate 22050 --data.espeak_voice en-us \\
      --data.cache_dir RUN/cache --data.config_path RUN/config.json \\
      --data.batch_size 16 --data.num_test_examples 5 \\
      --trainer.max_epochs N --trainer.accelerator auto --trainer.devices 1 \\
      --trainer.default_root_dir RUN/training --ckpt_path BASE.ckpt

``--ckpt_path`` resumes the base checkpoint's epoch counter, so ``--trainer.max_epochs`` is the
base checkpoint's epoch **plus** the epochs to train (lessac medium is at epoch 2164, so 1000
more epochs means ``--trainer.max_epochs 3164``). The base epoch is read from the checkpoint
when PyTorch is available, else from a file name like ``epoch=2164-step=…``, else from the
registry.

Checkpoints land in ``RUN/training/lightning_logs/version_N/checkpoints/`` (``last.ckpt`` is
rewritten every epoch). If training stops part-way (power cut, closed laptop), running the same
command again carries on from ``last.ckpt``.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any
from urllib.parse import unquote, urlparse

from vocalkeep import __version__
from vocalkeep.bases import BaseVoice, commercial_text, find_base, licence_notice, registry
from vocalkeep.dataset import load_dataset_info
from vocalkeep.doctor import python_path, training_ready, training_steps
from vocalkeep.download import download_file
from vocalkeep.errors import VocalkeepError
from vocalkeep.paths import checkpoints_dir
from vocalkeep.progress import NullReporter, Reporter

RUN_FORMAT = "vocalkeep-run"
RUN_VERSION = 1
DEFAULT_EXTRA_EPOCHS = 1000
QUICK_EXTRA_EPOCHS = 150
DEFAULT_BATCH_SIZE = 16
#: Fewer sentences than this rarely trains well (and very small sets can fail to split).
MIN_UTTERANCES = 20

_EPOCH_IN_NAME = re.compile(r"epoch=(\d+)")
_PROGRESS_EPOCH = re.compile(r"\bEpoch (\d+)\b")
_PROGRESS_PERCENT = re.compile(r"(\d{1,3})%\|")
_TQDM_BAR = re.compile(r"\d{1,3}%\|")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def epoch_from_filename(name: str) -> int | None:
    """``epoch=2164-step=1355540.ckpt`` (or its URL-encoded form) → 2164."""
    match = _EPOCH_IN_NAME.search(unquote(name))
    return int(match.group(1)) if match else None


def read_checkpoint_epoch(path: Path, python: str, timeout: float = 900) -> int | None:
    """The epoch stored in a checkpoint, read with PyTorch in ``python``. ``None`` if that isn't
    possible (no PyTorch, unreadable file)."""
    script = (
        "import sys, torch\n"
        "c = torch.load(sys.argv[1], map_location='cpu', weights_only=False)\n"
        "print('VOCALKEEP-EPOCH', int(c['epoch']))\n"
    )
    try:
        proc = subprocess.run(
            [python, "-c", script, str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("VOCALKEEP-EPOCH "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def dataset_fingerprint(dataset_dir: Path) -> str:
    """Changes whenever the dataset's sentences change."""
    digest = hashlib.sha256()
    csv = dataset_dir / "metadata.csv"
    if csv.is_file():
        digest.update(csv.read_bytes())
    return digest.hexdigest()[:16]


@dataclass
class TrainPlan:
    """Everything about a training run, decided before it starts."""

    dataset_dir: Path
    run_dir: Path
    base: BaseVoice
    checkpoint: Path
    checkpoint_url: str | None
    base_epoch: int
    epoch_source: str
    extra_epochs: int
    batch_size: int
    accelerator: str
    devices: str
    python: str
    voice_name: str
    espeak_voice: str
    sample_rate: int
    quick: bool
    dataset: dict[str, Any] = field(default_factory=dict)
    num_test_examples: int = 5
    resume_from: Path | None = None
    resume_max_epochs: int | None = None

    @property
    def max_epochs(self) -> int:
        if self.resume_max_epochs is not None:
            return self.resume_max_epochs
        return self.base_epoch + self.extra_epochs

    @property
    def needs_download(self) -> bool:
        return self.checkpoint_url is not None and not self.checkpoint.is_file()

    @property
    def config_path(self) -> Path:
        return self.run_dir / "config.json"

    @property
    def command(self) -> list[str]:
        start = self.resume_from or self.checkpoint
        return [
            self.python,
            "-m",
            "piper.train",
            "fit",
            "--data.voice_name",
            self.voice_name,
            "--data.csv_path",
            str(self.dataset_dir / "metadata.csv"),
            "--data.audio_dir",
            str(self.dataset_dir / "wavs"),
            "--model.sample_rate",
            str(self.sample_rate),
            "--data.espeak_voice",
            self.espeak_voice,
            "--data.cache_dir",
            str(self.run_dir / "cache"),
            "--data.config_path",
            str(self.config_path),
            "--data.batch_size",
            str(self.batch_size),
            "--data.num_test_examples",
            str(self.num_test_examples),
            "--trainer.max_epochs",
            str(self.max_epochs),
            "--trainer.accelerator",
            self.accelerator,
            "--trainer.devices",
            self.devices,
            "--trainer.default_root_dir",
            str(self.run_dir / "training"),
            "--ckpt_path",
            str(start),
        ]

    @property
    def command_text(self) -> str:
        """The command as one line, quoted for this system's shell."""
        if os.name == "nt":
            return subprocess.list2cmdline(self.command)
        return shlex.join(self.command)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": {
                "id": self.base.id,
                "name": self.base.name,
                "license": self.base.license,
                "commercial": self.base.commercial,
                "lineage": self.base.lineage,
                "lineageChain": list(self.base.lineage_chain),
                "dataset": self.base.dataset,
                "datasetUrl": self.base.dataset_url,
                "modelCard": self.base.model_card,
                "checkpoint": str(self.checkpoint),
                "checkpointUrl": self.checkpoint_url,
                "epoch": self.base_epoch,
                "epochSource": self.epoch_source,
            },
            "epochs": {
                "base": self.base_epoch,
                "extra": self.extra_epochs,
                "max": self.max_epochs,
                "quick": self.quick,
            },
            "batchSize": self.batch_size,
            "accelerator": self.accelerator,
            "devices": self.devices,
            "python": self.python,
            "voiceName": self.voice_name,
            "espeakVoice": self.espeak_voice,
            "sampleRate": self.sample_rate,
            "command": self.command,
            "dataset": self.dataset,
            "resumedFrom": str(self.resume_from) if self.resume_from else None,
        }


def _is_url(value: str) -> bool:
    return urlparse(value).scheme in ("http", "https", "file")


def _dataset_summary(dataset_dir: Path, info: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(dataset_dir),
        "fingerprint": dataset_fingerprint(dataset_dir),
        "bankId": info.get("bank", {}).get("id"),
        "speaker": info.get("speaker", {}),
        "language": info.get("language"),
        "espeakVoice": info.get("espeakVoice"),
        "sampleRate": info.get("sampleRate"),
        "utterances": info.get("counts", {}).get("included"),
        "minutes": info.get("minutes"),
    }


def plan_training(
    dataset_dir: str | Path,
    base_id: str,
    run_dir: str | Path,
    *,
    epochs: int | None = None,
    quick: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    accelerator: str = "auto",
    devices: str = "1",
    checkpoint: str | None = None,
    python: str | None = None,
    require_commercial: bool = False,
    dataset_info: dict[str, Any] | None = None,
) -> TrainPlan:
    """Decides how to train, without touching anything (safe for ``--dry-run``)."""
    dataset_path = Path(dataset_dir).expanduser().resolve()
    info = dataset_info if dataset_info is not None else load_dataset_info(dataset_path)
    base = find_base(base_id)
    if require_commercial and base.commercial != "yes":
        allowed = ", ".join(b.voice_name for b in registry() if b.commercial == "yes")
        raise VocalkeepError(
            f"The base voice {base.name} isn't cleared for commercial use. "
            f"{commercial_text(base.commercial)} {base.commercial_reason}",
            f"Choose a base voice whose licence allows it: {allowed}.",
        )
    if not base.can_fine_tune:
        raise VocalkeepError(
            f"{base.name} has {base.speakers} speakers; Vocalkeep can only fine-tune "
            "single-speaker voices.",
            "Choose another base voice; 'vocalkeep bases' lists them.",
        )
    if epochs is not None and epochs <= 0:
        raise VocalkeepError("--epochs must be a positive number of epochs to train.")
    if batch_size <= 0:
        raise VocalkeepError("--batch-size must be at least 1.")
    extra = (
        epochs if epochs is not None else (QUICK_EXTRA_EPOCHS if quick else DEFAULT_EXTRA_EPOCHS)
    )

    checkpoint_url: str | None
    if checkpoint:
        if _is_url(checkpoint):
            checkpoint_url = checkpoint
            name = unquote(Path(urlparse(checkpoint).path).name) or "checkpoint.ckpt"
            checkpoint_path = checkpoints_dir() / "custom" / name
        else:
            checkpoint_url = None
            checkpoint_path = Path(checkpoint).expanduser().resolve()
            if not checkpoint_path.is_file():
                raise VocalkeepError(f"The checkpoint {checkpoint_path} doesn't exist.")
    else:
        checkpoint_url = base.checkpoint_url
        checkpoint_path = checkpoints_dir() / base.id / base.checkpoint_filename

    from_name = epoch_from_filename(checkpoint_path.name)
    if from_name is not None:
        base_epoch, source = from_name, "filename"
    elif checkpoint_path.name == base.checkpoint_filename and base.checkpoint_epoch:
        base_epoch, source = base.checkpoint_epoch, "registry"
    else:
        base_epoch, source = 0, "unknown"

    speaker = info.get("speaker", {}) or {}
    voice_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(speaker.get("name") or "vocalkeep")).strip("_")
    utterances = int(info.get("counts", {}).get("included") or 0)
    return TrainPlan(
        dataset_dir=dataset_path,
        run_dir=Path(run_dir).expanduser().resolve(),
        base=base,
        checkpoint=checkpoint_path,
        checkpoint_url=checkpoint_url,
        base_epoch=base_epoch,
        epoch_source=source,
        extra_epochs=extra,
        batch_size=batch_size,
        accelerator=accelerator,
        devices=str(devices),
        python=python_path(python),
        voice_name=voice_name or "vocalkeep",
        espeak_voice=str(info.get("espeakVoice") or base.espeak_voice),
        sample_rate=int(info.get("sampleRate") or 22050),
        quick=quick,
        dataset=_dataset_summary(dataset_path, info),
        num_test_examples=max(1, min(5, utterances // 10)) if utterances else 5,
    )


def load_run(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "run.json"
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("format") == RUN_FORMAT else None


def write_run(run_dir: Path, data: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / "run.json.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(run_dir / "run.json")


def find_checkpoints(run_dir: Path) -> list[Path]:
    """Checkpoints written by training, best candidate first: ``last.ckpt`` of the newest
    ``version_N``, then the rest newest first."""
    roots = [run_dir / "training" / "lightning_logs", run_dir / "lightning_logs"]
    versions: list[tuple[int, Path]] = []
    for root in roots:
        if root.is_dir():
            for d in root.glob("version_*"):
                suffix = d.name.removeprefix("version_")
                if d.is_dir() and suffix.isdigit():
                    versions.append((int(suffix), d))
    ordered: list[Path] = []
    for _, version in sorted(versions, key=lambda t: t[0], reverse=True):
        ckpt_dir = version / "checkpoints"
        last = ckpt_dir / "last.ckpt"
        if last.is_file():
            ordered.append(last)
        others = sorted(
            (p for p in ckpt_dir.glob("*.ckpt") if p.name != "last.ckpt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        ordered.extend(others)
    if not ordered:
        ordered = sorted(run_dir.rglob("*.ckpt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ordered


def find_latest_checkpoint(run_dir: Path) -> Path | None:
    found = find_checkpoints(run_dir)
    return found[0] if found else None


def _fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    hours, minutes = divmod(minutes, 60)
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days} day{'s' if days != 1 else ''} {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


class TrainingMonitor:
    """Turns Piper/Lightning output into progress events."""

    def __init__(self, reporter: Reporter, start_epoch: int, max_epochs: int, log: IO[str]):
        self.reporter = reporter
        self.start_epoch = start_epoch
        self.max_epochs = max_epochs
        self.log = log
        self.tail: deque[str] = deque(maxlen=60)
        self.epoch: int | None = None
        self._first: tuple[int, float] | None = None
        self._eta = ""

    def feed(self, line: str) -> None:
        line = line.rstrip()
        if not line.strip():
            return
        self.log.write(line + "\n")
        self.tail.append(line)
        match = _PROGRESS_EPOCH.search(line)
        if match and (_TQDM_BAR.search(line) or line[match.end() : match.end() + 1] in (":", "/")):
            epoch = int(match.group(1))
            pct = _PROGRESS_PERCENT.search(line)
            within = int(pct.group(1)) / 100 if pct else 0.0
            self._on_epoch(epoch, within)
            return
        if _TQDM_BAR.search(line) or line.startswith(("Sanity Checking", "Validation")):
            return
        self.reporter.log(line)

    def _on_epoch(self, epoch: int, within: float) -> None:
        now = time.monotonic()
        if self._first is None:
            self._first = (epoch, now)
        elif epoch != self.epoch:
            first_epoch, first_time = self._first
            done = epoch - first_epoch
            if done > 0:
                per_epoch = (now - first_time) / done
                self._eta = _fmt_duration(per_epoch * max(self.max_epochs - epoch, 0))
        self.epoch = epoch
        span = max(self.max_epochs - self.start_epoch, 1)
        fraction = (epoch - self.start_epoch + within) / span
        message = f"Epoch {epoch} of {self.max_epochs}"
        if self._eta:
            message += f" (about {self._eta} left)"
        self.reporter.progress(
            "train",
            fraction,
            message,
            epoch=epoch,
            maxEpochs=self.max_epochs,
            startEpoch=self.start_epoch,
        )


def _stream_lines(stream: IO[bytes], on_line: Callable[[str], None]) -> None:
    """Calls ``on_line`` for every line, splitting on ``\\r`` too (progress bars use it)."""
    buffer = b""
    read = getattr(stream, "read1", stream.read)
    while True:
        chunk = read(65536)
        if not chunk:
            break
        buffer += chunk
        parts = re.split(rb"[\r\n]", buffer)
        buffer = parts.pop()
        for part in parts:
            if part.strip():
                on_line(part.decode("utf-8", "replace"))
    if buffer.strip():
        on_line(buffer.decode("utf-8", "replace"))


def _failure_hint(tail: list[str], run_dir: Path) -> str:
    text = "\n".join(tail)
    log = run_dir / "train.log"
    if "out of memory" in text.lower():
        return (
            "The graphics card ran out of memory. Run again with a smaller batch, for example "
            f"--batch-size 8. (Full log: {log})"
        )
    if "monotonic_align" in text:
        return "Piper's alignment helper isn't built. " + training_steps("python3")
    if "No module named 'piper" in text or "No module named piper" in text:
        return training_steps("python3")
    if "espeakbridge" in text:
        return (
            "Piper isn't fully built. In the piper1-gpl folder run: "
            "python3 setup.py build_ext --inplace"
        )
    return f"The full log is in {log}. The last lines were:\n" + "\n".join(tail[-8:])


def _prepare_run_dir(plan: TrainPlan, reporter: Reporter) -> dict[str, Any] | None:
    """Makes the run folder ready. Returns the earlier run to carry on from, if any."""
    run = plan.run_dir
    if run.exists() and not run.is_dir():
        raise VocalkeepError(f"{run} is a file. Choose a folder for the training run.")
    previous = load_run(run) if run.is_dir() else None
    if run.is_dir() and any(run.iterdir()) and previous is None:
        raise VocalkeepError(
            f"{run} already has other files in it.",
            "Choose a new or empty folder for the training run, so nothing of yours is replaced.",
        )
    if previous is not None:
        last = find_latest_checkpoint(run)
        same = (
            previous.get("base", {}).get("id") == plan.base.id
            and previous.get("dataset", {}).get("fingerprint") == plan.dataset.get("fingerprint")
            and previous.get("epochs", {}).get("extra") == plan.extra_epochs
        )
        if previous.get("status") in ("running", "stopped", "failed") and same and last:
            return previous
        # A finished or different run: start again from the base voice.
        reporter.log(f"Starting a new training run; the earlier one in {run} is replaced.")
        for name in ("training", "cache", "lightning_logs"):
            shutil.rmtree(run / name, ignore_errors=True)
        (run / "config.json").unlink(missing_ok=True)
    run.mkdir(parents=True, exist_ok=True)
    return None


def run_training(
    plan: TrainPlan,
    *,
    reporter: Reporter | None = None,
    dry_run: bool = False,
    check_environment: bool = True,
) -> dict[str, Any]:
    """Downloads the base checkpoint if needed, runs training and writes ``RUN/run.json``.

    Returns the contents of ``run.json``. With ``dry_run`` nothing is written or run.
    """
    reporter = reporter or NullReporter()
    for line in licence_notice(plan.base).splitlines():
        reporter.log(line)
    if dry_run:
        return {"format": RUN_FORMAT, "status": "dry-run", **plan.to_dict()}

    if plan.dataset.get("utterances") is not None and plan.dataset["utterances"] < MIN_UTTERANCES:
        reporter.warn(
            f"Only {plan.dataset['utterances']} sentences: training may fail or sound rough. "
            "Record more for a better voice."
        )
    if check_environment:
        ready, _info = training_ready(plan.python)
        if not ready:
            raise VocalkeepError(
                "This computer isn't set up to train voices yet.",
                training_steps(plan.python, _info) + "\nThen run 'vocalkeep doctor' to check.",
            )

    previous = _prepare_run_dir(plan, reporter)

    reporter.stage("download", "Getting the starting voice")
    if plan.needs_download:
        url = plan.checkpoint_url or ""
        reporter.log(f"Downloading {plan.base.name} from {url}")
        download_file(url, plan.checkpoint, reporter=reporter, what="the starting voice")
    else:
        reporter.progress("download", 1.0, "The starting voice is already downloaded")

    if previous is not None:
        last = find_latest_checkpoint(plan.run_dir)
        plan.resume_from = last
        plan.resume_max_epochs = int(previous.get("epochs", {}).get("max") or plan.max_epochs)
        plan.base_epoch = int(previous.get("epochs", {}).get("base") or plan.base_epoch)
        plan.epoch_source = str(previous.get("base", {}).get("epochSource") or plan.epoch_source)
        reporter.log(f"Carrying on from where training stopped ({last}).")
    elif plan.epoch_source != "checkpoint":
        stored = read_checkpoint_epoch(plan.checkpoint, plan.python)
        if stored is not None:
            plan.base_epoch, plan.epoch_source = stored, "checkpoint"
        elif plan.epoch_source == "unknown":
            reporter.warn(
                "Couldn't tell how far the starting checkpoint was trained; counting from 0. "
                "If training ends at once, pass a larger --epochs."
            )

    run: dict[str, Any] = {
        "format": RUN_FORMAT,
        "version": RUN_VERSION,
        "vocalkeepVersion": __version__,
        "createdAt": (previous or {}).get("createdAt") or _now(),
        "startedAt": _now(),
        "status": "running",
        **plan.to_dict(),
    }
    write_run(plan.run_dir, run)

    reporter.stage("train", f"Training (epochs {plan.base_epoch} to {plan.max_epochs})")
    reporter.log("Running: " + plan.command_text)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    start_epoch = plan.base_epoch
    if previous is not None and plan.resume_from is not None:
        start_epoch = epoch_from_filename(plan.resume_from.name) or plan.base_epoch
    with (plan.run_dir / "train.log").open("a", encoding="utf-8") as log:
        log.write(f"\n# {_now()} {plan.command_text}\n")
        monitor = TrainingMonitor(reporter, start_epoch, plan.max_epochs, log)
        try:
            proc = subprocess.Popen(
                plan.command,
                cwd=plan.run_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
        except OSError as e:
            run["status"] = "failed"
            write_run(plan.run_dir, run)
            raise VocalkeepError(f"Training couldn't start: {e}.") from e
        try:
            if proc.stdout is not None:
                _stream_lines(proc.stdout, monitor.feed)
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
            run["status"] = "stopped"
            run["stoppedAt"] = _now()
            write_run(plan.run_dir, run)
            raise VocalkeepError(
                "Training was stopped.",
                "Run the same command again to carry on from the last finished epoch.",
            ) from None

    if code != 0:
        run["status"] = "failed"
        run["exitCode"] = code
        run["failedAt"] = _now()
        write_run(plan.run_dir, run)
        raise VocalkeepError(
            f"Training stopped with an error (exit code {code}).",
            _failure_hint(list(monitor.tail), plan.run_dir),
        )
    checkpoint = find_latest_checkpoint(plan.run_dir)
    if checkpoint is None or not plan.config_path.is_file():
        run["status"] = "failed"
        write_run(plan.run_dir, run)
        raise VocalkeepError(
            "Training finished but left no checkpoint or config.json.",
            _failure_hint(list(monitor.tail), plan.run_dir),
        )
    run["status"] = "finished"
    run["finishedAt"] = _now()
    run["checkpoint"] = str(checkpoint)
    write_run(plan.run_dir, run)
    reporter.progress("train", 1.0, "Training finished")
    return run
