#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Print the CHANGELOG.md section for a version, for the GitHub Release notes.

    python3 scripts/release_notes.py v0.1.0 > notes.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def notes(version: str) -> str:
    version = version.removeprefix("refs/tags/").removeprefix("v")
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    body = re.sub(r"^\[[^\]]+\]: \S+\s*$", "", match.group(1), flags=re.M)
    return body.strip() + "\n"


if __name__ == "__main__":
    print(notes(sys.argv[1] if len(sys.argv) > 1 else ""), end="")
