# SPDX-License-Identifier: GPL-3.0-or-later
"""Progress reporting, for people (text) and for the desktop app (JSON lines).

With ``--progress json`` every event is one JSON object on its own line of standard output::

    {"event": "stage", "stage": "prepare", "message": "Getting your recordings ready"}
    {"event": "progress", "stage": "train", "fraction": 0.42, "message": "Epoch 2300 of 3164"}
    {"event": "log", "message": "..."}
    {"event": "log", "level": "warning", "message": "..."}
    {"event": "done", "voice": "/abs/path"}
    {"event": "error", "message": "...", "hint": "..."}

Text mode prints the same information as short, friendly lines.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Literal, TextIO

Mode = Literal["text", "json"]

_STAGE_TITLES = {
    "check": "Checking recordings",
    "prepare": "Getting the recordings ready",
    "download": "Downloading the starting voice",
    "train": "Training",
    "export": "Making the voice file",
    "package": "Packaging",
    "install": "Installing",
}


class Reporter:
    """Sends progress events to a stream as text or JSON lines."""

    def __init__(
        self,
        mode: Mode = "text",
        stream: TextIO | None = None,
        *,
        min_interval: float = 0.5,
    ) -> None:
        self.mode: Mode = mode
        self._stream = stream
        self._min_interval = min_interval
        self._last_progress_time = 0.0
        self._last_progress_key: tuple[str, int] | None = None
        self._last_message: str | None = None

    @property
    def stream(self) -> TextIO:
        # Looked up late so tests that swap sys.stdout (capsys) see the output.
        return self._stream if self._stream is not None else sys.stdout

    @property
    def is_json(self) -> bool:
        return self.mode == "json"

    def _emit(self, event: dict[str, Any]) -> None:
        self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.stream.flush()

    def _print(self, line: str) -> None:
        self.stream.write(line + "\n")
        self.stream.flush()

    def stage(self, stage: str, message: str | None = None) -> None:
        """A new step has started."""
        text = message or _STAGE_TITLES.get(stage, stage.capitalize())
        self._last_progress_key = None
        if self.is_json:
            self._emit({"event": "stage", "stage": stage, "message": text})
        else:
            self._print(f"\n== {text}")

    def progress(self, stage: str, fraction: float, message: str = "", **extra: Any) -> None:
        """How far the current step has come, from 0 to 1. ``extra`` goes into the JSON event."""
        fraction = min(1.0, max(0.0, float(fraction)))
        now = time.monotonic()
        if self.is_json:
            # Every distinct message is sent, but not more often than the app can use.
            key = (message, round(fraction * 100000))
            if key == self._last_progress_key:
                return
            if fraction < 1.0 and now - self._last_progress_time < self._min_interval / 5:
                return
            self._last_progress_key = (message, round(fraction * 100000))
            self._last_progress_time = now
            event: dict[str, Any] = {
                "event": "progress",
                "stage": stage,
                "fraction": round(fraction, 4),
                "message": message,
            }
            event.update(extra)
            self._emit(event)
            return
        percent = int(fraction * 100)
        key_text = (stage, percent)
        if key_text == self._last_progress_key:
            return
        if fraction < 1.0 and now - self._last_progress_time < self._min_interval:
            return
        self._last_progress_key = key_text
        self._last_progress_time = now
        suffix = f"  {message}" if message else ""
        self._print(f"   [{percent:3d}%]{suffix}")

    def log(self, message: str) -> None:
        """Something worth showing, but not a step of its own."""
        if self.is_json:
            self._emit({"event": "log", "message": message})
        else:
            self._print(f"   {message}")

    def warn(self, message: str) -> None:
        """Something the person should know about. It doesn't stop the work."""
        if self.is_json:
            self._emit({"event": "log", "level": "warning", "message": message})
        else:
            self._print(f"   Note: {message}")

    def done(self, message: str | None = None, **fields: Any) -> None:
        """The work finished. ``fields`` (e.g. ``voice=...``) go into the JSON event."""
        if self.is_json:
            event: dict[str, Any] = {"event": "done"}
            event.update(fields)
            if message:
                event["message"] = message
            self._emit(event)
        elif message:
            self._print(f"\n{message}")

    def error(self, message: str, hint: str | None = None) -> None:
        """The work stopped. In text mode the CLI prints errors to stderr itself."""
        if self.is_json:
            event: dict[str, Any] = {"event": "error", "message": message}
            if hint:
                event["hint"] = hint
            self._emit(event)


class NullReporter(Reporter):
    """Reports nothing. Used by library calls and tests that don't care about progress."""

    def __init__(self) -> None:
        super().__init__("text")

    def _emit(self, event: dict[str, Any]) -> None:
        return

    def _print(self, line: str) -> None:
        return
