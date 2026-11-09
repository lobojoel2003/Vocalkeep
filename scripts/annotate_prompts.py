#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Add eSpeak NG phonemes to every prompt in shared/prompts/*.json.

    python3 scripts/annotate_prompts.py           # fill in missing phonemes
    python3 scripts/annotate_prompts.py --all     # recompute every prompt
    python3 scripts/annotate_prompts.py --check   # fail if any prompt has no phonemes

Piper voices read text through eSpeak NG, so counting eSpeak's phonemes tells us which sounds a
voice bank already covers. The `ph` field holds words separated by spaces and phonemes by `_`,
with stress marks removed: "Hello there." -> "h_@_l_oU D_e@".
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "shared" / "prompts"
VOICES = {"en": "en-us"}
STRESS = re.compile(r"[',%=]")
# eSpeak writes pauses as "_:", "_;" and "_!", which the "_" separator splits apart.
PAUSE = re.compile(r"^[!:;?]+$")


def phonemize(texts: list[str], voice: str) -> list[str]:
    espeak = shutil.which("espeak-ng")
    if not espeak:
        raise SystemExit("espeak-ng is not installed (apt install espeak-ng)")
    out = []
    for text in texts:
        result = subprocess.run(
            [espeak, "-q", "-x", "--sep=_", "-v", voice, text],
            check=True,
            capture_output=True,
            text=True,
        )
        out.append(clean(result.stdout))
    return out


def clean(raw: str) -> str:
    words = []
    for word in raw.split():
        phonemes = [STRESS.sub("", p).lstrip("!") for p in word.split("_")]
        phonemes = [p for p in phonemes if p and not PAUSE.match(p) and p not in {"|", "||"}]
        if phonemes:
            words.append("_".join(phonemes))
    return " ".join(words)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="recompute every prompt")
    parser.add_argument("--check", action="store_true", help="only check that phonemes exist")
    args = parser.parse_args()

    failed = False
    for path in sorted(PROMPTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        prompts = data["prompts"]
        todo = [p for p in prompts if args.all or not p.get("ph")]
        if args.check:
            if todo:
                print(f"✗ {path.name}: {len(todo)} prompts without phonemes", file=sys.stderr)
                failed = True
            else:
                print(f"✓ {path.name}: {len(prompts)} prompts")
            continue
        if not todo:
            print(f"{path.name}: up to date")
            continue
        voice = VOICES.get(data["language"], data["language"])
        for p, ph in zip(todo, phonemize([p["text"] for p in todo], voice)):
            p["ph"] = ph
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{path.name}: annotated {len(todo)} prompts")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
