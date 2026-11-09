# SPDX-License-Identifier: GPL-3.0-or-later
"""Every text file is read and written as UTF-8.

Windows defaults to the system code page, which turns names like "Zoë" into "Zo�". This test
fails if a ``read_text``/``write_text`` call anywhere in the package or its tests leaves the
encoding out.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*(ROOT / "src").rglob("*.py"), *(ROOT / "tests").rglob("*.py")])


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_text_io_names_its_encoding(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"read_text", "write_text"}
        and not any(k.arg == "encoding" for k in node.keywords)
    ]
    assert not missing, f"{path.name}: lines {missing} read or write text without encoding="
