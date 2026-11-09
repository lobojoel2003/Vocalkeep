# SPDX-License-Identifier: GPL-3.0-or-later
"""``python -m vocalkeep`` runs the command-line tool."""

from __future__ import annotations

import sys

from vocalkeep.cli import main

if __name__ == "__main__":
    sys.exit(main())
