# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

import onnx

from conftest import PHONEME_ID_MAP, piper_config, tiny_onnx
from vocalkeep.sherpa import add_metadata, read_metadata, sherpa_metadata, tokens_text


def test_metadata_matches_sherpas_script() -> None:
    meta = sherpa_metadata(piper_config(), "en-US")
    assert meta == {
        "model_type": "vits",
        "comment": "piper",
        "language": "English",
        "voice": "en-us",
        "version": 1,
        "has_espeak": 1,
        "has_g2pw": 0,
        "n_speakers": 1,
        "sample_rate": 22050,
    }


def test_metadata_quirks() -> None:
    config = piper_config(sample_rate=22500, espeak="pt-PT")
    meta = sherpa_metadata(config, "pt-PT")
    assert meta["sample_rate"] == 22050
    assert meta["voice"] == "pt"
    assert meta["language"] == "Portuguese"
    config = piper_config(espeak="zh")
    config["phoneme_type"] = "pinyin"
    meta = sherpa_metadata(config, "zh-CN")
    assert (meta["has_espeak"], meta["has_g2pw"]) == (0, 1)


def test_tokens_txt() -> None:
    text = tokens_text(piper_config())
    lines = text.split("\n")
    assert lines[-1] == ""
    lines = lines[:-1]
    assert len(lines) == len(PHONEME_ID_MAP) - 1  # the newline symbol is left out
    assert "_ 0" in lines and "^ 1" in lines and "$ 2" in lines
    assert "  3" in lines  # the space symbol
    assert "ə 59" in lines
    assert all("\n" not in line for line in lines)


def test_tokens_accept_plain_ints() -> None:
    config = piper_config()
    config["phoneme_id_map"] = {"a": 5, "b": [6, 7]}
    assert tokens_text(config) == "a 5\nb 6\n"


def test_add_metadata_replaces_existing(tmp_path: Path) -> None:
    src = tiny_onnx(tmp_path / "m.onnx")
    assert read_metadata(src) == {"old": "should be removed"}
    dst = tmp_path / "out" / "m.onnx"
    add_metadata(src, dst, sherpa_metadata(piper_config(), "en-US"))
    meta = read_metadata(dst)
    assert "old" not in meta
    assert meta["model_type"] == "vits" and meta["comment"] == "piper"
    assert meta["n_speakers"] == "1" and meta["sample_rate"] == "22050"
    onnx.checker.check_model(onnx.load(str(dst)))
    assert read_metadata(src) == {"old": "should be removed"}, "the original is untouched"
