"""Post-processing transforms applied to validated candles."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from data_pipeline.validator import REQUIRED_COLUMNS

log = logging.getLogger(__name__)

_SATURDAY, _SUNDAY = 5, 6


@dataclass
class FoldReport:
    """What :func:`fold_sundays_into_monday` changed."""

    input_rows: int = 0
    output_rows: int = 0
    sundays_folded: int = 0
    #: Sundays with no Monday candle to merge into (dropped, listed by date).
    unmatched_sundays: list[str] = field(default_factory=list)
    saturdays_dropped: int = 0


def fold_sundays_into_monday(df: pd.DataFrame) -> tuple[pd.DataFrame, FoldReport]:
    """Merge each Sunday daily candle into the following Monday candle.

    Forex reopens on Sunday evening (UTC), so UTC-midnight daily candles include
    a short Sunday session. Folding it into Monday gives one candle per trading
    day, Monday to Friday:

    * Open   = Sunday open (the first price of the trading week)
    * High   = max(Sunday high, Monday high)
    * Low    = min(Sunday low, Monday low)
    * Close  = Monday close
    * Volume = Sunday volume + Monday volume
    * Date   = Monday

    A Sunday with no Monday candle (e.g. data ends on Sunday, or Monday is
    missing) cannot be folded and is dropped; such dates are listed in the
    report. Saturday candles are not expected and are dropped too.

    Args:
        df: validated daily candles with UTC-midnight ``Date`` values and unique dates.

    Returns:
        A new Monday-Friday frame sorted by date, and a :class:`FoldReport`.
    """
    report = FoldReport(input_rows=len(df))
    if df.empty:
        return df.copy(), report

    frame = df.loc[:, list(REQUIRED_COLUMNS)].sort_values("Date").reset_index(drop=True)
    dow = frame["Date"].dt.day_of_week

    report.saturdays_dropped = int((dow == _SATURDAY).sum())
    sundays = frame.loc[dow == _SUNDAY]
    weekdays = frame.loc[dow < _SATURDAY].set_index("Date")

    # Index each Sunday by the Monday it belongs to.
    sundays = sundays.set_index(sundays["Date"] + pd.Timedelta(days=1)).drop(columns="Date")
    matched = sundays.index.isin(weekdays.index)
    report.unmatched_sundays = [f"{(ts - pd.Timedelta(days=1)):%Y-%m-%d}" for ts in sundays.index[~matched]]

    sun = sundays.loc[matched]
    mondays = sun.index
    weekdays.loc[mondays, "Open"] = sun["Open"]
    weekdays.loc[mondays, "High"] = weekdays.loc[mondays, "High"].combine(sun["High"], max)
    weekdays.loc[mondays, "Low"] = weekdays.loc[mondays, "Low"].combine(sun["Low"], min)
    weekdays.loc[mondays, "Volume"] = weekdays.loc[mondays, "Volume"] + sun["Volume"]
    # Close stays Monday's close.
    report.sundays_folded = int(matched.sum())

    out = weekdays.reset_index()[list(REQUIRED_COLUMNS)]
    report.output_rows = len(out)

    log.info(
        "Folded %d Sunday candle(s) into Monday: %d -> %d rows (%d unmatched Sunday(s), %d Saturday(s) dropped)",
        report.sundays_folded, report.input_rows, report.output_rows,
        len(report.unmatched_sundays), report.saturdays_dropped,
    )
    for day in report.unmatched_sundays:
        log.warning("Sunday %s has no following Monday candle; it was dropped from the weekday dataset", day)
    return out, report
