# SPDX-License-Identifier: GPL-3.0-or-later
"""The base voice registry: its shape (the desktop app embeds the file) and licence policy."""

from __future__ import annotations

import json
from importlib import resources
from urllib.parse import urlparse

import pytest

from vocalkeep.bases import (
    COMMERCIAL_VALUES,
    LESSAC_ID,
    default_base,
    find_base,
    licence_notice,
    list_bases,
    registry,
)
from vocalkeep.errors import VocalkeepError

APP_KEYS = {
    "id",
    "name",
    "language",
    "quality",
    "dataset",
    "license",
    "commercial",
    "lineage",
    "recommended",
    "notes",
    "checkpointUrl",
    "sources",
}


def _raw_entries() -> list[dict]:
    text = resources.files("vocalkeep").joinpath("data/base_models.json").read_text("utf-8")
    data = json.loads(text)
    return data["bases"] if isinstance(data, dict) else data


def test_file_has_the_shape_the_app_reads() -> None:
    entries = _raw_entries()
    assert len(entries) >= 20
    for e in entries:
        assert set(e) >= APP_KEYS, e["id"]
        assert all("_" not in k for k in e), f"camelCase keys only: {e['id']}"
        assert isinstance(e["lineage"], str) and isinstance(e["dataset"], str)
        assert isinstance(e["sources"], list) and e["sources"]
        assert e["notes"].endswith(".") and len(e["notes"]) < 140


def test_ids_are_unique_and_piper_style() -> None:
    ids = [b.id for b in registry()]
    assert len(ids) == len(set(ids))
    names = [b.voice_name for b in registry()]
    assert len(names) == len(set(names))
    for b in registry():
        assert b.id == f"{b.language.replace('-', '_')}-{b.voice_name}-{b.quality}"
        assert b.quality == "medium"


def test_urls_are_https_and_point_at_checkpoints() -> None:
    for b in registry():
        url = urlparse(b.checkpoint_url)
        assert url.scheme == "https", b.id
        assert url.netloc == "huggingface.co"
        assert url.path.startswith("/datasets/rhasspy/piper-checkpoints/resolve/main/")
        assert b.checkpoint_filename.endswith(".ckpt")
        assert urlparse(b.model_card).scheme == "https"
        for source in b.sources:
            assert urlparse(source).scheme in ("http", "https")


def test_commercial_values_are_known() -> None:
    for b in registry():
        assert b.commercial in COMMERCIAL_VALUES


def test_lessac_lineage_is_never_commercial() -> None:
    lessac = find_base("lessac")
    assert lessac.id == LESSAC_ID
    assert lessac.commercial == "no"
    descendants = [b for b in registry() if LESSAC_ID in b.lineage_chain]
    assert len(descendants) >= 15
    for b in descendants:
        assert b.from_lessac
        assert b.commercial == "no", b.id
        assert "lessac" in b.lineage.lower()


def test_recommended_bases_are_public_domain_from_scratch() -> None:
    recommended = [b for b in registry() if b.recommended]
    assert {b.voice_name for b in recommended} == {"ljspeech", "kristin", "cori"}
    for b in recommended:
        assert b.trained_from == "scratch"
        assert b.lineage_chain == ()
        assert b.license == "Public domain"
        assert b.commercial == "yes"
        assert b.can_fine_tune


def test_only_public_domain_chains_are_commercial() -> None:
    for b in registry():
        if b.commercial == "yes":
            assert b.license == "Public domain"
            assert not b.from_lessac
            for parent in b.lineage_chain:
                assert find_base(parent).commercial == "yes"


def test_multi_speaker_bases_are_marked() -> None:
    multi = {b.voice_name for b in registry() if not b.can_fine_tune}
    assert multi == {"arctic", "l2arctic", "libritts_r", "aru", "semaine", "vctk"}


def test_epochs_from_names() -> None:
    assert find_base("lessac").checkpoint_epoch == 2164
    assert find_base("lessac").checkpoint_filename == "epoch=2164-step=1355540.ckpt"
    assert find_base("ljspeech").checkpoint_epoch == 1000
    assert find_base("cori").checkpoint_epoch == 640


def test_lookup_by_id_short_id_or_name() -> None:
    assert find_base("en_US-ljspeech-medium").voice_name == "ljspeech"
    assert find_base("en_US-ljspeech").voice_name == "ljspeech"
    assert find_base("LJSpeech").voice_name == "ljspeech"
    with pytest.raises(VocalkeepError, match="no base voice called"):
        find_base("nobody")


def test_filters_and_defaults() -> None:
    gb = list_bases("en-GB")
    assert gb and all(b.language == "en-GB" for b in gb)
    assert gb[0].voice_name == "cori"
    assert all(b.commercial == "yes" for b in list_bases(commercial_only=True))
    assert len(list_bases("en")) == len(registry())
    assert list_bases()[0].recommended
    assert default_base("en-US").voice_name == "ljspeech"
    assert default_base("en-GB").voice_name == "cori"
    assert default_base("en-US", "male").voice_name == "john"
    assert default_base("en-AU").voice_name in {"ljspeech", "kristin", "cori"}


def test_licence_notice_points_out_limits() -> None:
    text = licence_notice(find_base("ryan"))
    assert "not allowed" in text and "lessac" in text and "ljspeech" in text
    assert "allowed" in licence_notice(find_base("ljspeech"))
