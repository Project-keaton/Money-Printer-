"""EMA crossover trend-following strategy."""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from strategies.base import LONG, SHORT, Strategy, StrategyError
from strategies.indicators import crossed_above, crossed_below, ema


class EmaCrossoverStrategy(Strategy):
    """Go long when the fast EMA crosses above the slow EMA, short when it crosses below.

    With ``long_only`` a bearish cross only closes longs instead of opening a short.
    Stops and targets come from the ``risk`` section of ``config.yaml``.
    """

    name: ClassVar[str] = "ema_crossover"

    def __init__(self, fast_period: int = 20, slow_period: int = 50, long_only: bool = False) -> None:
        if not (isinstance(fast_period, int) and isinstance(slow_period, int)) or fast_period < 1:
            raise StrategyError("EMA periods must be positive integers")
        if fast_period >= slow_period:
            raise StrategyError(f"fast_period ({fast_period}) must be smaller than slow_period ({slow_period})")
        super().__init__(fast_period=fast_period, slow_period=slow_period, long_only=long_only)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.long_only = long_only

    @property
    def warmup_bars(self) -> int:
        return self.slow_period

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        fast = ema(data["Close"], self.fast_period)
        slow = ema(data["Close"], self.slow_period)
        bullish = crossed_above(fast, slow)
        bearish = crossed_below(fast, slow)

        signals = pd.DataFrame(index=data.index)
        signals["signal"] = 0
        signals.loc[bullish, "signal"] = LONG
        if self.long_only:
            signals["exit_long"] = bearish
        else:
            signals.loc[bearish, "signal"] = SHORT
        return signals
