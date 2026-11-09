#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build shared/prompts/arctic-en.json from the CMU ARCTIC prompt list.

    git clone --depth 1 https://github.com/festvox/festvox
    python3 scripts/import_arctic.py festvox/src/vox_files/prompts/cmuarctic.data
    python3 scripts/annotate_prompts.py

CMU ARCTIC (Kominek and Black, 2003) is a set of 1,132 sentences from out-of-copyright books,
chosen to cover the sounds of English with as few sentences as possible. It is distributed under
a permissive licence (see shared/prompts/LICENSES/CMU-ARCTIC.txt), which asks that modifications
are clearly marked: Vocalkeep leaves out the sentences listed in EXCLUDED (violence, death,
illness, choking, and dated language about ethnicity) and changes nothing else.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "shared" / "prompts" / "arctic-en.json"

# Left out because they may be upsetting to read aloud for someone who is ill, or use dated
# language. Reviewed by hand; see the module docstring.
EXCLUDED = {
    "arctic_a0082", "arctic_a0085", "arctic_a0086", "arctic_a0087", "arctic_a0106",
    "arctic_a0112", "arctic_a0113", "arctic_a0123", "arctic_a0148", "arctic_a0211",
    "arctic_a0215", "arctic_a0220", "arctic_a0236", "arctic_a0255", "arctic_a0269",
    "arctic_a0300", "arctic_a0313", "arctic_a0396", "arctic_a0424", "arctic_a0451",
    "arctic_a0477", "arctic_a0528", "arctic_a0544", "arctic_a0565", "arctic_a0577",
    "arctic_a0589",
    "arctic_b0003", "arctic_b0004", "arctic_b0007", "arctic_b0037", "arctic_b0084",
    "arctic_b0088", "arctic_b0092", "arctic_b0104", "arctic_b0126", "arctic_b0131",
    "arctic_b0147", "arctic_b0148", "arctic_b0168", "arctic_b0174", "arctic_b0192",
    "arctic_b0193", "arctic_b0212", "arctic_b0331", "arctic_b0383", "arctic_b0393",
    "arctic_b0396", "arctic_b0397", "arctic_b0446", "arctic_b0523", "arctic_b0536",
}  # fmt: skip

LINE = re.compile(r'^\(\s*(arctic_[ab]\d{4})\s+"(.*)"\s*\)\s*$')


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1])
    prompts = []
    seen = set()
    for raw in source.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        m = LINE.match(raw.strip())
        if not m:
            raise SystemExit(f"unexpected line: {raw!r}")
        pid, text = m.groups()
        seen.add(pid)
        if pid in EXCLUDED:
            continue
        prompts.append({"id": pid, "text": " ".join(text.split())})
    missing = EXCLUDED - seen
    if missing:
        raise SystemExit(f"excluded ids not in the source: {sorted(missing)}")

    # Keep phonemes from a previous run so re-importing doesn't need eSpeak NG.
    old = {}
    if OUT.exists():
        old = {p["id"]: p.get("ph") for p in json.loads(OUT.read_text())["prompts"]}
    for p in prompts:
        if old.get(p["id"]):
            p["ph"] = old[p["id"]]

    data = {
        "id": "arctic-en",
        "language": "en",
        "title": "Sound-rich sentences",
        "description": (
            "Sentences from classic books, chosen by Carnegie Mellon University to cover the "
            "sounds of English quickly. They teach your voice every sound it will need."
        ),
        "license": "CMU-ARCTIC",
        "source": "CMU ARCTIC prompts (festvox), with 51 sentences left out by Vocalkeep",
        "attribution": (
            "CMU ARCTIC databases, John Kominek and Alan W Black, Language Technologies "
            "Institute, Carnegie Mellon University. Copyright (c) 1998-2020 Carnegie Mellon "
            "University and Alan W Black and Kevin A. Lenzo."
        ),
        "prompts": prompts,
    }
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(prompts)} prompts ({len(EXCLUDED)} left out)")


if __name__ == "__main__":
    main()
