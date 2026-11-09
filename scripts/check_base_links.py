#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that every starting voice's checkpoint can still be downloaded (HEAD request).

    python3 scripts/check_base_links.py

Reads pipeline/src/vocalkeep/data/base_models.json. Standard library only.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "pipeline" / "src" / "vocalkeep" / "data" / "base_models.json"


def head(url: str) -> tuple[int, int | None]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "vocalkeep-ci"})
    with urllib.request.urlopen(request, timeout=60) as response:
        length = response.headers.get("Content-Length")
        return response.status, int(length) if length else None


def main() -> None:
    bases = json.loads(REGISTRY.read_text(encoding="utf-8"))["bases"]
    failed = 0
    for base in bases:
        url = base["checkpointUrl"]
        try:
            status, length = head(url)
            size = f"{length / 1e6:.0f} MB" if length else "size unknown"
            print(f"✓ {base['id']}: {status}, {size}")
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"✗ {base['id']}: {url}: {e}", file=sys.stderr)
            failed += 1
    if failed:
        raise SystemExit(f"{failed} checkpoint link(s) failed")


if __name__ == "__main__":
    main()
