# SPDX-License-Identifier: GPL-3.0-or-later
"""Converting a Piper voice for Sherpa-ONNX (used by Saywell, SherpaTTS and VoiceGarden).

Sherpa-ONNX reads a Piper model directly, but wants two extra things, exactly as its own
``scripts/piper/add_meta_data.py`` makes them:

* metadata inside the ``.onnx`` file (``model_type``, ``comment``, ``language``, ``voice``…);
* ``tokens.txt``: one ``<symbol> <id>`` line per phoneme in the voice's ``phoneme_id_map``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vocalkeep.languages import language_name


def sherpa_metadata(config: dict[str, Any], language: str) -> dict[str, str | int]:
    """The metadata Sherpa-ONNX expects on a Piper model."""
    sample_rate = int(config["audio"]["sample_rate"])
    if sample_rate == 22500:
        # Some older voices say 22500 by mistake; Sherpa's script corrects it the same way.
        sample_rate = 22050
    voice = str(config.get("lang_code") or config["espeak"]["voice"])
    if voice == "pt-PT":
        voice = "pt"
    has_espeak, has_g2pw = 1, 0
    if config.get("phoneme_type") == "pinyin" and voice == "zh":
        has_espeak, has_g2pw = 0, 1
    return {
        "model_type": "vits",
        "comment": "piper",
        "language": language_name(language),
        "voice": voice,
        "version": 1,
        "has_espeak": has_espeak,
        "has_g2pw": has_g2pw,
        "n_speakers": int(config["num_speakers"]),
        "sample_rate": sample_rate,
    }


def tokens_text(config: dict[str, Any]) -> str:
    """``tokens.txt`` for a Piper config: ``<symbol> <id>`` per line, the newline symbol left out.

    The space symbol gives a line that starts with a space (``"  3"``); that is intended.
    """
    lines = []
    for symbol, ids in config["phoneme_id_map"].items():
        if symbol == "\n":
            continue
        first = ids[0] if isinstance(ids, list) else ids
        lines.append(f"{symbol} {first}\n")
    return "".join(lines)


def write_tokens(config: dict[str, Any], path: Path) -> None:
    path.write_text(tokens_text(config), encoding="utf-8", newline="\n")


def add_metadata(src: Path, dst: Path, metadata: dict[str, str | int]) -> None:
    """Copies the model ``src`` to ``dst`` with its metadata replaced by ``metadata``."""
    import onnx

    model = onnx.load(str(src))
    while len(model.metadata_props):
        model.metadata_props.pop()
    for key, value in metadata.items():
        prop = model.metadata_props.add()
        prop.key = key
        prop.value = str(value)
    dst.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(dst))


def read_metadata(path: Path) -> dict[str, str]:
    """The metadata stored in an ONNX model."""
    import onnx

    model = onnx.load(str(path), load_external_data=False)
    return {p.key: p.value for p in model.metadata_props}
