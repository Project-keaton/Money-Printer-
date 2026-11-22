"""Bar-by-bar trade simulation: order execution, spread, slippage, SL/TP and position sizing.

Execution model
---------------
* A signal produced at the **close** of bar *t* is executed at the **open** of bar *t+1*.
* Prices in the data are treated as mid prices (``price_basis: mid``: half the
  spread is paid on every entry and every exit) or as bid prices
  (``price_basis: bid``: buys fill at bid + spread, sells at bid).
* Market orders (entries, signal exits, end-of-data exits) and stop-loss fills
  suffer adverse ``slippage_pips``. Take-profit orders are limit orders and fill
  at their price, or better if the market gaps through them.
* Stop-loss and take-profit levels are checked against each bar's high and low,
  including the bar the trade was opened on. If the bar *opens* beyond a level
  (a gap), the fill is the open price. If one bar touches both levels, the
  ``intrabar_priority`` setting decides which is assumed to fill first
  (``stop_loss`` by default, the conservative choice).
* Commission is charged per lot, round turn, when the trade closes.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from backtests.config import BacktestConfig, ExecutionSettings, Instrument, RiskSettings

log = logging.getLogger(__name__)


class Side(StrEnum):
    BUY = "Buy"
    SELL = "Sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class ExitReason(StrEnum):
    STOP_LOSS = "Stop Loss"
    TAKE_PROFIT = "Take Profit"
    SIGNAL = "Exit Signal"
    OPPOSITE_SIGNAL = "Opposite Signal"
    END_OF_DATA = "End of Data"


@dataclass(slots=True)
class Position:
    """An open trade."""

    trade_id: int
    side: Side
    entry_time: pd.Timestamp
    entry_bar: int
    entry_price: float
    units: float
    lots: float
    stop_loss: float | None
    take_profit: float | None
    balance_at_entry: float


@dataclass(frozen=True, slots=True)
class Trade:
    """A completed trade."""

    trade_id: int
    side: Side
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_loss: float | None
    take_profit: float | None
    units: float
    lots: float
    gross_pnl: float
    commission: float
    pnl: float
    return_pct: float
    pips: float
    exit_reason: ExitReason
    balance_after: float
    bars_held: int

    @property
    def duration(self) -> pd.Timedelta:
        return self.exit_time - self.entry_time


@dataclass
class EngineResult:
    trades: list[Trade]
    equity_curve: pd.DataFrame
    final_balance: float
    signals_received: int = 0
    skipped_entries: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _PendingOrders:
    """Orders decided at a bar's close, executed at the next bar's open."""

    close_longs: ExitReason | None = None
    close_shorts: ExitReason | None = None
    entry: Side | None = None
    stop_distance: float = math.nan
    target_distance: float = math.nan


# --------------------------------------------------------------------------- #
# Execution model
# --------------------------------------------------------------------------- #


class ExecutionModel:
    """Converts data prices into realistic fill prices for each order type."""

    def __init__(self, settings: ExecutionSettings, instrument: Instrument) -> None:
        self.settings = settings
        self.instrument = instrument
        spread = settings.spread_pips * instrument.pip_size
        self.slippage = settings.slippage_pips * instrument.pip_size
        if settings.price_basis == "mid":
            self._bid_offset, self._ask_offset = -spread / 2, spread / 2
        else:  # data are bid prices
            self._bid_offset, self._ask_offset = 0.0, spread

    def bid(self, price: float) -> float:
        return price + self._bid_offset

    def ask(self, price: float) -> float:
        return price + self._ask_offset

    def entry_fill(self, side: Side, open_price: float) -> float:
        """Market entry: buy at the ask, sell at the bid, plus adverse slippage."""
        if side is Side.BUY:
            return self.ask(open_price) + self.slippage
        return self.bid(open_price) - self.slippage

    def market_exit_fill(self, side: Side, price: float) -> float:
        """Market exit of a position: a long sells at the bid, a short buys at the ask."""
        if side is Side.BUY:
            return self.bid(price) - self.slippage
        return self.ask(price) + self.slippage

    def mark_price(self, side: Side, close: float) -> float:
        """Price at which an open position is valued (what it would close at, before slippage)."""
        return self.bid(close) if side is Side.BUY else self.ask(close)

    def check_exit(
        self, position: Position, open_: float, high: float, low: float
    ) -> tuple[float, ExitReason] | None:
        """Return the stop-loss/take-profit fill for this bar, or ``None`` if neither triggers."""
        sl, tp = position.stop_loss, position.take_profit
        if position.side is Side.BUY:
            o, h, l = self.bid(open_), self.bid(high), self.bid(low)
            sl_hit = sl is not None and l <= sl
            tp_hit = tp is not None and h >= tp
            sl_fill = (min(sl, o) - self.slippage) if sl is not None else math.nan
            tp_fill = max(tp, o) if tp is not None else math.nan
            gap_sl = sl is not None and o <= sl
            gap_tp = tp is not None and o >= tp
        else:
            o, h, l = self.ask(open_), self.ask(high), self.ask(low)
            sl_hit = sl is not None and h >= sl
            tp_hit = tp is not None and l <= tp
            sl_fill = (max(sl, o) + self.slippage) if sl is not None else math.nan
            tp_fill = min(tp, o) if tp is not None else math.nan
            gap_sl = sl is not None and o >= sl
            gap_tp = tp is not None and o <= tp

        if sl_hit and tp_hit:
            # The open tells us which level was crossed first when the bar gapped through one.
            if gap_sl:
                return sl_fill, ExitReason.STOP_LOSS
            if gap_tp:
                return tp_fill, ExitReason.TAKE_PROFIT
            if self.settings.intrabar_priority == "take_profit":
                return tp_fill, ExitReason.TAKE_PROFIT
            return sl_fill, ExitReason.STOP_LOSS
        if sl_hit:
            return sl_fill, ExitReason.STOP_LOSS
        if tp_hit:
            return tp_fill, ExitReason.TAKE_PROFIT
        return None


# --------------------------------------------------------------------------- #
# Position sizing
# --------------------------------------------------------------------------- #


class PositionSizer:
    """Risk-based or fixed-lot sizing, rounded to the broker's lot step and capped by leverage."""

    def __init__(self, risk: RiskSettings, instrument: Instrument) -> None:
        self.risk = risk
        self.instrument = instrument

    def size(self, balance: float, entry_price: float, stop_distance: float) -> tuple[float, float]:
        """Return ``(units, lots)``; ``(0, 0)`` if the trade cannot be sized.

        Risk-based: units = (balance x risk_per_trade) / (stop distance x quote-to-account rate),
        so hitting the stop loses about ``risk_per_trade`` of the balance (before costs).
        """
        contract = self.instrument.contract_size
        conversion = self.instrument.quote_to_account(entry_price)

        if self.risk.position_sizing == "risk":
            if not stop_distance > 0:
                return 0.0, 0.0
            units = balance * self.risk.risk_per_trade / (stop_distance * conversion)
        else:
            units = self.risk.fixed_lots * contract

        # Leverage cap: notional value in account currency <= balance x max_leverage.
        max_units = balance * self.risk.max_leverage / (entry_price * conversion)
        lots = min(units, max_units) / contract
        lots = math.floor(lots / self.risk.lot_step + 1e-9) * self.risk.lot_step
        lots = round(min(lots, self.risk.max_lots), 8)
        if lots < self.risk.min_lot:
            return 0.0, 0.0
        return lots * contract, lots


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class TradeEngine:
    """Simulates trading a signal frame over OHLC bars."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.instrument = config.instrument
        self.execution = ExecutionModel(config.execution, self.instrument)
        self.sizer = PositionSizer(config.risk, self.instrument)

    def run(self, bars: pd.DataFrame, signals: pd.DataFrame) -> EngineResult:
        """Run the simulation.

        Args:
            bars: OHLC frame indexed by timestamp.
            signals: normalised signal frame with ``signal``, ``exit_long``, ``exit_short``,
                ``stop_distance`` and ``target_distance`` columns, same index as ``bars``.
        """
        if not signals.index.equals(bars.index):
            raise ValueError("signals and bars must share the same index")

        times = bars.index
        opens, highs = bars["Open"].to_numpy(float), bars["High"].to_numpy(float)
        lows, closes = bars["Low"].to_numpy(float), bars["Close"].to_numpy(float)
        sig = signals["signal"].to_numpy(int)
        exit_long = signals["exit_long"].to_numpy(bool)
        exit_short = signals["exit_short"].to_numpy(bool)
        stop_dist = signals["stop_distance"].to_numpy(float)
        target_dist = signals["target_distance"].to_numpy(float)

        self._balance = self.config.starting_balance
        self._open: list[Position] = []
        self._trades: list[Trade] = []
        self._next_id = 1
        skipped: Counter[str] = Counter()
        signals_received = int(np.count_nonzero(sig))
        equity_rows: list[tuple[pd.Timestamp, float, float, int]] = []
        pending: _PendingOrders | None = None
        last = len(bars) - 1

        for i in range(len(bars)):
            ts = times[i]

            # 1) Orders decided at the previous close fill at this open.
            if pending is not None:
                self._execute_pending(pending, i, ts, opens[i], skipped)
                pending = None

            # 2) Protective orders.
            for position in list(self._open):
                hit = self.execution.check_exit(position, opens[i], highs[i], lows[i])
                if hit is not None:
                    self._close(position, ts, i, hit[0], hit[1])

            # 3) End of data.
            if i == last and self.config.close_open_trades_at_end:
                for position in list(self._open):
                    fill = self.execution.market_exit_fill(position.side, closes[i])
                    self._close(position, ts, i, fill, ExitReason.END_OF_DATA)

            # 4) Mark to market.
            equity = self._balance + sum(self._unrealized(p, closes[i]) for p in self._open)
            equity_rows.append((ts, self._balance, equity, len(self._open)))

            # 5) Read this bar's signal for the next open.
            if i < last:
                pending = self._plan(sig[i], exit_long[i], exit_short[i], stop_dist[i], target_dist[i])
            elif sig[i] != 0:
                skipped["signal on last bar"] += 1

        equity_curve = pd.DataFrame(equity_rows, columns=["Date", "Balance", "Equity", "OpenTrades"]).set_index("Date")
        log.info(
            "Simulation finished: %d trade(s), %d signal(s), final balance %.2f",
            len(self._trades), signals_received, self._balance,
        )
        return EngineResult(self._trades, equity_curve, self._balance, signals_received, skipped)

    # ---------------------------------------------------------------- steps

    def _plan(
        self, signal: int, exit_long: bool, exit_short: bool, stop_distance: float, target_distance: float
    ) -> _PendingOrders | None:
        orders = _PendingOrders()
        if exit_long:
            orders.close_longs = ExitReason.SIGNAL
        if exit_short:
            orders.close_shorts = ExitReason.SIGNAL
        if signal != 0:
            side = Side.BUY if signal > 0 else Side.SELL
            orders.entry = side
            orders.stop_distance, orders.target_distance = stop_distance, target_distance
            if self.config.close_on_opposite_signal:
                if side is Side.BUY:
                    orders.close_shorts = ExitReason.OPPOSITE_SIGNAL
                else:
                    orders.close_longs = ExitReason.OPPOSITE_SIGNAL
        if orders.entry is None and orders.close_longs is None and orders.close_shorts is None:
            return None
        return orders

    def _execute_pending(
        self, orders: _PendingOrders, bar: int, ts: pd.Timestamp, open_price: float, skipped: Counter[str]
    ) -> None:
        for position in list(self._open):
            reason = orders.close_longs if position.side is Side.BUY else orders.close_shorts
            if reason is not None:
                fill = self.execution.market_exit_fill(position.side, open_price)
                self._close(position, ts, bar, fill, reason)

        side = orders.entry
        if side is None:
            return
        if len(self._open) >= self.config.max_positions:
            skipped["max open trades reached"] += 1
            return

        entry = self.execution.entry_fill(side, open_price)
        units, lots = self.sizer.size(self._balance, entry, orders.stop_distance)
        if units <= 0:
            reason = "no stop distance (indicator warm-up)" if not orders.stop_distance > 0 else "position below minimum lot"
            skipped[reason] += 1
            log.debug("Skipped %s entry at %s: %s", side, ts, reason)
            return

        stop = entry - side.sign * orders.stop_distance if orders.stop_distance > 0 else None
        target = entry + side.sign * orders.target_distance if orders.target_distance > 0 else None
        position = Position(
            trade_id=self._next_id, side=side, entry_time=ts, entry_bar=bar, entry_price=entry,
            units=units, lots=lots, stop_loss=stop, take_profit=target, balance_at_entry=self._balance,
        )
        self._next_id += 1
        self._open.append(position)
        log.debug(
            "Opened #%d %s %.2f lots at %.5f (SL %s, TP %s) on %s",
            position.trade_id, side, lots, entry, _fmt(stop), _fmt(target), ts,
        )

    def _close(self, position: Position, ts: pd.Timestamp, bar: int, fill: float, reason: ExitReason) -> None:
        move = position.side.sign * (fill - position.entry_price)
        gross = move * position.units * self.instrument.quote_to_account(fill)
        commission = self.config.execution.commission_per_lot * position.lots
        pnl = gross - commission
        self._balance += pnl
        self._open.remove(position)

        trade = Trade(
            trade_id=position.trade_id,
            side=position.side,
            entry_time=position.entry_time,
            exit_time=ts,
            entry_price=position.entry_price,
            exit_price=fill,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            units=position.units,
            lots=position.lots,
            gross_pnl=gross,
            commission=commission,
            pnl=pnl,
            return_pct=pnl / position.balance_at_entry * 100.0,
            pips=self.instrument.to_pips(move),
            exit_reason=reason,
            balance_after=self._balance,
            bars_held=bar - position.entry_bar,
        )
        self._trades.append(trade)
        log.info(
            "Trade #%d %s %s -> %s | %.5f -> %.5f | %s | P/L %.2f | balance %.2f",
            trade.trade_id, trade.side, trade.entry_time, trade.exit_time,
            trade.entry_price, trade.exit_price, reason, pnl, self._balance,
        )

    def _unrealized(self, position: Position, close: float) -> float:
        mark = self.execution.mark_price(position.side, close)
        gross = position.side.sign * (mark - position.entry_price) * position.units
        gross *= self.instrument.quote_to_account(mark)
        return gross - self.config.execution.commission_per_lot * position.lots


def _fmt(value: float | None) -> str:
    return "none" if value is None else f"{value:.5f}"
