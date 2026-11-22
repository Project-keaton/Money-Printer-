"""RSI mean-reversion strategy."""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from strategies.base import LONG, SHORT, Strategy, StrategyError
from strategies.indicators import crossed_above, crossed_below, rsi


class RsiReversalStrategy(Strategy):
    """Fade RSI extremes.

    * Long when RSI crosses back **up** through ``oversold``.
    * Short when RSI crosses back **down** through ``overbought``.
    * Longs exit when RSI crosses above ``exit_level``; shorts when it crosses below.

    Stop-loss and take-profit orders from ``config.yaml`` still apply.
    """

    name: ClassVar[str] = "rsi_reversal"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_level: float = 50.0,
        long_only: bool = False,
    ) -> None:
        if not isinstance(period, int) or period < 2:
            raise StrategyError("RSI period must be an integer >= 2")
        if not 0 < oversold < exit_level < overbought < 100:
            raise StrategyError("RSI levels must satisfy 0 < oversold < exit_level < overbought < 100")
        super().__init__(
            period=period, oversold=oversold, overbought=overbought, exit_level=exit_level, long_only=long_only
        )
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.exit_level = exit_level
        self.long_only = long_only

    @property
    def warmup_bars(self) -> int:
        return self.period + 1

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        value = rsi(data["Close"], self.period)

        signals = pd.DataFrame(index=data.index)
        signals["signal"] = 0
        signals.loc[crossed_above(value, self.oversold), "signal"] = LONG
        if not self.long_only:
            signals.loc[crossed_below(value, self.overbought), "signal"] = SHORT
        signals["exit_long"] = crossed_above(value, self.exit_level)
        signals["exit_short"] = crossed_below(value, self.exit_level)
        return signals
