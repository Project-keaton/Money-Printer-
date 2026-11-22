"""Data validation and cleaning for OHLCV candles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from data_pipeline.config import Timeframe

log = logging.getLogger(__name__)

PRICE_COLUMNS: tuple[str, ...] = ("Open", "High", "Low", "Close")
REQUIRED_COLUMNS: tuple[str, ...] = ("Date", *PRICE_COLUMNS, "Volume")

#: (month, day) pairs on which the forex market is effectively closed.
MARKET_HOLIDAYS: frozenset[tuple[int, int]] = frozenset({(1, 1), (12, 25)})

#: A single-candle move bigger than this is reported as a possible bad tick.
MAX_ABS_RETURN: float = 0.10


class DataValidationError(ValueError):
    """The data cannot be validated at all (e.g. required columns are missing)."""


@dataclass(frozen=True, slots=True)
class GapWarning:
    """A run of consecutive trading periods with no data."""

    start: pd.Timestamp
    end: pd.Timestamp
    missing_periods: int
    timeframe: Timeframe

    def __str__(self) -> str:
        fmt = self.timeframe.date_format
        unit = self.timeframe.unit + ("s" if self.missing_periods != 1 else "")
        span = f"{self.start:{fmt}}" if self.start == self.end else f"{self.start:{fmt}} -> {self.end:{fmt}}"
        return f"Missing {self.missing_periods} trading {unit}: {span}"


@dataclass
class ValidationReport:
    input_rows: int = 0
    output_rows: int = 0
    null_rows_removed: int = 0
    invalid_rows_removed: int = 0
    duplicates_removed: int = 0
    gaps: list[GapWarning] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def missing_periods(self) -> int:
        return sum(g.missing_periods for g in self.gaps)


def validate_ohlcv(df: pd.DataFrame, timeframe: Timeframe) -> tuple[pd.DataFrame, ValidationReport]:
    """Clean and validate candles.

    Steps:
        1. Check that all required columns are present.
        2. Parse dates as UTC and coerce prices/volume to numbers.
        3. Drop rows with a missing date or price; fill missing volume with 0.
        4. Drop rows that break OHLC rules (non-positive price, High below
           Open/Close/Low, Low above Open/Close/High, negative volume).
        5. Sort by date and drop duplicate timestamps (keeping the last value).
        6. Report suspicious price jumps and gaps in expected trading periods.

    Returns:
        The cleaned frame (sorted, unique dates) and a :class:`ValidationReport`.

    Raises:
        DataValidationError: if required columns are missing.
    """
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise DataValidationError(f"Data is missing required column(s): {', '.join(missing_columns)}")

    report = ValidationReport(input_rows=len(df))
    out = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    out["Date"] = pd.to_datetime(out["Date"], utc=True, errors="coerce", format="mixed")
    for column in (*PRICE_COLUMNS, "Volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype(float)

    # 3. Missing values
    null_mask = out[["Date", *PRICE_COLUMNS]].isna().any(axis=1)
    report.null_rows_removed = int(null_mask.sum())
    out = out.loc[~null_mask]
    out["Volume"] = out["Volume"].fillna(0.0)

    # 4. OHLC consistency
    invalid = (
        (out[list(PRICE_COLUMNS)] <= 0).any(axis=1)
        | (out["High"] < out[["Open", "Close", "Low"]].max(axis=1))
        | (out["Low"] > out[["Open", "Close", "High"]].min(axis=1))
        | (out["Volume"] < 0)
    )
    report.invalid_rows_removed = int(invalid.sum())
    out = out.loc[~invalid]

    # 5. Ordering and duplicates
    out = out.sort_values("Date", kind="stable")
    duplicated = out.duplicated(subset="Date", keep="last")
    report.duplicates_removed = int(duplicated.sum())
    out = out.loc[~duplicated].reset_index(drop=True)

    # 6. Suspicious moves and gaps
    returns = out["Close"].pct_change().abs()
    for ts in out.loc[returns > MAX_ABS_RETURN, "Date"]:
        report.warnings.append(f"Price moved more than {MAX_ABS_RETURN:.0%} in one candle at {ts:{timeframe.date_format}}")
    report.gaps = find_gaps(out["Date"], timeframe)
    report.output_rows = len(out)

    log.info(
        "Validation: %d in, %d out (%d null, %d invalid, %d duplicate removed); %d gap(s), %d missing %s(s)",
        report.input_rows, report.output_rows, report.null_rows_removed, report.invalid_rows_removed,
        report.duplicates_removed, len(report.gaps), report.missing_periods, timeframe.unit,
    )
    for gap in report.gaps:
        log.warning(str(gap))
    for warning in report.warnings:
        log.warning(warning)
    return out, report


def expected_trading_periods(start: pd.Timestamp, end: pd.Timestamp, timeframe: Timeframe) -> pd.DatetimeIndex:
    """Timestamps in ``[start, end]`` when the forex market is normally open.

    Daily: Monday-Friday. Hourly: from Sunday 22:00 to Friday 21:00 UTC (the
    window that is open all year regardless of daylight saving time).
    1 January and 25 December are excluded in both cases.
    """
    periods = pd.date_range(start, end, freq=timeframe.pandas_freq)
    dow = periods.day_of_week
    if timeframe is Timeframe.DAILY:
        is_open = dow < 5
    else:
        hour = periods.hour
        is_closed = (dow == 5) | ((dow == 4) & (hour >= 21)) | ((dow == 6) & (hour < 22))
        is_open = ~is_closed
    holiday = pd.Index(list(zip(periods.month, periods.day))).isin(MARKET_HOLIDAYS)
    return periods[is_open & ~holiday]


def find_gaps(dates: pd.Series, timeframe: Timeframe) -> list[GapWarning]:
    """Group missing expected trading periods between the first and last date into ranges."""
    if len(dates) < 2:
        return []
    present = pd.DatetimeIndex(dates)
    present = present.normalize() if timeframe is Timeframe.DAILY else present.floor("h")

    missing = expected_trading_periods(present.min(), present.max(), timeframe).difference(present)
    if missing.empty:
        return []

    series = missing.to_series()
    group_ids = (series.diff() != timeframe.step).cumsum()
    return [
        GapWarning(group.iloc[0], group.iloc[-1], len(group), timeframe)
        for _, group in series.groupby(group_ids)
    ]
