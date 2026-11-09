# SPDX-License-Identifier: GPL-3.0-or-later
"""A finished voice: a folder with the Piper model and what is known about it.

::

    en_US-jane-medium/
      en_US-jane-medium.onnx        the voice (Piper/ONNX)
      en_US-jane-medium.onnx.json   Piper's settings for it (written during training)
      MODEL_CARD                    plain text: whose voice, how it was made, licence
      voice.json                    the same, for programs (format "vocalkeep-voice")

Voice ids follow Piper's convention ``<language>-<name>-<quality>``. The name may only contain
lowercase letters and underscores, because the NVDA add-on Sonata reads the language, name and
quality back out of the file name.

Voices made elsewhere (a plain ``.onnx`` with its ``.onnx.json``) work too.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import normalize_tag, piper_language_code

VOICE_FORMAT = "vocalkeep-voice"
VOICE_VERSION = 1
QUALITY = "medium"
FALLBACK_NAME = "vocalkeep"

#: How Sonata (the NVDA add-on) parses voice file names. Kept here so a test can check ours.
SONATA_VOICE_PATTERN = re.compile(
    r"(?P<language>[a-z]+(_|-)?([a-z]+)?)(-|_)(?P<name>[a-z|_]+(\+RT)?)(-|_)"
    r"(?P<quality>(high|medium|low|x-low|x_low))",
    re.IGNORECASE,
)

#: Keys a Piper config must have for the voice to load anywhere.
REQUIRED_CONFIG_KEYS = ("audio.sample_rate", "espeak.voice", "phoneme_id_map", "num_speakers")


def sanitize_name(name: str) -> str:
    """A voice name made of lowercase ASCII letters and underscores.

    Accents are dropped (``Zoë`` → ``zoe``), anything else becomes ``_``. If nothing is left the
    name is ``vocalkeep``.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = re.sub(r"[^a-z]+", "_", ascii_only.lower()).strip("_")
    return out or FALLBACK_NAME


def make_voice_id(language: str, name: str, quality: str = QUALITY) -> str:
    """``("en-US", "Jane Doe")`` → ``en_US-jane_doe-medium``."""
    return f"{piper_language_code(language or 'en-US')}-{sanitize_name(name)}-{quality}"


def missing_config_keys(config: dict[str, Any]) -> list[str]:
    missing = []
    for dotted in REQUIRED_CONFIG_KEYS:
        node: Any = config
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                missing.append(dotted)
                break
            node = node[part]
    return missing


def validate_config(config: dict[str, Any], where: Path) -> None:
    missing = missing_config_keys(config)
    if missing:
        raise VocalkeepError(
            f"{where} is missing settings Piper needs: {', '.join(missing)}.",
            "It may not be a Piper voice config. Export the voice again with 'vocalkeep export'.",
        )


@dataclass
class Voice:
    """A voice on disk."""

    root: Path
    id: str
    onnx: Path
    config_path: Path
    config: dict[str, Any]
    model_card: Path | None = None
    info: dict[str, Any] = field(default_factory=dict)

    @property
    def sample_rate(self) -> int:
        return int(self.config["audio"]["sample_rate"])

    @property
    def espeak_voice(self) -> str:
        return str(self.config["espeak"]["voice"])

    @property
    def num_speakers(self) -> int:
        return int(self.config.get("num_speakers", 1))

    @property
    def language(self) -> str:
        """BCP 47 tag, e.g. ``en-US``."""
        if self.info.get("language"):
            return normalize_tag(str(self.info["language"]))
        lang = self.config.get("language")
        if isinstance(lang, dict) and lang.get("code"):
            return normalize_tag(str(lang["code"]))
        prefix = self.id.split("-", 1)[0]
        if re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", prefix):
            return normalize_tag(prefix)
        return normalize_tag(self.espeak_voice)

    @property
    def name(self) -> str:
        """The person's name, or the name part of the id."""
        if self.info.get("name"):
            return str(self.info["name"])
        parts = self.id.split("-")
        return parts[1].replace("_", " ").title() if len(parts) >= 3 else self.id

    @property
    def gender(self) -> str | None:
        g = self.info.get("gender")
        return str(g).lower() if g else None

    @property
    def model_card_text(self) -> str:
        if self.model_card and self.model_card.is_file():
            return self.model_card.read_text(encoding="utf-8")
        return f"# Model card for {self.id}\n\nNo model card came with this voice.\n"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise VocalkeepError(f"{path} is missing.") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise VocalkeepError(f"{path} is damaged ({e}).") from e
    if not isinstance(data, dict):
        raise VocalkeepError(f"{path} isn't a voice settings file.")
    return data


def _config_for(onnx: Path) -> Path:
    for candidate in (
        onnx.with_name(onnx.name + ".json"),
        onnx.with_suffix(".json"),
        onnx.parent / "config.json",
    ):
        if candidate.is_file() and candidate.name != "voice.json":
            return candidate
    raise VocalkeepError(
        f"{onnx.name} has no settings file next to it (expected {onnx.name}.json).",
        "Piper voices come as two files: the .onnx and its .onnx.json. Keep them together.",
    )


def load_voice(path: str | Path) -> Voice:
    """Opens a voice folder, a ``.onnx`` file or its ``.onnx.json``."""
    path = Path(path).expanduser()
    if not path.exists():
        raise VocalkeepError(
            f"There is no voice at {path}.",
            "Give the voice folder made by 'vocalkeep export', or a Piper .onnx file.",
        )
    info: dict[str, Any] = {}
    if path.is_dir():
        root = path
        info_path = root / "voice.json"
        if info_path.is_file():
            info = _load_json(info_path)
        onnx: Path | None = None
        if info.get("id") and (root / f"{info['id']}.onnx").is_file():
            onnx = root / f"{info['id']}.onnx"
        else:
            models = sorted(root.glob("*.onnx"), key=lambda p: p.stat().st_size, reverse=True)
            if not models:
                raise VocalkeepError(
                    f"{root} doesn't contain a voice (no .onnx file).",
                    "Give the folder made by 'vocalkeep export'.",
                )
            onnx = models[0]
    else:
        if path.name.endswith(".onnx.json"):
            path = path.with_name(path.name[: -len(".json")])
        if path.suffix != ".onnx":
            raise VocalkeepError(
                f"{path.name} isn't a voice.",
                "Give the voice folder made by 'vocalkeep export', or a Piper .onnx file.",
            )
        if not path.is_file():
            raise VocalkeepError(f"There is no voice at {path}.")
        onnx = path
        root = path.parent
        info_path = root / "voice.json"
        if info_path.is_file():
            candidate = _load_json(info_path)
            if candidate.get("id") == onnx.stem:
                info = candidate
    config_path = _config_for(onnx)
    config = _load_json(config_path)
    validate_config(config, config_path)
    voice_id = str(info.get("id") or onnx.stem)
    if voice_id == "model":
        voice_id = root.name.removeprefix("vits-piper-")
    card = root / "MODEL_CARD"
    return Voice(
        root=root,
        id=voice_id,
        onnx=onnx,
        config_path=config_path,
        config=config,
        model_card=card if card.is_file() else None,
        info=info,
    )
