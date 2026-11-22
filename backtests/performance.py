"""Performance metrics computed from completed trades and the equity curve."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtests.trade_engine import Trade

TRADE_COLUMNS = [
    "Trade ID", "Entry Date", "Exit Date", "Position Type", "Entry Price", "Exit Price",
    "Stop Loss", "Take Profit", "Position Size", "Lots", "Profit/Loss", "Return Percentage",
    "Trade Duration", "Duration (Days)", "Pips", "Gross P/L", "Commission", "Exit Reason",
    "Balance After", "Cumulative P/L",
]


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    starting_balance: float
    ending_balance: float
    ending_equity: float
    total_return_pct: float
    total_profit: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_pct: float
    loss_rate_pct: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    gross_profit: float
    gross_loss: float
    profit_factor: float          # inf when there are wins but no losses, nan without trades
    sharpe_ratio: float           # annualised; nan when undefined
    max_drawdown: float           # account currency, negative
    max_drawdown_pct: float       # percent, negative
    average_trade_duration: pd.Timedelta | None
    expectancy: float             # average P/L per trade
    risk_reward_ratio: float      # average win / |average loss|
    cagr_pct: float
    total_commission: float
    exposure_pct: float           # share of bars with at least one open trade
    periods_per_year: float
    start: pd.Timestamp
    end: pd.Timestamp


def trades_to_frame(trades: list[Trade], date_format: str = "%Y-%m-%d") -> pd.DataFrame:
    """Trade log in the export format (one row per completed trade)."""
    if not trades:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    cumulative = np.cumsum([t.pnl for t in trades])
    rows = [
        {
            "Trade ID": t.trade_id,
            "Entry Date": t.entry_time.strftime(date_format),
            "Exit Date": t.exit_time.strftime(date_format),
            "Position Type": t.side.value,
            "Entry Price": round(t.entry_price, 6),
            "Exit Price": round(t.exit_price, 6),
            "Stop Loss": None if t.stop_loss is None else round(t.stop_loss, 6),
            "Take Profit": None if t.take_profit is None else round(t.take_profit, 6),
            "Position Size": round(t.units, 2),
            "Lots": round(t.lots, 2),
            "Profit/Loss": round(t.pnl, 2),
            "Return Percentage": round(t.return_pct, 4),
            "Trade Duration": format_duration(t.duration),
            "Duration (Days)": round(t.duration / pd.Timedelta(days=1), 4),
            "Pips": round(t.pips, 1),
            "Gross P/L": round(t.gross_pnl, 2),
            "Commission": round(t.commission, 2),
            "Exit Reason": t.exit_reason.value,
            "Balance After": round(t.balance_after, 2),
            "Cumulative P/L": round(float(cum), 2),
        }
        for t, cum in zip(trades, cumulative)
    ]
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def build_equity_curve(raw: pd.DataFrame, starting_balance: float) -> pd.DataFrame:
    """Add cumulative profit and drawdown columns to the engine's equity curve."""
    curve = raw.copy()
    peak = curve["Equity"].cummax().clip(lower=starting_balance)
    curve["CumulativeProfit"] = curve["Equity"] - starting_balance
    curve["RealizedProfit"] = curve["Balance"] - starting_balance
    curve["Peak"] = peak
    curve["Drawdown"] = curve["Equity"] - peak
    curve["DrawdownPct"] = curve["Drawdown"] / peak * 100.0
    return curve


def monthly_returns(equity_curve: pd.DataFrame, starting_balance: float) -> pd.DataFrame:
    """Percent return per calendar month: one row per year, columns Jan-Dec plus the year's Total."""
    equity = equity_curve["Equity"]
    month_end = equity.groupby([equity.index.year, equity.index.month]).last()
    month_end.index = month_end.index.set_names(["Year", "Month"])
    previous = month_end.shift(1)
    previous.iloc[0] = starting_balance

    table = ((month_end / previous - 1.0) * 100.0).unstack("Month").reindex(columns=range(1, 13))
    table.columns = [pd.Timestamp(2000, m, 1).strftime("%b") for m in table.columns]
    year_start = previous.groupby(level="Year").first()
    year_end = month_end.groupby(level="Year").last()
    table["Total"] = (year_end / year_start - 1.0) * 100.0
    return table


def compute_metrics(
    trades: list[Trade],
    equity_curve: pd.DataFrame,
    starting_balance: float,
    risk_free_rate: float = 0.0,
) -> PerformanceMetrics:
    """Compute the full metric set.

    The Sharpe ratio uses per-bar returns of the mark-to-market equity curve,
    annualised with the observed number of bars per year. Maximum drawdown is
    measured on the same curve, so it includes losses on trades that were still open.
    """
    pnl = np.array([t.pnl for t in trades], dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    total = len(pnl)

    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    if total == 0:
        profit_factor = math.nan
    elif gross_loss == 0:
        profit_factor = math.inf if gross_profit > 0 else math.nan
    else:
        profit_factor = gross_profit / abs(gross_loss)

    average_win = float(wins.mean()) if wins.size else 0.0
    average_loss = float(losses.mean()) if losses.size else 0.0
    risk_reward = average_win / abs(average_loss) if average_loss else (math.inf if average_win else math.nan)

    equity = equity_curve["Equity"]
    start, end = equity.index[0], equity.index[-1]
    years = max((end - start) / pd.Timedelta(days=365.25), 1e-9)
    periods_per_year = len(equity) / years if len(equity) > 1 else 0.0

    returns = equity.pct_change().dropna()
    sharpe = math.nan
    if len(returns) > 1 and returns.std(ddof=1) > 0 and periods_per_year > 0:
        excess = returns - risk_free_rate / periods_per_year
        sharpe = float(excess.mean() / returns.std(ddof=1) * math.sqrt(periods_per_year))

    peak = equity.cummax().clip(lower=starting_balance)
    drawdown = equity - peak
    ending_equity = float(equity.iloc[-1])
    cagr = ((ending_equity / starting_balance) ** (1 / years) - 1) * 100 if ending_equity > 0 else -100.0

    durations = [t.duration for t in trades]
    return PerformanceMetrics(
        starting_balance=starting_balance,
        ending_balance=float(equity_curve["Balance"].iloc[-1]),
        ending_equity=ending_equity,
        total_return_pct=(ending_equity / starting_balance - 1) * 100,
        total_profit=ending_equity - starting_balance,
        total_trades=total,
        winning_trades=int(wins.size),
        losing_trades=int(losses.size),
        breakeven_trades=int(total - wins.size - losses.size),
        win_rate_pct=wins.size / total * 100 if total else 0.0,
        loss_rate_pct=losses.size / total * 100 if total else 0.0,
        average_win=average_win,
        average_loss=average_loss,
        largest_win=float(pnl.max()) if total else 0.0,
        largest_loss=float(pnl.min()) if total else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        max_drawdown=float(drawdown.min()),
        max_drawdown_pct=float((drawdown / peak).min() * 100),
        average_trade_duration=pd.Series(durations).mean() if durations else None,
        expectancy=float(pnl.mean()) if total else 0.0,
        risk_reward_ratio=risk_reward,
        cagr_pct=cagr,
        total_commission=float(sum(t.commission for t in trades)),
        exposure_pct=float((equity_curve["OpenTrades"] > 0).mean() * 100),
        periods_per_year=periods_per_year,
        start=start,
        end=end,
    )


def format_duration(value: pd.Timedelta | None) -> str:
    """Human-readable duration such as ``12d 4h`` or ``3h``."""
    if value is None or pd.isna(value):
        return "n/a"
    total_hours = int(round(value / pd.Timedelta(hours=1)))
    days, hours = divmod(total_hours, 24)
    if days and hours:
        return f"{days}d {hours}h"
    if days:
        return f"{days}d"
    return f"{hours}h"
