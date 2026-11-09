# SPDX-License-Identifier: GPL-3.0-or-later
"""Base voices: the Piper checkpoints a new voice is fine-tuned from.

Fine-tuning starts from a voice that already knows how to speak, so a few hundred sentences are
enough to make it sound like the person who recorded them. What the base voice was trained on
still matters for one thing: **its licence**. Piper adds no licence of its own; the licence of
the base voice's recordings governs what the new voice may be used for.

Most of Piper's medium voices were fine-tuned from *lessac*, whose recordings are licensed for
research only, so they inherit "not for commercial use". Vocalkeep recommends bases trained
from scratch on public domain recordings (LJ Speech, Kristin, Cori).

The registry lives in ``data/base_models.json``. Its entries use the same camelCase shape that
``vocalkeep bases --json`` prints (the desktop app embeds the file as a fallback).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Literal
from urllib.parse import unquote

from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import base_language, normalize_tag

Commercial = Literal["yes", "no", "conditions", "unknown"]
COMMERCIAL_VALUES: tuple[str, ...] = ("yes", "no", "conditions", "unknown")
LESSAC_ID = "en_US-lessac-medium"

_COMMERCIAL_TEXT = {
    "yes": "Commercial use: allowed.",
    "no": "Commercial use: not allowed. Personal and research use only.",
    "conditions": "Commercial use: allowed with conditions (see the licence).",
    "unknown": "Commercial use: unclear. Treat it as personal use only.",
}


@dataclass(frozen=True)
class BaseVoice:
    """One entry of the registry. ``raw`` is the entry exactly as stored."""

    id: str
    name: str
    voice_name: str
    language: str
    quality: str
    gender: str
    speakers: int
    espeak_voice: str
    dataset: str
    dataset_url: str
    license: str
    license_url: str | None
    commercial: Commercial
    lineage: str
    trained_from: str
    lineage_chain: tuple[str, ...]
    recommended: bool
    notes: str
    checkpoint_url: str
    checkpoint_epoch: int
    model_card: str
    sources: tuple[str, ...]
    raw: dict[str, Any]

    @property
    def checkpoint_filename(self) -> str:
        """The checkpoint's file name, decoded (``epoch=2164-step=1355540.ckpt``)."""
        return unquote(self.checkpoint_url.split("?", 1)[0].rsplit("/", 1)[-1])

    @property
    def from_lessac(self) -> bool:
        """True for lessac itself and every voice fine-tuned from it."""
        return self.id == LESSAC_ID or LESSAC_ID in self.lineage_chain

    @property
    def single_speaker(self) -> bool:
        return self.speakers == 1

    @property
    def can_fine_tune(self) -> bool:
        """Vocalkeep fine-tunes single-speaker medium checkpoints (they need no tweaks)."""
        return self.single_speaker and self.quality == "medium"

    @property
    def commercial_reason(self) -> str:
        if self.commercial == "yes":
            return "The recordings it was trained on are public domain."
        if self.id == LESSAC_ID:
            return "Its recordings (Blizzard 2013 Lessac) are licensed for research only."
        if self.from_lessac:
            return (
                "It was fine-tuned from lessac, whose recordings are licensed for research only "
                f"(its own recordings: {self.license})."
            )
        if self.commercial == "unknown":
            return f"The licence of everything it was built from isn't clear ({self.license})."
        return f"Its recordings' licence: {self.license}."

    def to_dict(self) -> dict[str, Any]:
        """The registry entry plus a few derived fields, for ``vocalkeep bases --json``."""
        out = dict(self.raw)
        out.setdefault("checkpointFilename", self.checkpoint_filename)
        out["canFineTune"] = self.can_fine_tune
        out["commercialReason"] = self.commercial_reason
        return out


def _parse(entry: dict[str, Any]) -> BaseVoice:
    return BaseVoice(
        id=entry["id"],
        name=entry["name"],
        voice_name=entry.get("voiceName") or entry["id"].split("-")[1],
        language=entry["language"],
        quality=entry.get("quality", "medium"),
        gender=entry.get("gender", "unknown"),
        speakers=int(entry.get("speakers", 1)),
        espeak_voice=entry["espeakVoice"],
        dataset=entry["dataset"],
        dataset_url=entry.get("datasetUrl", ""),
        license=entry["license"],
        license_url=entry.get("licenseUrl"),
        commercial=entry["commercial"],
        lineage=entry["lineage"],
        trained_from=entry.get("trainedFrom", "unknown"),
        lineage_chain=tuple(entry.get("lineageChain", [])),
        recommended=bool(entry.get("recommended", False)),
        notes=entry.get("notes", ""),
        checkpoint_url=entry["checkpointUrl"],
        checkpoint_epoch=int(entry.get("checkpointEpoch", 0)),
        model_card=entry.get("modelCard", ""),
        sources=tuple(entry.get("sources", [])),
        raw=dict(entry),
    )


@lru_cache(maxsize=1)
def registry() -> tuple[BaseVoice, ...]:
    """Every base voice Vocalkeep knows about."""
    text = (
        resources.files("vocalkeep").joinpath("data/base_models.json").read_text(encoding="utf-8")
    )
    data = json.loads(text)
    entries = data["bases"] if isinstance(data, dict) else data
    return tuple(_parse(e) for e in entries)


def find_base(identifier: str) -> BaseVoice:
    """Looks a base voice up by id (``en_US-ljspeech-medium``), ``en_US-ljspeech`` or its short
    name (``ljspeech``). Case doesn't matter."""
    key = identifier.strip().lower().replace(" ", "_")
    bases = registry()
    for base in bases:
        if key in (base.id.lower(), base.id.lower().removesuffix("-medium")):
            return base
    by_name = [b for b in bases if b.voice_name.lower() == key]
    if len(by_name) == 1:
        return by_name[0]
    suggestions = ", ".join(b.voice_name for b in bases if b.recommended)
    raise VocalkeepError(
        f"There is no base voice called '{identifier}'.",
        f"Run 'vocalkeep bases' to see them all. Recommended: {suggestions}.",
    )


def list_bases(
    language: str | None = None,
    *,
    commercial_only: bool = False,
) -> list[BaseVoice]:
    """Base voices, recommended ones first. ``language`` may be a full tag (``en-US``) or a
    language (``en``)."""
    result = list(registry())
    if language:
        tag = normalize_tag(language)
        if "-" in tag:
            result = [b for b in result if b.language.lower() == tag.lower()]
        else:
            result = [b for b in result if base_language(b.language) == tag.lower()]
    if commercial_only:
        result = [b for b in result if b.commercial == "yes"]
    # Stable sort: within each group the registry's own order is kept.
    return sorted(
        result, key=lambda b: (not b.recommended, b.commercial != "yes", not b.can_fine_tune)
    )


def default_base(language: str, gender: str | None = None) -> BaseVoice:
    """A sensible base for a bank: recommended, same language (or at least the same family)."""
    candidates = [b for b in list_bases(language) if b.can_fine_tune and b.commercial == "yes"]
    if not candidates:
        candidates = [
            b
            for b in list_bases(base_language(language))
            if b.can_fine_tune and b.commercial == "yes"
        ]
    if not candidates:
        candidates = [b for b in registry() if b.recommended]
    if gender:
        same = [b for b in candidates if b.gender == gender.lower()]
        if same:
            candidates = same
    recommended = [b for b in candidates if b.recommended]
    return (recommended or candidates)[0]


def commercial_text(commercial: str) -> str:
    return _COMMERCIAL_TEXT.get(commercial, _COMMERCIAL_TEXT["unknown"])


def licence_notice(base: BaseVoice) -> str:
    """What the person should know about the base voice before training, in plain words."""
    lines = [
        f"Starting voice: {base.name} [{base.id}]. {base.lineage}.",
        f"It learned from: {base.dataset}. Licence: {base.license}.",
        f"{commercial_text(base.commercial)} {base.commercial_reason}",
    ]
    if base.commercial != "yes":
        good = ", ".join(b.voice_name for b in registry() if b.recommended)
        lines.append(f"For a voice without these limits, start from one of: {good}.")
    lines.append("Your recordings stay yours, and the voice made from them is your voice.")
    return "\n".join(lines)
