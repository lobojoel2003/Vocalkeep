# SPDX-License-Identifier: GPL-3.0-or-later
"""scripts/sync-shared.py keeps the packaged quality.json identical to shared/quality.json."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO

SCRIPT = REPO / "scripts" / "sync-shared.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="not in the repository")


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, check=False
    )


def test_packaged_copy_is_in_sync() -> None:
    proc = _run(SCRIPT, "--check")
    assert proc.returncode == 0, proc.stderr


def test_check_fails_then_sync_fixes(tmp_path: Path) -> None:
    # A copy of the repository layout, so the real files are never touched.
    script = tmp_path / "scripts" / "sync-shared.py"
    script.parent.mkdir()
    shutil.copy(SCRIPT, script)
    shared = tmp_path / "shared" / "quality.json"
    shared.parent.mkdir()
    shared.write_text('{"version": 2}\n')
    copy = tmp_path / "pipeline" / "src" / "vocalkeep" / "data" / "quality.json"
    copy.parent.mkdir(parents=True)
    copy.write_text('{"version": 1}\n')

    proc = _run(script, "--check")
    assert proc.returncode == 1
    assert "differs" in proc.stderr
    proc = _run(script)
    assert proc.returncode == 0
    assert copy.read_text() == shared.read_text()
    assert _run(script, "--check").returncode == 0
    copy.unlink()
    assert _run(script, "--check").returncode == 1
