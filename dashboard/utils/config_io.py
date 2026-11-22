"""Edit values in ``config.yaml`` without losing its comments or layout."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from backtests.config import ConfigError, load_config

_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_]+):(?P<gap>[ \t]*)(?P<value>[^#\n]*?)(?P<pad>[ \t]*)(?P<comment>#.*)?$")


def to_yaml_scalar(value: Any) -> str:
    """Format a Python value as a YAML scalar."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Fixed notation: PyYAML reads forms like "1e-05" as strings, not numbers.
        text = f"{value:.10f}".rstrip("0")
        return text + "0" if text.endswith(".") else text
    if isinstance(value, date):
        return f'"{value.isoformat()}"'
    text = str(value)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*", text) and text.lower() not in {"true", "false", "null", "yes", "no"}:
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_yaml_text(text: str, updates: Mapping[str, Any]) -> str:
    """Replace the values of dotted keys (e.g. ``risk.stop_loss.pips``) in YAML text.

    Comments, blank lines and key order are preserved. Every key must already
    exist in the text.

    Raises:
        KeyError: if a key is not found.
    """
    lines = text.splitlines(keepends=True)
    stack: list[tuple[int, str]] = []
    found: set[str] = set()

    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if not body.strip() or body.lstrip().startswith(("#", "-")):
            continue
        match = _KEY_LINE.match(body)
        if not match:
            continue
        indent = len(match["indent"])
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([key for _, key in stack] + [match["key"]])
        value = match["value"].strip()

        if path in updates:
            new_value = to_yaml_scalar(updates[path])
            rebuilt = f"{match['indent']}{match['key']}: {new_value}"
            if match["comment"]:
                column = body.index(match["comment"])
                rebuilt = rebuilt.ljust(column - 1) + " " + match["comment"]
            newline = line[len(body):] or "\n"
            lines[i] = rebuilt + newline
            found.add(path)
        elif value == "":
            stack.append((indent, match["key"]))

    missing = set(updates) - found
    if missing:
        raise KeyError(f"Keys not found in config file: {', '.join(sorted(missing))}")
    return "".join(lines)


def save_config_values(path: Path, updates: Mapping[str, Any]) -> None:
    """Validate and write ``updates`` into the YAML file atomically.

    The file is only replaced if the result loads as a valid backtest config.

    Raises:
        KeyError: unknown key. ConfigError: the new values are invalid.
    """
    new_text = update_yaml_text(path.read_text(encoding="utf-8"), updates)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".yaml")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(new_text)
        load_config(tmp)  # raises ConfigError if invalid
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


__all__ = ["ConfigError", "save_config_values", "to_yaml_scalar", "update_yaml_text"]
