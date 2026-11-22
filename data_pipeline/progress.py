"""Dependency-free console progress bar."""

from __future__ import annotations

import sys
import time
from types import TracebackType
from typing import Self, TextIO


def format_duration(seconds: float) -> str:
    """Format seconds as ``MM:SS`` or ``H:MM:SS``."""
    seconds = int(max(seconds, 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class ProgressBar:
    """Single-line progress bar with elapsed time and ETA.

    On an interactive terminal the line is redrawn in place; when output is
    redirected (e.g. to a file or a service log) each update is a new line.
    """

    def __init__(self, total: int, description: str = "", *, width: int = 30, stream: TextIO | None = None) -> None:
        self.total = max(total, 0)
        self.description = description
        self.width = width
        self.count = 0
        self.stream = stream or sys.stderr
        self._started = time.monotonic()
        self._interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._last_len = 0
        self._render()

    def update(self, n: int = 1, status: str = "") -> None:
        """Advance the bar by ``n`` steps and show an optional status message."""
        self.count = min(self.count + n, self.total)
        self._render(status)

    def close(self) -> None:
        if self._interactive:
            self.stream.write("\n")
        self.stream.flush()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _render(self, status: str = "") -> None:
        fraction = self.count / self.total if self.total else 1.0
        filled = int(self.width * fraction)
        bar = "#" * filled + "-" * (self.width - filled)

        elapsed = time.monotonic() - self._started
        if self.count and self.count < self.total:
            eta = format_duration(elapsed / self.count * (self.total - self.count))
        elif self.count >= self.total:
            eta = "00:00"
        else:
            eta = "--:--"

        line = (
            f"{self.description} [{bar}] {self.count}/{self.total} {fraction:4.0%}"
            f" | elapsed {format_duration(elapsed)} | ETA {eta}"
        )
        if status:
            line += f" | {status}"

        if self._interactive:
            padding = " " * max(0, self._last_len - len(line))
            self.stream.write(f"\r{line}{padding}")
            self._last_len = len(line)
        else:
            self.stream.write(line + "\n")
        self.stream.flush()
