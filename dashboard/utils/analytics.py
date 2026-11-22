"""Analytics derived from a :class:`BacktestResult` for the dashboard pages.

All functions are pure (no Streamlit calls) so they can be unit-tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtests.backtester import BacktestResult
from backtests.performance import format_duration, monthly_returns

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def trade_frame(result: BacktestResult) -> pd.DataFrame:
    """Typed trade table (timestamps, numbers) for filtering and charts."""
    columns = [
        "Trade ID", "Entry Date", "Exit Date", "Trade Type", "Entry Price", "Exit Price", "Stop Loss",
        "Take Profit", "Lots", "Units", "Profit/Loss", "Return %", "Pips", "Commission", "Duration",
        "Duration (Days)", "Trade Duration", "Exit Reason", "Balance After", "Cumulative P/L", "Outcome",
    ]
    if not result.trades:
        return pd.DataFrame(columns=columns)
    rows = []
    cumulative = 0.0
    for t in result.trades:
        cumulative += t.pnl
        rows.append({
            "Trade ID": t.trade_id,
            "Entry Date": t.entry_time.tz_convert(None),
            "Exit Date": t.exit_time.tz_convert(None),
            "Trade Type": t.side.value,
            "Entry Price": t.entry_price,
            "Exit Price": t.exit_price,
            "Stop Loss": t.stop_loss,
            "Take Profit": t.take_profit,
            "Lots": t.lots,
            "Units": t.units,
            "Profit/Loss": t.pnl,
            "Return %": t.return_pct,
            "Pips": t.pips,
            "Commission": t.commission,
            "Duration": t.duration,
            "Duration (Days)": t.duration / pd.Timedelta(days=1),
            "Trade Duration": format_duration(t.duration),
            "Exit Reason": t.exit_reason.value,
            "Balance After": t.balance_after,
            "Cumulative P/L": cumulative,
            "Outcome": "Win" if t.pnl > 0 else ("Loss" if t.pnl < 0 else "Break-even"),
        })
    return pd.DataFrame(rows, columns=columns)


def equity_frame(result: BacktestResult) -> pd.DataFrame:
    """Equity curve with a timezone-naive index (Plotly-friendly) and growth %."""
    curve = result.equity_curve.copy()
    curve.index = curve.index.tz_convert(None)
    curve["GrowthPct"] = (curve["Equity"] / result.config.starting_balance - 1.0) * 100.0
    return curve


def yearly_returns(result: BacktestResult) -> pd.DataFrame:
    """Return and profit per calendar year."""
    equity = result.equity_curve["Equity"]
    year_end = equity.groupby(equity.index.year).last()
    year_start = year_end.shift(1)
    year_start.iloc[0] = result.config.starting_balance
    out = pd.DataFrame({
        "Year": year_end.index.astype(int),
        "Start Equity": year_start.to_numpy(),
        "End Equity": year_end.to_numpy(),
    })
    out["Profit"] = out["End Equity"] - out["Start Equity"]
    out["Return %"] = out["Profit"] / out["Start Equity"] * 100.0
    return out


def monthly_table(result: BacktestResult) -> pd.DataFrame:
    """Year x month returns (%) plus a ``Total`` column."""
    return monthly_returns(result.equity_curve, result.config.starting_balance)


def monthly_series(table: pd.DataFrame) -> pd.Series:
    """Monthly returns as a time series indexed by month start (NaN months dropped)."""
    long = table[MONTHS].stack()
    index = pd.to_datetime([f"{year}-{MONTHS.index(month) + 1:02d}-01" for year, month in long.index])
    return pd.Series(long.to_numpy(), index=index).sort_index()


def monthly_trade_stats(trades: pd.DataFrame) -> pd.DataFrame:
    """Trades, wins, win rate and P/L per calendar month (by exit date)."""
    columns = ["Year", "Month", "Trades", "Wins", "Win Rate %", "Profit/Loss"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    grouped = trades.groupby([trades["Exit Date"].dt.year, trades["Exit Date"].dt.month])
    out = pd.DataFrame({
        "Trades": grouped.size(),
        "Wins": grouped["Profit/Loss"].apply(lambda s: int((s > 0).sum())),
        "Profit/Loss": grouped["Profit/Loss"].sum(),
    })
    out["Win Rate %"] = out["Wins"] / out["Trades"] * 100.0
    out.index = out.index.set_names(["Year", "Month"])
    return out.reset_index()[columns]


def drawdown_episodes(result: BacktestResult, top: int | None = None) -> pd.DataFrame:
    """Every drawdown from a peak, with trough, recovery and durations, deepest first.

    A drawdown starts when equity falls below its running peak and ends when
    equity regains that peak. Unrecovered drawdowns have no recovery date.
    """
    curve = result.equity_curve
    equity, peak = curve["Equity"], curve["Peak"]
    under = (equity < peak - 1e-9).to_numpy()
    index = curve.index.tz_convert(None)
    columns = ["Peak Date", "Trough Date", "Recovery Date", "Depth $", "Depth %",
               "Days to Trough", "Days to Recover", "Total Days", "Recovered"]
    episodes = []
    i, n = 0, len(under)
    while i < n:
        if not under[i]:
            i += 1
            continue
        start = i
        while i < n and under[i]:
            i += 1
        end = i  # first bar back at the peak, or n if never recovered
        segment = equity.iloc[start:end]
        peak_value = float(peak.iloc[start])
        trough_pos = start + int(np.argmin(segment.to_numpy()))
        peak_date = index[start - 1] if start > 0 else index[start]
        trough_date = index[trough_pos]
        recovered = end < n
        recovery_date = index[end] if recovered else pd.NaT
        depth = float(segment.min()) - peak_value
        last_date = recovery_date if recovered else index[-1]
        episodes.append({
            "Peak Date": peak_date,
            "Trough Date": trough_date,
            "Recovery Date": recovery_date,
            "Depth $": depth,
            "Depth %": depth / peak_value * 100.0,
            "Days to Trough": (trough_date - peak_date).days,
            "Days to Recover": (recovery_date - trough_date).days if recovered else np.nan,
            "Total Days": (last_date - peak_date).days,
            "Recovered": recovered,
        })
    frame = pd.DataFrame(episodes, columns=columns).sort_values("Depth %", kind="stable").reset_index(drop=True)
    return frame.head(top) if top else frame


def losing_streaks(trades: pd.DataFrame, top: int = 5) -> pd.DataFrame:
    """Longest runs of consecutive losing trades."""
    columns = ["Start", "End", "Losing Trades", "Total Loss"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    losing = (trades["Profit/Loss"] < 0).to_numpy()
    streaks, i = [], 0
    while i < len(losing):
        if not losing[i]:
            i += 1
            continue
        start = i
        while i < len(losing) and losing[i]:
            i += 1
        chunk = trades.iloc[start:i]
        streaks.append({
            "Start": chunk["Entry Date"].iloc[0],
            "End": chunk["Exit Date"].iloc[-1],
            "Losing Trades": i - start,
            "Total Loss": float(chunk["Profit/Loss"].sum()),
        })
    frame = pd.DataFrame(streaks, columns=columns)
    return frame.sort_values(["Losing Trades", "Total Loss"], ascending=[False, True]).head(top).reset_index(drop=True)


def worst_months(table: pd.DataFrame, top: int = 5) -> pd.DataFrame:
    series = monthly_series(table)
    worst = series.nsmallest(top)
    return pd.DataFrame({"Month": worst.index.strftime("%b %Y"), "Return %": worst.to_numpy()})


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    """Trades, win rate and P/L grouped by a column such as ``Trade Type`` or ``Exit Reason``."""
    columns = [by, "Trades", "Win Rate %", "Profit/Loss", "Average P/L"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    grouped = trades.groupby(by)["Profit/Loss"]
    out = pd.DataFrame({
        "Trades": grouped.size(),
        "Win Rate %": grouped.apply(lambda s: (s > 0).mean() * 100.0),
        "Profit/Loss": grouped.sum(),
        "Average P/L": grouped.mean(),
    }).reset_index()
    return out.sort_values("Trades", ascending=False).reset_index(drop=True)[columns]


def longest_drawdown_days(episodes: pd.DataFrame) -> int:
    return int(episodes["Total Days"].max()) if not episodes.empty else 0


def current_drawdown_pct(result: BacktestResult) -> float:
    return float(result.equity_curve["DrawdownPct"].iloc[-1])
