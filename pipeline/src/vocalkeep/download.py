# SPDX-License-Identifier: GPL-3.0-or-later
"""Downloading base checkpoints: resumable, size-checked, with progress.

Checkpoints are large (hundreds of megabytes), and home internet connections drop. A download
writes to ``<file>.part`` and, if interrupted, carries on from where it stopped next time (HTTP
range requests). The finished size is checked against what the server announced. No checksums
are published for these files, so none are checked.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from vocalkeep import __version__
from vocalkeep.errors import VocalkeepError
from vocalkeep.progress import NullReporter, Reporter

CHUNK = 1024 * 1024
_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")


def _size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"  # pragma: no cover


def _open(url: str, start: int, timeout: float) -> Any:
    headers = {
        "User-Agent": f"vocalkeep/{__version__} (+https://github.com/lobojoel2003/Vocalkeep)"
    }
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https URLs from the registry
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def download_file(
    url: str,
    dest: Path,
    *,
    reporter: Reporter | None = None,
    stage: str = "download",
    timeout: float = 60,
    what: str = "the starting voice",
) -> Path:
    """Downloads ``url`` to ``dest`` (resuming a ``.part`` file). Returns ``dest``."""
    reporter = reporter or NullReporter()
    if not url.lower().startswith(("https://", "http://", "file://")):
        raise VocalkeepError(f"Can't download from {url}: only web addresses are supported.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    try:
        response = _open(url, start, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416 and start:
            # The part file is already complete or no longer matches: start again.
            part.unlink(missing_ok=True)
            start = 0
            try:
                response = _open(url, 0, timeout)
            except (urllib.error.URLError, OSError) as e2:
                raise _network_error(url, e2) from e2
        else:
            raise _network_error(url, e) from e
    except (urllib.error.URLError, OSError) as e:
        raise _network_error(url, e) from e

    with response:
        status = getattr(response, "status", 200)
        content_type = response.headers.get("Content-Type", "")
        if "text/html" in content_type.lower():
            raise VocalkeepError(
                f"The server sent a web page instead of {what}.",
                f"Check that this address works in a browser: {url}",
            )
        total: int | None = None
        if status == 206:
            match = _CONTENT_RANGE.match(response.headers.get("Content-Range", ""))
            if not match or int(match.group(1)) != start:
                raise VocalkeepError(f"The server's reply for {url} didn't make sense; try again.")
            if match.group(3) != "*":
                total = int(match.group(3))
            mode = "ab"
        else:
            start = 0
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            mode = "wb"
        if start:
            reporter.log(f"Carrying on with the download from {_size(start)}")
        done = start
        last_report = 0.0
        try:
            with part.open(mode) as out:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_report > 0.25:
                        last_report = now
                        if total:
                            reporter.progress(
                                stage,
                                done / total,
                                f"Downloaded {_size(done)} of {_size(total)}",
                                bytes=done,
                                totalBytes=total,
                            )
                        else:
                            reporter.progress(stage, 0.0, f"Downloaded {_size(done)}", bytes=done)
        except (OSError, urllib.error.URLError) as e:
            raise VocalkeepError(
                f"The download of {what} stopped at {_size(done)}.",
                "Check the internet connection and run the same command again; "
                "it carries on from where it stopped.",
            ) from e

    size = part.stat().st_size
    if total is not None and size != total:
        raise VocalkeepError(
            f"The download of {what} is incomplete ({_size(size)} of {_size(total)}).",
            "Run the same command again; it carries on from where it stopped.",
        )
    if size == 0:
        part.unlink(missing_ok=True)
        raise VocalkeepError(f"The download of {what} was empty. Try again later.")
    part.replace(dest)
    reporter.progress(stage, 1.0, f"Downloaded {_size(size)}", bytes=size, totalBytes=size)
    return dest


def _network_error(url: str, error: Exception) -> VocalkeepError:
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            return VocalkeepError(
                f"The file isn't at {url} any more (error 404).",
                "Update Vocalkeep, or download the checkpoint yourself and pass it with "
                "--checkpoint PATH.",
            )
        return VocalkeepError(
            f"The server refused the download (error {error.code}).",
            "Try again later, or download the checkpoint yourself and pass --checkpoint PATH.",
        )
    reason = getattr(error, "reason", error)
    return VocalkeepError(
        f"Couldn't connect to download the starting voice ({reason}).",
        "Check the internet connection. On a computer without internet, download the "
        f"checkpoint elsewhere ({url}) and pass it with --checkpoint PATH.",
    )
