"""Consistent number formatting for KPI cards, tables and chart labels."""

from __future__ import annotations

import math

import pandas as pd

from backtests.performance import format_duration


def money(value: float | None, decimals: int = 2) -> str:
    """``-$1,234.56`` style; ``n/a`` for missing values."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.{decimals}f}"


def signed_money(value: float, decimals: int = 2) -> str:
    return ("+" if value > 0 else "") + money(value, decimals)


def pct(value: float | None, decimals: int = 2, signed: bool = False) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"


def ratio(value: float | None, decimals: int = 2) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    if math.isinf(value):
        return "∞"
    return f"{value:.{decimals}f}"


def integer(value: int | float) -> str:
    return f"{int(value):,}"


def duration(value: pd.Timedelta | None) -> str:
    return format_duration(value)


def date(value: pd.Timestamp | None, fmt: str = "%d %b %Y") -> str:
    if value is None or pd.isna(value):
        return "-"
    return pd.Timestamp(value).strftime(fmt)


def tone(value: float, neutral_band: float = 0.0) -> str:
    """``positive`` / ``negative`` / ``neutral`` for KPI badges."""
    if value is None or math.isnan(value) or abs(value) <= neutral_band:
        return "neutral"
    return "positive" if value > 0 else "negative"
