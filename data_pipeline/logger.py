"""Logging setup: rotating log files in ``logs/`` plus concise console output."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_BACKUP_COUNT = 5
_HANDLER_TAG = "_forexbot_pipeline_handler"


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    *,
    console_level: int = logging.WARNING,
    file_prefix: str = "data_download",
) -> Path:
    """Configure the root logger.

    * ``logs/<file_prefix>.log``        - everything at ``level`` and up
    * ``logs/<file_prefix>_errors.log`` - errors only, for quick triage
    * console (stderr)                  - warnings and errors only, so the progress bar stays readable

    Calling this more than once replaces the handlers instead of duplicating them.

    Returns:
        Path of the main download log file.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_TAG, False):
            root.removeHandler(handler)
            handler.close()

    download_log = log_dir / f"{file_prefix}.log"
    handlers: list[logging.Handler] = [
        _file_handler(download_log, level, formatter),
        _file_handler(log_dir / f"{file_prefix}_errors.log", logging.ERROR, formatter),
    ]

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(max(console_level, logging.getLevelName(level)))
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    handlers.append(console)

    for handler in handlers:
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)

    # Third-party libraries are noisy at INFO/DEBUG.
    for noisy in ("urllib3", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return download_log


def _file_handler(path: Path, level: int | str, formatter: logging.Formatter) -> logging.Handler:
    handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler
