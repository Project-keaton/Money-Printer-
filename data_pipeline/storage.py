"""Writing yearly CSV files and verifying them afterwards."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from data_pipeline.config import Timeframe
from data_pipeline.validator import PRICE_COLUMNS, REQUIRED_COLUMNS

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class YearFile:
    year: int
    path: Path
    rows: int
    first: pd.Timestamp
    last: pd.Timestamp


def yearly_filename(symbol: str, year: int) -> str:
    """E.g. ``EURUSD_2016.csv``."""
    return f"{symbol}_{year}.csv"


def write_yearly_csv(df: pd.DataFrame, data_dir: Path, symbol: str, timeframe: Timeframe) -> list[YearFile]:
    """Split validated candles by calendar year (UTC) and write one CSV per year.

    The data folder is created if needed. Each file is written to a temporary
    file first and then renamed, so an interrupted run never leaves a
    half-written CSV behind. Existing files for the same year are replaced.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    files: list[YearFile] = []
    if df.empty:
        return files

    for year, group in df.groupby(df["Date"].dt.year, sort=True):
        path = data_dir / yearly_filename(symbol, int(year))
        out = group.loc[:, list(REQUIRED_COLUMNS)].copy()
        out["Date"] = out["Date"].dt.strftime(timeframe.date_format)
        out[list(PRICE_COLUMNS)] = out[list(PRICE_COLUMNS)].round(6)
        out["Volume"] = out["Volume"].round(2)
        _atomic_write_csv(out, path)

        files.append(YearFile(int(year), path, len(out), group["Date"].iloc[0], group["Date"].iloc[-1]))
        log.info("Wrote %d record(s) to %s", len(out), path)
    return files


def _atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False, lineterminator="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


@dataclass
class FileCheck:
    year: int
    path: Path
    exists: bool = False
    rows: int = 0
    first: str = ""
    last: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exists and not self.problems


def load_yearly_csv(data_dir: Path, symbol: str, years: Iterable[int]) -> pd.DataFrame:
    """Load existing yearly CSV files into one frame with UTC ``Date`` values.

    Missing years are skipped (and logged); returns an empty frame if none exist.
    """
    frames = []
    for year in years:
        path = data_dir / yearly_filename(symbol, year)
        if not path.is_file():
            log.warning("Cannot load %s: file not found", path)
            continue
        frames.append(pd.read_csv(path))
    if not frames:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], utc=True, format="mixed")
    return df


def verify_yearly_files(
    data_dir: Path, symbol: str, years: Iterable[int], *, weekdays_only: bool = False
) -> list[FileCheck]:
    """Check that a well-formed CSV exists for every year in ``years``.

    With ``weekdays_only`` the files must also contain no Saturday/Sunday rows.
    """
    return [_verify_file(data_dir / yearly_filename(symbol, year), year, weekdays_only) for year in years]


def _verify_file(path: Path, year: int, weekdays_only: bool = False) -> FileCheck:
    check = FileCheck(year=year, path=path, exists=path.is_file())
    if not check.exists:
        check.problems.append("file not found")
        return check

    try:
        df = pd.read_csv(path)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        check.problems.append(f"unreadable: {exc}")
        return check

    check.rows = len(df)
    if list(df.columns) != list(REQUIRED_COLUMNS):
        check.problems.append(f"unexpected columns {list(df.columns)}")
        return check
    if df.empty:
        check.problems.append("no records")
        return check

    dates = pd.to_datetime(df["Date"], errors="coerce", format="mixed")
    check.first, check.last = str(df["Date"].iloc[0]), str(df["Date"].iloc[-1])
    if dates.isna().any():
        check.problems.append(f"{int(dates.isna().sum())} unparseable date(s)")
    if (dates.dt.year != year).any():
        check.problems.append("contains dates from another year")
    if dates.duplicated().any():
        check.problems.append(f"{int(dates.duplicated().sum())} duplicate date(s)")
    if not dates.is_monotonic_increasing:
        check.problems.append("dates are not in ascending order")
    if df[list(PRICE_COLUMNS)].isna().any().any():
        check.problems.append("missing price values")
    if weekdays_only and (dates.dt.day_of_week >= 5).any():
        check.problems.append(f"{int((dates.dt.day_of_week >= 5).sum())} weekend row(s)")
    return check
