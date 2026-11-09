# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding espeak-ng's data folder.

Piper voices turn text into sounds with espeak-ng, so voice packages for Sherpa-ONNX carry a
copy of ``espeak-ng-data``. We look, in order, at the folder the person gave, the copy bundled
with the ``piper-tts`` package, ``ESPEAK_DATA_PATH``, and the usual system locations.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from vocalkeep.errors import VocalkeepError

SYSTEM_PATHS = (
    "/usr/share/espeak-ng-data",
    "/usr/lib/x86_64-linux-gnu/espeak-ng-data",
    "/usr/lib/aarch64-linux-gnu/espeak-ng-data",
    "/usr/lib/arm-linux-gnueabihf/espeak-ng-data",
    "/usr/lib64/espeak-ng-data",
    "/usr/lib/espeak-ng-data",
    "/usr/local/share/espeak-ng-data",
    "/usr/local/lib/espeak-ng-data",
    "/opt/homebrew/share/espeak-ng-data",
    "/opt/local/share/espeak-ng-data",
)


def is_espeak_data(path: Path) -> bool:
    """espeak-ng's data folder always holds ``phontab`` (Saywell checks for it too)."""
    return (path / "phontab").is_file()


def piper_espeak_data() -> Path | None:
    """The espeak-ng data bundled with the ``piper-tts`` package, if it is installed."""
    try:
        spec = importlib.util.find_spec("piper")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        candidate = Path(location) / "espeak-ng-data"
        if is_espeak_data(candidate):
            return candidate
    return None


def find_espeak_data(explicit: str | Path | None = None) -> Path | None:
    """The best espeak-ng data folder available, or ``None``.

    An ``explicit`` folder that isn't espeak-ng data is an error rather than silently ignored.
    """
    if explicit:
        path = Path(explicit).expanduser()
        if is_espeak_data(path):
            return path
        if is_espeak_data(path / "espeak-ng-data"):
            return path / "espeak-ng-data"
        raise VocalkeepError(
            f"{path} isn't an espeak-ng data folder (it has no 'phontab' file).",
            "Point --espeak-data at the folder named espeak-ng-data.",
        )
    bundled = piper_espeak_data()
    if bundled:
        return bundled
    env = os.environ.get("ESPEAK_DATA_PATH")
    if env:
        for candidate in (Path(env), Path(env) / "espeak-ng-data"):
            if is_espeak_data(candidate):
                return candidate
    for raw in SYSTEM_PATHS:
        candidate = Path(raw)
        if is_espeak_data(candidate):
            return candidate
    return None
