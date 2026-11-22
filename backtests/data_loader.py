"""Load, combine and validate the yearly OHLCV CSV files produced by the data pipeline."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from data_pipeline.config import Timeframe
from data_pipeline.validator import REQUIRED_COLUMNS, DataValidationError, validate_ohlcv

log = logging.getLogger(__name__)

PRICE_COLUMNS = ["Open", "High", "Low", "Close"]


class DataLoadError(RuntimeError):
    """No usable market data could be loaded."""


@dataclass
class LoadReport:
    """What was loaded and what was cleaned up on the way."""

    data_dir: Path
    symbol: str
    files_loaded: list[Path] = field(default_factory=list)
    files_failed: list[tuple[Path, str]] = field(default_factory=list)
    rows_read: int = 0
    rows_used: int = 0
    null_rows_removed: int = 0
    invalid_rows_removed: int = 0
    duplicates_removed: int = 0
    missing_periods: int = 0
    timeframe: Timeframe = Timeframe.DAILY
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None

    @property
    def warnings(self) -> list[str]:
        notes = [f"Skipped {p.name}: {reason}" for p, reason in self.files_failed]
        if self.null_rows_removed:
            notes.append(f"{self.null_rows_removed} row(s) with missing values removed")
        if self.invalid_rows_removed:
            notes.append(f"{self.invalid_rows_removed} row(s) violating OHLC rules removed")
        if self.duplicates_removed:
            notes.append(f"{self.duplicates_removed} duplicate timestamp(s) removed")
        if self.missing_periods:
            notes.append(f"{self.missing_periods} expected trading {self.timeframe.unit}(s) missing from the data")
        return notes


def discover_files(data_dir: Path, symbol: str) -> list[Path]:
    """Yearly files named ``<SYMBOL>_<YYYY>.csv``, oldest first."""
    pattern = re.compile(rf"^{re.escape(symbol)}_(\d{{4}})\.csv$", re.IGNORECASE)
    files = [p for p in data_dir.glob(f"{symbol}_*.csv") if pattern.match(p.name)]
    return sorted(files, key=lambda p: int(pattern.match(p.name).group(1)))  # type: ignore[union-attr]


def load_market_data(
    data_dir: Path,
    symbol: str,
    start: date | None = None,
    end: date | None = None,
) -> tuple[pd.DataFrame, LoadReport]:
    """Load every yearly file for ``symbol``, combine and validate them.

    Corrupted or unreadable files are skipped and reported rather than aborting
    the run. Rows are validated with the same rules as the download pipeline
    (OHLC consistency, missing values, duplicates).

    Returns:
        A frame indexed by UTC ``Date`` with ``Open, High, Low, Close, Volume``,
        sorted ascending, and a :class:`LoadReport`.

    Raises:
        DataLoadError: if the folder has no usable files or no rows remain.
    """
    report = LoadReport(data_dir=data_dir, symbol=symbol)
    if not data_dir.is_dir():
        raise DataLoadError(
            f"Data folder not found: {data_dir}. Download data first with: python -m data_pipeline"
        )

    files = discover_files(data_dir, symbol)
    if not files:
        raise DataLoadError(
            f"No {symbol}_<YEAR>.csv files in {data_dir}. Download data first with: python -m data_pipeline"
        )

    frames: list[pd.DataFrame] = []
    for path in files:
        try:
            frame = pd.read_csv(path)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            _skip(report, path, f"unreadable ({type(exc).__name__}: {exc})")
            continue
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            _skip(report, path, f"missing column(s) {', '.join(missing)}")
            continue
        if frame.empty:
            _skip(report, path, "no rows")
            continue
        frames.append(frame.loc[:, list(REQUIRED_COLUMNS)])
        report.files_loaded.append(path)
        log.debug("Loaded %d row(s) from %s", len(frame), path)

    if not frames:
        raise DataLoadError(f"None of the {len(files)} file(s) in {data_dir} could be used; see the log for details")

    combined = pd.concat(frames, ignore_index=True)
    report.rows_read = len(combined)
    report.timeframe = _infer_timeframe(combined["Date"])

    try:
        clean, validation = validate_ohlcv(combined, report.timeframe)
    except DataValidationError as exc:
        raise DataLoadError(str(exc)) from exc

    report.null_rows_removed = validation.null_rows_removed
    report.invalid_rows_removed = validation.invalid_rows_removed
    report.duplicates_removed = validation.duplicates_removed
    report.missing_periods = validation.missing_periods

    if start is not None:
        clean = clean.loc[clean["Date"] >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        clean = clean.loc[clean["Date"] < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    if clean.empty:
        raise DataLoadError(f"No {symbol} data between {start or 'the start'} and {end or 'the end'}")

    data = clean.set_index("Date")
    report.rows_used = len(data)
    report.start, report.end = data.index[0], data.index[-1]
    log.info(
        "Loaded %s: %d file(s), %d row(s) used (%s -> %s), %d file(s) skipped",
        symbol, len(report.files_loaded), report.rows_used, report.start, report.end, len(report.files_failed),
    )
    return data, report


def _skip(report: LoadReport, path: Path, reason: str) -> None:
    log.warning("Skipping %s: %s", path, reason)
    report.files_failed.append((path, reason))


def _infer_timeframe(dates: pd.Series) -> Timeframe:
    parsed = pd.to_datetime(dates, utc=True, errors="coerce", format="mixed").dropna().sort_values()
    if len(parsed) < 2:
        return Timeframe.DAILY
    return Timeframe.DAILY if parsed.diff().median() >= pd.Timedelta(hours=12) else Timeframe.HOURLY
