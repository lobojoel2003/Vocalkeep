# SPDX-License-Identifier: GPL-3.0-or-later
"""``vocalkeep doctor``: what this computer can do, and what to install next.

The checks run in the Python that will do the work (normally this one; ``--python`` points at
another, for example a separate virtual environment for training). They never fail: anything
missing is reported with a plain-language next step.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from vocalkeep import __version__
from vocalkeep.errors import VocalkeepError

PIPER_GIT = "https://github.com/OHF-voice/piper1-gpl.git"
TRAIN_DEPENDENCIES = ("torch", "lightning", "librosa", "jsonargparse", "pysilero_vad")

# Runs in the target interpreter; standard library only, so it works anywhere.
_PROBE = r"""
import glob, importlib.util, json, os, platform, sys
out = {"python": platform.python_version(), "executable": sys.executable}
def has(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False
try:
    spec = importlib.util.find_spec("piper")
except Exception:
    spec = None
locations = list(spec.submodule_search_locations or []) if spec else []
piper_dir = locations[0] if locations else None
out["piperDir"] = piper_dir
try:
    from importlib import metadata
    out["piperVersion"] = metadata.version("piper-tts")
except Exception:
    out["piperVersion"] = None
out["onnxruntime"] = has("onnxruntime")
out["espeakbridge"] = bool(piper_dir and glob.glob(os.path.join(piper_dir, "espeakbridge*")))
data = os.path.join(piper_dir, "espeak-ng-data") if piper_dir else None
out["espeakData"] = data if data and os.path.isfile(os.path.join(data, "phontab")) else None
train_main = os.path.join(piper_dir or "", "train", "__main__.py")
out["trainCode"] = bool(piper_dir and os.path.isfile(train_main))
ma = os.path.join(piper_dir or "", "train", "vits", "monotonic_align", "monotonic_align")
built = glob.glob(os.path.join(ma, "core*.so")) + glob.glob(os.path.join(ma, "core*.pyd"))
out["monotonicAlign"] = bool(piper_dir and built)
root = os.path.dirname(os.path.dirname(piper_dir)) if piper_dir else None
script = os.path.join(root or "", "build_monotonic_align.sh")
out["piperSource"] = root if root and os.path.isfile(script) else None
out["deps"] = {name: has(name) for name in DEPS}
out["torch"] = False
out["torchVersion"] = None
out["cuda"] = False
out["gpuName"] = None
out["mps"] = False
if CHECK_TORCH and out["deps"].get("torch"):
    try:
        import torch
        out["torch"] = True
        out["torchVersion"] = str(torch.__version__)
        out["cuda"] = bool(torch.cuda.is_available())
        if out["cuda"]:
            out["gpuName"] = torch.cuda.get_device_name(0)
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        out["mps"] = bool(mps and mps.is_available())
    except Exception as e:
        out["torchError"] = str(e)[:300]
print("VOCALKEEP-PROBE " + json.dumps(out))
"""


def probe(
    python: str | None = None, *, check_torch: bool = True, timeout: float = 180
) -> dict[str, Any]:
    """Runs the checks in ``python`` (default: this interpreter)."""
    exe = python or sys.executable
    script = f"DEPS = {TRAIN_DEPENDENCIES!r}\nCHECK_TORCH = {check_torch!r}\n" + _PROBE
    try:
        proc = subprocess.run(
            [exe, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise VocalkeepError(f"There is no Python at {exe}.") from None
    except subprocess.TimeoutExpired:
        raise VocalkeepError(f"Checking {exe} took too long.") from None
    for line in proc.stdout.splitlines():
        if line.startswith("VOCALKEEP-PROBE "):
            result: dict[str, Any] = json.loads(line[len("VOCALKEEP-PROBE ") :])
            return result
    raise VocalkeepError(
        f"{exe} couldn't be checked.", (proc.stderr or proc.stdout).strip()[-500:] or None
    )


def training_steps(python: str, info: dict[str, Any] | None = None) -> str:
    """The commands that install Piper's training tools, as one block of text."""
    info = info or {}
    source = info.get("piperSource")
    q = f'"{python}"' if " " in python else python
    if source and info.get("trainCode") and all(info.get("deps", {}).values()):
        steps = [
            "Finish setting up Piper's training tools by building its alignment helper:",
            f"  cd {source}",
            "  ./build_monotonic_align.sh",
        ]
        if not info.get("espeakbridge"):
            steps.append(f"  {q} setup.py build_ext --inplace")
        return "\n".join(steps)
    lines = [
        "To train voices on this computer, install Piper's training tools "
        "(an NVIDIA graphics card makes this hours instead of days):",
    ]
    if sys.platform.startswith("linux"):
        lines.append("  sudo apt-get install build-essential cmake ninja-build   (Debian/Ubuntu)")
    lines += [
        f"  git clone {PIPER_GIT}",
        "  cd piper1-gpl",
        f"  {q} -m pip install -e '.[train]'",
        "  ./build_monotonic_align.sh",
    ]
    if info.get("trainCode") and not info.get("piperSource"):
        lines.append(
            "(The piper-tts package from PyPI can speak, but training needs the source "
            "repository because of a part that has to be built on your computer.)"
        )
    return "\n".join(lines)


def runtime_step(python: str) -> str:
    q = f'"{python}"' if " " in python else python
    return (
        "Install Piper's runtime so Vocalkeep can speak with voices and package them:\n"
        f'  {q} -m pip install "piper-tts>=1.3"'
    )


def report(python: str | None = None, *, check_torch: bool = True) -> dict[str, Any]:
    """Everything ``vocalkeep doctor --json`` prints (camelCase keys)."""
    from vocalkeep.espeak import find_espeak_data
    from vocalkeep.install.linux import find_player

    exe = python or sys.executable
    try:
        info = probe(exe, check_torch=check_torch)
        probe_error = None
    except VocalkeepError as e:
        info = {}
        probe_error = str(e)
    deps: dict[str, bool] = info.get("deps", {})
    piper_runtime = bool(info.get("piperDir")) and bool(info.get("onnxruntime"))
    can_speak = piper_runtime and bool(info.get("espeakbridge"))
    piper_train = bool(info.get("trainCode")) and all(
        deps.get(d, False) for d in TRAIN_DEPENDENCIES
    )
    can_train = piper_train and bool(info.get("monotonicAlign")) and can_speak
    espeak = info.get("espeakData") or (str(p) if (p := find_espeak_data()) else None)
    players: list[str] = []
    if sys.platform.startswith("linux"):
        player = find_player()
        players = [player.name] if player else []

    steps: list[str] = []
    if probe_error:
        steps.append(probe_error)
    if not can_speak:
        if piper_runtime and not info.get("espeakbridge"):
            source = info.get("piperSource") or "the piper1-gpl folder"
            steps.append(
                "Piper is installed from its source folder but not built yet. Run:\n"
                f"  cd {source}\n  python3 setup.py build_ext --inplace"
            )
        else:
            steps.append(runtime_step(exe))
    if not can_train:
        steps.append(training_steps(exe, info))
    elif not info.get("cuda"):
        if info.get("mps"):
            steps.append(
                "Training will use the processor. Apple graphics (MPS) may work but hasn't been "
                "tested with Piper; expect training to take a long time."
            )
        else:
            steps.append(
                "No NVIDIA graphics card was found, so training would run on the processor and "
                "take days. A computer with an NVIDIA card (or a rented cloud GPU) takes hours."
            )
    if sys.platform.startswith("linux") and not players:
        steps.append(
            "To hear voices through the speakers, install an audio player: "
            "pulseaudio-utils (paplay) or alsa-utils (aplay)."
        )

    return {
        "version": __version__,
        "vocalkeepVersion": __version__,
        "python": info.get("python") or platform.python_version(),
        "pythonExecutable": info.get("executable") or exe,
        "platform": platform.platform(),
        "piperRuntime": piper_runtime,
        "piperVersion": info.get("piperVersion"),
        "piperTrain": piper_train,
        "monotonicAlign": bool(info.get("monotonicAlign")),
        "piperSource": info.get("piperSource"),
        "trainDependencies": deps,
        "torch": bool(info.get("torch")),
        "torchVersion": info.get("torchVersion"),
        "cuda": bool(info.get("cuda")),
        "gpuName": info.get("gpuName"),
        "espeakData": espeak,
        "canSpeak": can_speak,
        "canTrain": can_train,
        "audioPlayers": players,
        "speechDispatcher": bool(shutil.which("spd-say")),
        "nextStep": steps[0] if steps else None,
        "nextSteps": steps,
    }


def format_report(r: dict[str, Any]) -> str:
    def yes(v: object) -> str:
        return "yes" if v else "no"

    lines = [
        f"Vocalkeep {r['version']}",
        f"Python {r['python']} ({r['pythonExecutable']})",
        f"Platform: {r['platform']}",
        "",
        f"Can speak with voices (Piper runtime): {yes(r['canSpeak'])}"
        + (f"  [piper-tts {r['piperVersion']}]" if r.get("piperVersion") else ""),
        f"espeak-ng data: {r['espeakData'] or 'not found'}",
        f"Can train voices (Piper training tools): {yes(r['canTrain'])}",
        f"  training code and its libraries: {yes(r['piperTrain'])}",
        f"  alignment helper built (monotonic_align): {yes(r['monotonicAlign'])}",
        f"  PyTorch: {yes(r['torch'])}"
        + (f" {r['torchVersion']}" if r.get("torchVersion") else ""),
        f"  NVIDIA graphics card (CUDA): {yes(r['cuda'])}"
        + (f" - {r['gpuName']}" if r.get("gpuName") else ""),
    ]
    if r.get("audioPlayers") is not None and sys.platform.startswith("linux"):
        lines.append(f"Audio player: {', '.join(r['audioPlayers']) or 'none found'}")
        lines.append(f"Speech Dispatcher (spd-say): {yes(r['speechDispatcher'])}")
    lines.append("")
    if r["nextSteps"]:
        lines.append("What to do next:")
        for i, step in enumerate(r["nextSteps"], start=1):
            first, *rest = step.split("\n")
            lines.append(f"{i}. {first}")
            lines += [f"   {x}" for x in rest]
    else:
        lines.append("Everything is ready.")
    return "\n".join(lines)


def training_ready(python: str | None = None) -> tuple[bool, dict[str, Any]]:
    """Whether ``python`` can train, without loading PyTorch (fast)."""
    info = probe(python, check_torch=False)
    deps = info.get("deps", {})
    ready = (
        bool(info.get("trainCode"))
        and all(deps.get(d, False) for d in TRAIN_DEPENDENCIES)
        and bool(info.get("monotonicAlign"))
    )
    return ready, info


def python_path(value: str | None) -> str:
    """Validates a ``--python`` argument."""
    if not value:
        return sys.executable
    found = shutil.which(value) or (value if Path(value).exists() else None)
    if not found:
        raise VocalkeepError(f"There is no Python at {value}.")
    return found
