#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy shared files from shared/ into the Python package.

    python3 scripts/sync-shared.py           # copy shared/quality.json into the pipeline package
    python3 scripts/sync-shared.py --check   # exit 1 if the packaged copy differs (used in CI)

The desktop app (Rust) compiles shared/quality.json in directly. The Python package cannot reach
outside its own folder once it is installed, so it ships a copy in
pipeline/src/vocalkeep/data/. This script keeps that copy identical. Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DATA = ROOT / "pipeline" / "src" / "vocalkeep" / "data"

# (source in shared/, copy in the package)
FILES: list[tuple[Path, Path]] = [
    (ROOT / "shared" / "quality.json", PACKAGE_DATA / "quality.json"),
]


def differs(source: Path, copy: Path) -> bool:
    return not copy.is_file() or source.read_bytes() != copy.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="only check; exit 1 if a packaged copy is missing or out of date",
    )
    args = parser.parse_args(argv)

    stale: list[tuple[Path, Path]] = []
    for source, copy in FILES:
        if not source.is_file():
            print(f"missing source file: {source.relative_to(ROOT)}", file=sys.stderr)
            return 1
        if differs(source, copy):
            stale.append((source, copy))

    if args.check:
        for source, copy in stale:
            print(
                f"{copy.relative_to(ROOT)} differs from {source.relative_to(ROOT)}; "
                "run: python3 scripts/sync-shared.py",
                file=sys.stderr,
            )
        if not stale:
            print("shared files are in sync")
        return 1 if stale else 0

    for source, copy in stale:
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, copy)
        print(f"updated {copy.relative_to(ROOT)}")
    if not stale:
        print("shared files are already in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
