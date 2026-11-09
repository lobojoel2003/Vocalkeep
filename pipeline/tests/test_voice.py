# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_voice, piper_config, tiny_onnx
from vocalkeep.errors import VocalkeepError
from vocalkeep.languages import (
    espeak_voice_for,
    iso639_3,
    language_name,
    normalize_tag,
    piper_language_code,
    windows_langid,
)
from vocalkeep.voice import SONATA_VOICE_PATTERN, load_voice, make_voice_id, sanitize_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane", "jane"),
        ("Jane Doe", "jane_doe"),
        ("Zoë O'Brien-Smith", "zoe_o_brien_smith"),
        ("  José  ", "jose"),
        ("R2-D2", "r_d"),
        ("", "vocalkeep"),
        ("123", "vocalkeep"),
        ("李雷", "vocalkeep"),
    ],
)
def test_sanitize_name(name: str, expected: str) -> None:
    assert sanitize_name(name) == expected


@pytest.mark.parametrize(
    ("language", "name"),
    [("en-US", "Jane"), ("en-GB", "Zoë O'Brien"), ("en_us", "Sam"), ("de-DE", "Jürgen")],
)
def test_voice_ids_parse_back_with_sonatas_pattern(language: str, name: str) -> None:
    voice_id = make_voice_id(language, name)
    m = SONATA_VOICE_PATTERN.match(voice_id)
    assert m, voice_id
    assert m.group("language") == voice_id.split("-")[0]
    assert m.group("name") == sanitize_name(name)
    assert m.group("quality") == "medium"
    assert m.group(0) == voice_id


def test_example_id() -> None:
    assert make_voice_id("en-US", "Jane") == "en_US-jane-medium"


def test_languages() -> None:
    assert normalize_tag("en_us") == "en-US"
    assert normalize_tag("zh-hant-tw") == "zh-Hant-TW"
    assert piper_language_code("en-GB") == "en_GB"
    assert espeak_voice_for("en-US") == "en-us"
    assert espeak_voice_for("en-GB") == "en-gb-x-rp"
    assert espeak_voice_for("de-DE") == "de"
    assert espeak_voice_for("pt-BR") == "pt-br"
    assert language_name("en-US") == "English"
    assert iso639_3("en-GB") == "eng"
    assert iso639_3("de") == "deu"
    assert windows_langid("en-US") == "409"
    assert windows_langid("en-GB") == "809"
    assert windows_langid("en-ZA") == "1c09"
    assert windows_langid("es-AR") == "a"


def test_load_voice_folder(tmp_path: Path) -> None:
    folder = make_voice(tmp_path)
    v = load_voice(folder)
    assert v.id == "en_US-jane_doe-medium"
    assert v.sample_rate == 22050
    assert v.language == "en-US"
    assert v.name == "Jane Doe"
    assert v.gender == "female"
    assert v.model_card is not None
    assert load_voice(v.onnx).id == v.id
    assert load_voice(v.config_path).id == v.id


def test_load_plain_piper_voice(tmp_path: Path) -> None:
    onnx = tiny_onnx(tmp_path / "en_GB-alba-medium.onnx")
    (tmp_path / "en_GB-alba-medium.onnx.json").write_text(json.dumps(piper_config()))
    v = load_voice(onnx)
    assert v.id == "en_GB-alba-medium"
    assert v.language == "en-GB"
    assert v.name == "Alba"
    assert v.gender is None
    assert "No model card" in v.model_card_text


def test_load_voice_errors(tmp_path: Path) -> None:
    with pytest.raises(VocalkeepError, match="no voice"):
        load_voice(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    with pytest.raises(VocalkeepError, match=r"no \.onnx"):
        load_voice(tmp_path / "empty")
    onnx = tiny_onnx(tmp_path / "lonely" / "x.onnx")
    with pytest.raises(VocalkeepError, match="no settings file"):
        load_voice(onnx)
    (tmp_path / "lonely" / "x.onnx.json").write_text(json.dumps({"audio": {}}))
    with pytest.raises(VocalkeepError, match="missing settings Piper needs"):
        load_voice(onnx)
