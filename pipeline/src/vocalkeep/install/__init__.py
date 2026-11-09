# SPDX-License-Identifier: GPL-3.0-or-later
"""Installing voices as system voices (Linux, Windows) and instructions for everything else."""

from __future__ import annotations

from vocalkeep.install.instructions import instructions

#: Targets ``vocalkeep install`` understands.
INSTALL_TARGETS = ("linux", "windows", "saywell", "android", "nvda", "macos")
#: Targets Vocalkeep installs to directly. The rest get step-by-step instructions.
DIRECT_TARGETS = ("linux", "windows")

__all__ = ["DIRECT_TARGETS", "INSTALL_TARGETS", "instructions"]
