# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Vocalkeep keeps things on each platform.

Everything respects the usual environment variables (``HOME``, ``XDG_*``, ``LOCALAPPDATA``), so
tests and unusual setups can point it elsewhere. ``VOCALKEEP_CACHE_DIR`` overrides the cache.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def home() -> Path:
    """The person's home folder (``HOME`` first, so a temporary home works in tests)."""
    env = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return Path(env) if env else Path.home()


def _xdg(name: str, default: str) -> Path:
    value = os.environ.get(name)
    if value and Path(value).is_absolute():
        return Path(value)
    return home() / default


def xdg_data_home() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def xdg_config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def xdg_cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def local_app_data() -> Path | None:
    """``%LOCALAPPDATA%`` on Windows (or wherever the variable points)."""
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else None


def cache_dir() -> Path:
    """Vocalkeep's cache: downloaded base checkpoints live here."""
    override = os.environ.get("VOCALKEEP_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = local_app_data() or home() / "AppData" / "Local"
        return base / "vocalkeep" / "Cache"
    if sys.platform == "darwin":
        return home() / "Library" / "Caches" / "vocalkeep"
    return xdg_cache_home() / "vocalkeep"


def checkpoints_dir() -> Path:
    return cache_dir() / "checkpoints"
