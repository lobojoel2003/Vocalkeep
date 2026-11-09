# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a Vocalkeep voice bank: a folder, or a backup zip of one.

A bank is a plain folder (format described in ``docs/voice-bank-format.md`` and
``crates/vocalkeep-core/src/bank.rs``)::

    My voice bank/
      bank.json                     what was said in each recording, quality, sessions
      bank.json.bak                 the previous save, used if bank.json is damaged
      recordings/<set>/<prompt>.wav one take per prompt (16-bit PCM mono)

A backup made by the app is a zip with ``bank.json`` at the top or inside one folder. It is
unpacked to a temporary folder, refusing any entry that would land outside it.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from vocalkeep.errors import VocalkeepError

BANK_FORMAT = "vocalkeep-bank"
BANK_VERSION = 1
MANIFEST = "bank.json"
BACKUP = "bank.json.bak"

#: Largest backup we unpack: about 40 hours of 48 kHz speech (the same limit as the app).
MAX_RESTORE_BYTES = 16 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class Speaker:
    #: The name the voice will carry ("Jane's voice").
    name: str
    #: BCP 47 language tag of the recordings, e.g. ``en-US``.
    language: str = "en-US"
    #: Only used to label the finished system voice: "female", "male" or "neutral".
    gender: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "language": self.language}
        if self.gender:
            d["gender"] = self.gender
        return d


@dataclass(frozen=True)
class Take:
    """The kept recording of one prompt."""

    prompt_id: str
    set_id: str
    text: str
    #: Path relative to the bank folder, with ``/`` separators.
    file: str
    sample_rate: int = 0
    duration_ms: int = 0
    recorded_at: str = ""
    session_id: str | None = None
    attempts: int = 1
    #: The quality result stored by the app. The pipeline checks the audio again instead.
    stored_quality: dict[str, Any] | None = None


@dataclass
class Bank:
    root: Path
    id: str
    speaker: Speaker
    takes: list[Take] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    #: Where the bank came from (the zip file, when it was a backup).
    source: Path | None = None

    def resolve(self, relative: str) -> Path:
        """Absolute path of a file named in the manifest. Refuses paths that leave the bank."""
        return self.root / safe_relative_path(relative, what="voice bank")


def safe_relative_path(relative: str, *, what: str = "archive") -> PurePosixPath:
    """A relative path that stays inside its folder, or an error.

    Absolute paths, drive letters, ``..`` and ``.`` parts are refused. Backslashes are treated
    as separators so a zip made on Windows is checked the same way.
    """
    cleaned = relative.replace("\\", "/")
    parts = [p for p in cleaned.split("/") if p != ""]
    if (
        not parts
        or cleaned.startswith("/")
        or any(p in (".", "..") for p in parts)
        or ":" in parts[0]
        or any("\x00" in p for p in parts)
    ):
        raise VocalkeepError(f"The {what} contains an unsafe file path: {relative!r}.")
    return PurePosixPath(*parts)


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise VocalkeepError(f"{path} is damaged and couldn't be read ({e}).") from e
    if not isinstance(data, dict) or data.get("format") != BANK_FORMAT:
        raise VocalkeepError(f"{path} is not a Vocalkeep voice bank.")
    version = data.get("version")
    if not isinstance(version, int) or version > BANK_VERSION:
        raise VocalkeepError(
            f"This voice bank was saved by a newer version of Vocalkeep (format {version}).",
            "Please update Vocalkeep (pip install --upgrade vocalkeep) and try again.",
        )
    return data


def _find_bank_dir(path: Path) -> Path:
    """The folder holding bank.json: ``path`` itself, or its only sub-folder that has one."""
    if (path / MANIFEST).is_file() or (path / BACKUP).is_file():
        return path
    candidates = [
        child
        for child in sorted(path.iterdir())
        if child.is_dir() and ((child / MANIFEST).is_file() or (child / BACKUP).is_file())
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise VocalkeepError(
        f"{path} doesn't look like a Vocalkeep voice bank: there is no bank.json in it.",
        "Choose the voice bank folder itself (the one that holds bank.json and the "
        "'recordings' folder), or a backup .zip made by Vocalkeep.",
    )


def _parse_take(raw: Any, index: int) -> Take | None:
    if not isinstance(raw, dict):
        return None
    prompt_id = str(raw.get("promptId") or f"take-{index + 1:04d}")
    quality = raw.get("quality")
    return Take(
        prompt_id=prompt_id,
        set_id=str(raw.get("setId") or ""),
        text=str(raw.get("text") or ""),
        file=str(raw.get("file") or ""),
        sample_rate=int(raw.get("sampleRate") or 0),
        duration_ms=int(raw.get("durationMs") or 0),
        recorded_at=str(raw.get("recordedAt") or ""),
        session_id=raw.get("sessionId"),
        attempts=int(raw.get("attempts") or 1),
        stored_quality=quality if isinstance(quality, dict) else None,
    )


def load_bank_dir(path: str | Path) -> Bank:
    """Opens a bank folder, falling back to the recovery copy if ``bank.json`` is damaged."""
    path = Path(path).expanduser()
    if not path.exists():
        raise VocalkeepError(f"There is no voice bank at {path}.")
    if not path.is_dir():
        raise VocalkeepError(f"{path} is a file, not a voice bank folder or backup zip.")
    root = _find_bank_dir(path)
    try:
        manifest = _read_manifest(root / MANIFEST)
    except (FileNotFoundError, VocalkeepError) as primary_error:
        backup = root / BACKUP
        if not backup.is_file():
            if isinstance(primary_error, FileNotFoundError):
                raise VocalkeepError(f"{root} has no bank.json.") from None
            raise
        try:
            manifest = _read_manifest(backup)
        except VocalkeepError:
            raise VocalkeepError(
                f"{root / MANIFEST} and its recovery copy are both damaged.",
                "Restore the bank from a backup zip if you have one.",
            ) from None
    speaker_raw = manifest.get("speaker") or {}
    speaker = Speaker(
        name=str(speaker_raw.get("name") or "").strip(),
        language=str(speaker_raw.get("language") or "en-US").strip() or "en-US",
        gender=(str(speaker_raw["gender"]).strip().lower() or None)
        if speaker_raw.get("gender")
        else None,
    )
    takes = [
        t
        for i, raw in enumerate(manifest.get("takes") or [])
        if (t := _parse_take(raw, i)) is not None
    ]
    return Bank(
        root=root,
        id=str(manifest.get("id") or ""),
        speaker=speaker,
        takes=takes,
        manifest=manifest,
    )


def extract_bank_zip(zip_path: Path, dest: Path) -> Path:
    """Unpacks a bank backup into ``dest`` and returns the bank folder.

    ``bank.json`` may be at the top of the zip or inside one folder. Entries with unsafe paths
    (absolute, ``..``, drive letters) are refused, so nothing can be written outside ``dest``.
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise VocalkeepError(
            f"{zip_path.name} isn't a zip file Vocalkeep can open.",
            "Choose the voice bank folder or the backup .zip made by Vocalkeep.",
        ) from e
    with archive:
        infos = archive.infolist()
        # Check every name first: one bad entry means the archive isn't trustworthy.
        names = [(info, safe_relative_path(info.filename, what="backup")) for info in infos]
        prefix: PurePosixPath | None = None
        for _info, name in names:
            if name.name == MANIFEST and len(name.parts) <= 2:
                prefix = name.parent
                break
        if prefix is None:
            raise VocalkeepError(
                f"{zip_path.name} doesn't contain a Vocalkeep voice bank (no bank.json).",
            )
        dest.mkdir(parents=True, exist_ok=True)
        total = 0
        for info, name in names:
            try:
                rel = name.relative_to(prefix) if prefix.parts else name
            except ValueError:
                continue
            if not rel.parts:
                continue
            out = dest.joinpath(*rel.parts)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, out.open("wb") as dst:
                while chunk := src.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_RESTORE_BYTES:
                        raise VocalkeepError(f"{zip_path.name} is too large to unpack.")
                    dst.write(chunk)
    return dest


@contextlib.contextmanager
def open_bank(path: str | Path) -> Iterator[Bank]:
    """Opens a bank folder or backup zip. A zip is unpacked to a temporary folder for the
    duration of the ``with`` block and removed afterwards."""
    path = Path(path).expanduser()
    if path.is_file():
        if not zipfile.is_zipfile(path):
            if path.name == MANIFEST:
                yield load_bank_dir(path.parent)
                return
            raise VocalkeepError(
                f"{path.name} isn't a voice bank.",
                "Choose the voice bank folder or the backup .zip made by Vocalkeep.",
            )
        tmp = Path(tempfile.mkdtemp(prefix="vocalkeep-bank-"))
        try:
            extract_bank_zip(path, tmp)
            bank = load_bank_dir(tmp)
            bank.source = path
            yield bank
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        bank = load_bank_dir(path)
        bank.source = bank.root
        yield bank


def safe_name(identifier: str) -> str:
    """A file-name-safe version of an id: letters, digits, ``-`` and ``_`` only (as the app)."""
    s = "".join(c if (c.isascii() and c.isalnum()) or c in "-_" else "_" for c in identifier)
    return s or "_"
