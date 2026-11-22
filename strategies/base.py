"""Strategy interface shared by every trading strategy.

A strategy turns market data into **signals**. It never places orders, sizes
positions or touches account state; the backtest engine (and later the live
trader) does that. This keeps strategies pure, easy to test, and identical in
backtesting and live trading.

Signal contract
---------------
``generate_signals(data)`` receives a frame indexed by UTC timestamp with
``Open, High, Low, Close, Volume`` and returns either:

* a ``pd.Series`` of ``1`` (go long), ``-1`` (go short) or ``0`` (no new trade), or
* a ``pd.DataFrame`` with a ``signal`` column (same values) and optionally:

  ========================  ====================================================
  ``exit_long``  (bool)     close open long trades
  ``exit_short`` (bool)     close open short trades
  ``stop_distance``         stop-loss distance in price units (overrides config)
  ``target_distance``       take-profit distance in price units (overrides config)
  ========================  ====================================================

The value at bar *t* may only use information available at the **close** of bar
*t*. The engine executes it at the **open of bar t+1**, so a strategy that
follows this rule cannot look ahead.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

import pandas as pd

LONG, SHORT, FLAT = 1, -1, 0
SIGNAL_COLUMN = "signal"
OPTIONAL_BOOL_COLUMNS = ("exit_long", "exit_short")
OPTIONAL_DISTANCE_COLUMNS = ("stop_distance", "target_distance")


class StrategyError(ValueError):
    """A strategy is misconfigured or produced invalid signals."""


class Strategy(ABC):
    """Base class for all strategies."""

    #: Identifier used in ``config.yaml`` (``strategy.active``).
    name: ClassVar[str] = "strategy"

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = dict(params)

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame | pd.Series:
        """Return signals aligned to ``data.index`` (see module docstring)."""

    @property
    def warmup_bars(self) -> int:
        """Bars needed before the first meaningful signal (informational)."""
        return 0

    def describe(self) -> str:
        params = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({params})"

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.describe()}>"


def normalise_signals(raw: pd.DataFrame | pd.Series, index: pd.Index) -> pd.DataFrame:
    """Validate strategy output and return a frame with every signal column present.

    Raises:
        StrategyError: if the output is misaligned or contains invalid values.
    """
    if isinstance(raw, pd.Series):
        frame = raw.to_frame(SIGNAL_COLUMN)
    elif isinstance(raw, pd.DataFrame):
        if SIGNAL_COLUMN not in raw.columns:
            raise StrategyError(f"Strategy output is missing the '{SIGNAL_COLUMN}' column")
        frame = raw.copy()
    else:
        raise StrategyError(f"Strategy must return a Series or DataFrame, got {type(raw).__name__}")

    if len(frame) != len(index) or not frame.index.equals(index):
        raise StrategyError("Strategy output must have exactly the same index as the input data")

    signal = pd.to_numeric(frame[SIGNAL_COLUMN], errors="coerce").fillna(FLAT)
    invalid = ~signal.isin([LONG, SHORT, FLAT])
    if invalid.any():
        raise StrategyError(
            f"Signals must be 1, -1 or 0; found {sorted(signal[invalid].unique().tolist())[:5]}"
        )

    out = pd.DataFrame(index=index)
    out[SIGNAL_COLUMN] = signal.astype(int)
    for column in OPTIONAL_BOOL_COLUMNS:
        out[column] = frame[column].fillna(False).astype(bool) if column in frame else False
    for column in OPTIONAL_DISTANCE_COLUMNS:
        values = pd.to_numeric(frame[column], errors="coerce") if column in frame else pd.Series(float("nan"), index=index)
        if (values <= 0).any():
            raise StrategyError(f"'{column}' values must be positive price distances")
        out[column] = values.astype(float)
    return out
