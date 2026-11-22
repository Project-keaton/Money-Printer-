"""Data-quality scan of the yearly CSV files (raw contents, before any cleaning)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from backtests.data_loader import discover_files
from data_pipeline.config import Timeframe
from data_pipeline.validator import PRICE_COLUMNS, REQUIRED_COLUMNS, GapWarning, find_gaps


@dataclass
class FileQuality:
    year: int
    file: str
    rows: int = 0
    first: str = ""
    last: str = ""
    missing_values: int = 0
    rows_with_missing: int = 0
    duplicates: int = 0
    invalid_ohlc: int = 0
    weekend_rows: int = 0
    size_kb: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "OK" if not self.problems else "Issues"


@dataclass
class DatasetQuality:
    directory: Path
    files: list[FileQuality]
    gaps: list[GapWarning]

    @property
    def total_rows(self) -> int:
        return sum(f.rows for f in self.files)

    @property
    def years(self) -> list[int]:
        return [f.year for f in self.files if f.rows]

    @property
    def missing_values(self) -> int:
        return sum(f.missing_values for f in self.files)

    @property
    def duplicates(self) -> int:
        return sum(f.duplicates for f in self.files)

    @property
    def invalid_ohlc(self) -> int:
        return sum(f.invalid_ohlc for f in self.files)

    @property
    def missing_trading_days(self) -> int:
        return sum(g.missing_periods for g in self.gaps)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "Year": f.year, "File": f.file, "Rows": f.rows, "First": f.first, "Last": f.last,
                "Missing Values": f.missing_values, "Duplicates": f.duplicates, "Invalid OHLC": f.invalid_ohlc,
                "Weekend Rows": f.weekend_rows, "Size (KB)": round(f.size_kb, 1),
                "Status": f.status, "Problems": "; ".join(f.problems),
            }
            for f in self.files
        ])


def scan_dataset(directory: Path, symbol: str) -> DatasetQuality:
    """Inspect every ``<SYMBOL>_<YEAR>.csv`` in ``directory`` without modifying it."""
    files: list[FileQuality] = []
    all_dates: list[pd.Series] = []
    for path in discover_files(directory, symbol) if directory.is_dir() else []:
        quality = FileQuality(year=int(path.stem.split("_")[-1]), file=path.name, size_kb=path.stat().st_size / 1024)
        files.append(quality)
        try:
            df = pd.read_csv(path)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            quality.problems.append(f"unreadable: {type(exc).__name__}")
            continue

        missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing_columns:
            quality.problems.append(f"missing columns: {', '.join(missing_columns)}")
            continue

        quality.rows = len(df)
        quality.missing_values = int(df[list(REQUIRED_COLUMNS)].isna().sum().sum())
        quality.rows_with_missing = int(df[list(REQUIRED_COLUMNS)].isna().any(axis=1).sum())
        dates = pd.to_datetime(df["Date"], errors="coerce", format="mixed")
        quality.duplicates = int(dates.dropna().duplicated().sum())
        prices = df[list(PRICE_COLUMNS)].apply(pd.to_numeric, errors="coerce")
        quality.invalid_ohlc = int((
            (prices <= 0).any(axis=1)
            | (prices["High"] < prices[["Open", "Close", "Low"]].max(axis=1))
            | (prices["Low"] > prices[["Open", "Close", "High"]].min(axis=1))
        ).sum())
        quality.weekend_rows = int((dates.dt.day_of_week >= 5).sum())
        if quality.rows:
            quality.first, quality.last = str(df["Date"].iloc[0]), str(df["Date"].iloc[-1])

        if quality.missing_values:
            quality.problems.append(f"{quality.missing_values} missing value(s)")
        if quality.duplicates:
            quality.problems.append(f"{quality.duplicates} duplicate date(s)")
        if quality.invalid_ohlc:
            quality.problems.append(f"{quality.invalid_ohlc} invalid OHLC row(s)")
        if dates.isna().any():
            quality.problems.append(f"{int(dates.isna().sum())} unparseable date(s)")
        all_dates.append(dates.dropna())

    gaps: list[GapWarning] = []
    if all_dates:
        combined = pd.concat(all_dates).drop_duplicates().sort_values()
        gaps = find_gaps(pd.Series(combined.dt.tz_localize("UTC") if combined.dt.tz is None else combined),
                         Timeframe.DAILY)
    return DatasetQuality(directory=directory, files=files, gaps=gaps)


def latest_download_report(reports_dir: Path, symbol: str) -> Path | None:
    reports = sorted(reports_dir.glob(f"{symbol}_download_summary_*.txt"))
    return reports[-1] if reports else None
