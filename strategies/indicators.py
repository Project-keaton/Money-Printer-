"""Technical indicators implemented with pandas (no look-ahead: each value uses past data only)."""

from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    _check_period(period)
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average (span = ``period``), NaN until ``period`` values exist."""
    _check_period(period)
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing (0-100)."""
    _check_period(period)
    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    value = 100.0 - 100.0 / (1.0 + rs)
    # No losses in the window -> RSI 100; no movement at all -> neutral 50.
    value = value.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    value = value.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return value


def true_range(data: pd.DataFrame) -> pd.Series:
    """Greatest of high-low, |high - previous close| and |low - previous close|."""
    prev_close = data["Close"].shift(1)
    ranges = pd.concat(
        [data["High"] - data["Low"], (data["High"] - prev_close).abs(), (data["Low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using Wilder's smoothing."""
    _check_period(period)
    return true_range(data).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def crossed_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True on bars where ``a`` moves from <= ``b`` to > ``b``."""
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift(1) <= b_prev)


def crossed_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True on bars where ``a`` moves from >= ``b`` to < ``b``."""
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift(1) >= b_prev)


def _check_period(period: int) -> None:
    if int(period) != period or period < 1:
        raise ValueError(f"Indicator period must be a positive integer, got {period}")
