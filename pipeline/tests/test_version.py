# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import PIPELINE, REPO
from vocalkeep import __version__
from vocalkeep.cli import main


@pytest.mark.skipif(not (REPO / "VERSION").is_file(), reason="not in the repository")
def test_version_matches_repository() -> None:
    assert __version__ == (REPO / "VERSION").read_text(encoding="utf-8").strip()


def test_pyproject_version_matches() -> None:
    text = (PIPELINE / "pyproject.toml").read_text(encoding="utf-8")
    assert f'\nversion = "{__version__}"\n' in text


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"vocalkeep {__version__}"


def test_python_dash_m() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "vocalkeep", "--version"], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == f"vocalkeep {__version__}"
