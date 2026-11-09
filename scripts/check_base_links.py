#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that every starting voice's checkpoint can still be downloaded.

    python3 scripts/check_base_links.py                       # report only
    python3 scripts/check_base_links.py --fix                 # also update the registry
    python3 scripts/check_base_links.py --report report.json  # machine-readable results

Reads pipeline/src/vocalkeep/data/base_models.json. Each checkpoint is one of:

- ok:    the link works.
- moved: the link is gone but its folder in Piper's repository holds a replacement (Piper
         reorganises checkpoints now and then). Not a failure: the voice builder follows the
         move by itself. --fix writes the new link and epoch into the registry.
- gone:  no checkpoint is left in the folder, or the server can't be reached. A failure.

Exit status 1 only if something is gone. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "pipeline" / "src" / "vocalkeep" / "data" / "base_models.json"
RESOLVE = "/resolve/main/"
REPO = "https://huggingface.co/datasets/rhasspy/piper-checkpoints"
API = "https://huggingface.co/api/datasets/rhasspy/piper-checkpoints/tree/main/"
EPOCH = re.compile(r"epoch=(\d+)")
HEADERS = {"User-Agent": "vocalkeep-ci (+https://github.com/lobojoel2003/Vocalkeep)"}


def _request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers=HEADERS)


def head(url: str, attempts: int = 2) -> int | None:
    """Content length of a working link. Raises HTTPError (404 and so on) or URLError."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(_request(url, "HEAD"), timeout=60) as response:
                length = response.headers.get("Content-Length")
                return int(length) if length else None
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(5)
    return None  # pragma: no cover


def replacement(url: str) -> str | None:
    """The checkpoint now in a broken link's folder (the most trained one), or None."""
    if RESOLVE not in url:
        return None
    folder = unquote(url.split(RESOLVE, 1)[1]).rsplit("/", 1)[0]
    try:
        with urllib.request.urlopen(_request(API + quote(folder)), timeout=60) as response:
            entries = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    names = [
        str(e["path"])
        for e in entries
        if isinstance(e, dict) and str(e.get("path", "")).endswith(".ckpt")
    ]
    if not names:
        return None

    def trained(name: str) -> tuple[int, str]:
        match = EPOCH.search(name)
        return (int(match.group(1)) if match else -1, name)

    return f"{REPO}{RESOLVE}{quote(max(names, key=trained))}"


def fix_registry(raw: str, moved: list[dict[str, str]]) -> str:
    """Writes new links (and the epoch in each new file name) into the registry text."""
    for m in moved:
        old, new = m["old"], m["new"]
        if raw.count(old) != 1:
            raise SystemExit(f"{m['id']}: can't find its link in the registry")
        raw = raw.replace(old, new)
        match = EPOCH.search(unquote(new))
        epoch_line = re.compile(
            r'("checkpointUrl": "' + re.escape(new) + r'",\s*\n\s*)"checkpointEpoch": \d+,\s*\n'
        )
        if match:
            raw, n = epoch_line.subn(rf'\g<1>"checkpointEpoch": {match.group(1)},\n', raw)
            if n == 0:
                raw = raw.replace(
                    f'"checkpointUrl": "{new}",',
                    f'"checkpointUrl": "{new}",\n      "checkpointEpoch": {match.group(1)},',
                )
        else:
            # The epoch isn't in the name: the voice builder reads it from the checkpoint.
            raw = epoch_line.sub(r"\g<1>", raw)
    json.loads(raw)
    return raw


def annotate(level: str, title: str, message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title={title}::{message}")


def summary(results: list[dict[str, str]]) -> str:
    icon = {"ok": "✅", "moved": "🔀", "gone": "❌"}
    lines = [
        "## Starting voice checkpoints",
        "",
        "| Voice | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for r in results:
        lines.append(f"| `{r['id']}` | {icon[r['status']]} {r['status']} | {r['detail']} |")
    moved = [r for r in results if r["status"] == "moved"]
    if moved:
        lines += [
            "",
            "Moved checkpoints still work: the voice builder follows the move by itself. "
            "To update the registry, run `python3 scripts/check_base_links.py --fix` and commit.",
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fix", action="store_true", help="write moved links into the registry")
    parser.add_argument("--report", type=Path, help="write the results as JSON to this file")
    args = parser.parse_args()

    raw = REGISTRY.read_text(encoding="utf-8")
    bases = json.loads(raw)["bases"]
    results: list[dict[str, str]] = []
    for base in bases:
        url = base["checkpointUrl"]
        entry = {"id": base["id"], "old": url}
        try:
            length = head(url)
            size = f"{length / 1e6:.0f} MB" if length else "size unknown"
            results.append({**entry, "status": "ok", "detail": size})
            print(f"✓ {base['id']}: {size}")
            continue
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}"
            new = replacement(url) if e.code == 404 else None
        except (urllib.error.URLError, TimeoutError) as e:
            error, new = f"unreachable ({e})", None
        if new and new != url:
            name = unquote(new.rsplit("/", 1)[-1])
            results.append({**entry, "status": "moved", "new": new, "detail": f"now `{name}`"})
            print(f"→ {base['id']}: moved to {name}")
            annotate("warning", "Starting voice moved", f"{base['id']} is now {name}")
        else:
            results.append({**entry, "status": "gone", "detail": error})
            print(f"✗ {base['id']}: {url}: {error}", file=sys.stderr)
            annotate("error", "Starting voice missing", f"{base['id']}: {error}")

    moved = [r for r in results if r["status"] == "moved"]
    gone = [r for r in results if r["status"] == "gone"]
    if args.fix and moved:
        REGISTRY.write_text(fix_registry(raw, moved), encoding="utf-8")
        print(f"Updated {len(moved)} link(s) in {REGISTRY.relative_to(ROOT)}")
    if args.report:
        args.report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(summary(results))
    ok = len(results) - len(moved) - len(gone)
    print(f"{ok} ok, {len(moved)} moved, {len(gone)} missing")
    if gone:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
