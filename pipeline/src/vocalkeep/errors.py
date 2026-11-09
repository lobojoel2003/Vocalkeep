# SPDX-License-Identifier: GPL-3.0-or-later
"""Errors meant for people, not programmers.

Anything that can go wrong because of a file, a missing program or a choice the person made is
raised as :class:`VocalkeepError`. The command-line tool prints its message (and hint) without a
traceback and exits with status 1.
"""

from __future__ import annotations


class VocalkeepError(Exception):
    """A problem the person can understand and usually fix.

    ``message`` says what happened in plain words. ``hint`` (optional) says what to do next.
    """

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        if self.hint:
            return f"{self.message}\n{self.hint}"
        return self.message
