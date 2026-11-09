# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from conftest import TakeSpec, make_bank
from vocalkeep.bank import open_bank, safe_name, safe_relative_path
from vocalkeep.errors import VocalkeepError


def _zip_dir(src: Path, dest: Path, prefix: str = "") -> Path:
    with zipfile.ZipFile(dest, "w") as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, prefix + f.relative_to(src).as_posix())
    return dest


def test_opens_a_bank_folder(bank_dir: Path) -> None:
    with open_bank(bank_dir) as bank:
        assert bank.speaker.name == "Jane Doe"
        assert bank.speaker.language == "en-US"
        assert bank.speaker.gender == "female"
        assert bank.id.startswith("0b1c")
        assert len(bank.takes) == 7
        take = bank.takes[0]
        assert take.prompt_id == "arctic_a0001"
        assert bank.resolve(take.file).is_file()
        assert take.stored_quality == {"verdict": "good", "issues": []}


def test_parent_folder_with_one_bank_is_accepted(bank_dir: Path) -> None:
    with open_bank(bank_dir.parent) as bank:
        assert bank.root == bank_dir


def test_bank_json_path_is_accepted(bank_dir: Path) -> None:
    with open_bank(bank_dir / "bank.json") as bank:
        assert bank.root == bank_dir


def test_not_a_bank(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    message = "doesn't look like a Vocalkeep voice bank"
    with pytest.raises(VocalkeepError, match=message), open_bank(tmp_path / "x"):
        pass
    with pytest.raises(VocalkeepError, match="no voice bank"), open_bank(tmp_path / "missing"):
        pass
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    with (
        pytest.raises(VocalkeepError, match="isn't a voice bank"),
        open_bank(tmp_path / "notes.txt"),
    ):
        pass


def test_damaged_manifest_falls_back_to_recovery_copy(tmp_path: Path) -> None:
    root = make_bank(tmp_path / "b", [TakeSpec("a")])
    (root / "bank.json.bak").write_text(
        (root / "bank.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "bank.json").write_text("{ not json", encoding="utf-8")
    with open_bank(root) as bank:
        assert bank.takes[0].prompt_id == "a"


def test_damaged_manifest_without_backup(tmp_path: Path) -> None:
    root = make_bank(tmp_path / "b", [TakeSpec("a")])
    (root / "bank.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(VocalkeepError, match="damaged"), open_bank(root):
        pass


def test_rejects_other_formats_and_newer_versions(tmp_path: Path) -> None:
    root = make_bank(tmp_path / "b", [TakeSpec("a")])
    data = json.loads((root / "bank.json").read_text(encoding="utf-8"))
    data["version"] = 2
    (root / "bank.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(VocalkeepError, match="newer version"), open_bank(root):
        pass
    (root / "bank.json").write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(VocalkeepError, match="not a Vocalkeep voice bank"), open_bank(root):
        pass


@pytest.mark.parametrize("prefix", ["", "Vocalkeep voice bank - Jane/"])
def test_opens_a_backup_zip(tmp_path: Path, bank_dir: Path, prefix: str) -> None:
    archive = _zip_dir(bank_dir, tmp_path / "backup.zip", prefix)
    with open_bank(archive) as bank:
        extracted = bank.root
        assert bank.source == archive
        assert len(bank.takes) == 7
        assert bank.resolve(bank.takes[0].file).is_file()
    assert not extracted.exists(), "the temporary folder is removed afterwards"


@pytest.mark.parametrize(
    "evil", ["../evil.txt", "/etc/evil", "C:/evil.txt", "folder/../../evil.txt", "a\\..\\..\\x"]
)
def test_zip_slip_is_refused(tmp_path: Path, bank_dir: Path, evil: str) -> None:
    archive = _zip_dir(bank_dir, tmp_path / "backup.zip")
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr(evil, "gotcha")
    with pytest.raises(VocalkeepError, match="unsafe"), open_bank(archive):
        pass
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


def test_zip_without_bank(tmp_path: Path) -> None:
    archive = tmp_path / "x.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a/b/bank.json", "{}")  # too deep
        z.writestr("readme.txt", "hi")
    message = "doesn't contain a Vocalkeep voice bank"
    with pytest.raises(VocalkeepError, match=message), open_bank(archive):
        pass


def test_bad_zip(tmp_path: Path) -> None:
    archive = tmp_path / "x.zip"
    archive.write_bytes(b"PK\x03\x04 broken")
    with pytest.raises(VocalkeepError), open_bank(archive):
        pass


def test_unsafe_take_paths_are_refused(tmp_path: Path) -> None:
    for bad in ("../outside.wav", "/etc/passwd", "./a.wav", "C:\\x.wav", ""):
        with pytest.raises(VocalkeepError):
            safe_relative_path(bad)
    assert str(safe_relative_path("recordings/a/b.wav")) == "recordings/a/b.wav"


def test_safe_name_matches_the_app() -> None:
    assert safe_name("a/b\\c..d") == "a_b_c__d"
    assert safe_name("") == "_"
    assert safe_name("personal-0001") == "personal-0001"
