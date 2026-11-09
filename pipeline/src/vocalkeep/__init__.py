# SPDX-License-Identifier: GPL-3.0-or-later
"""Vocalkeep's training pipeline.

Turns a voice bank recorded in the Vocalkeep desktop app into a Piper text-to-speech voice,
then packages and installs it as a system voice. Run ``vocalkeep --help`` to get started.
"""

from __future__ import annotations

# Kept equal to the repository's VERSION file (a test checks this).
__version__ = "0.1.0"

__all__ = ["__version__"]
