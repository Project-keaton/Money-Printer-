"""Overview: headline KPIs, equity curve and latest trades."""

from __future__ import annotations

import streamlit as st

from dashboard.charts.equity import equity_curve
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import chart, page_header, run_subtitle, section
from dashboard.utils import formatting as fmt
from dashboard.utils.analytics import breakdown, equity_frame, trade_frame
from dashboard.utils.state import require_result

result = require_result()
m = result.metrics
trades = trade_frame(result)
years = max((m.end - m.start).days / 365.25, 1e-9)

page_header("Overview", run_subtitle(result))

render_kpis([
    KPI("Starting Balance", fmt.money(m.starting_balance), caption=f"{m.start:%d %b %Y}"),
    KPI("Current Balance", fmt.money(m.ending_balance), tone=fmt.tone(m.total_profit),
        badge=fmt.pct(m.total_return_pct, signed=True), caption=f"{m.end:%d %b %Y}"),
    KPI("Total Profit", fmt.signed_money(m.total_profit), tone=fmt.tone(m.total_profit),
        badge="Profit" if m.total_profit > 0 else "Loss" if m.total_profit < 0 else "Flat",
        caption=f"after {fmt.money(m.total_commission)} commission"),
    KPI("Total Return", fmt.pct(m.total_return_pct, signed=True), tone=fmt.tone(m.total_return_pct),
        caption=f"CAGR {fmt.pct(m.cagr_pct, signed=True)}"),
    KPI("Total Trades", fmt.integer(m.total_trades), caption=f"{m.total_trades / years:.1f} per year"),
    KPI("Win Rate", fmt.pct(m.win_rate_pct), caption=f"{m.winning_trades} winning trades",
        help="Winning trades / total trades"),
    KPI("Loss Rate", fmt.pct(m.loss_rate_pct), caption=f"{m.losing_trades} losing trades"),
    KPI("Profit Factor", fmt.ratio(m.profit_factor), tone=fmt.tone((m.profit_factor or 0) - 1),
        badge="Profitable" if m.profit_factor > 1 else "Unprofitable", help="Gross profit / gross loss"),
    KPI("Sharpe Ratio", fmt.ratio(m.sharpe_ratio), tone=fmt.tone(m.sharpe_ratio),
        caption="annualised", help="Mean excess return / volatility of per-bar equity returns, annualised"),
    KPI("Maximum Drawdown", fmt.pct(m.max_drawdown_pct), tone="negative" if m.max_drawdown < 0 else "neutral",
        caption=fmt.money(m.max_drawdown), help="Largest fall of equity from its running peak"),
])

chart(equity_curve(equity_frame(result), m.starting_balance, height=400), key="overview_equity")

left, right = st.columns([3, 2], gap="medium")
with left:
    section("Latest trades", "The 10 most recent closed trades")
    if trades.empty:
        st.info("The strategy produced no trades with the current settings.")
    else:
        recent = trades.tail(10).iloc[::-1]
        st.dataframe(
            recent[["Trade ID", "Exit Date", "Trade Type", "Entry Price", "Exit Price", "Profit/Loss", "Exit Reason"]],
            hide_index=True,
            column_config={
                "Exit Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Entry Price": st.column_config.NumberColumn(format="%.5f"),
                "Exit Price": st.column_config.NumberColumn(format="%.5f"),
                "Profit/Loss": st.column_config.NumberColumn(format="dollar"),
            },
        )
with right:
    section("How trades ended", "Count, win rate and net P/L by exit type")
    table = breakdown(trades, "Exit Reason")
    if table.empty:
        st.info("No trades yet.")
    else:
        st.dataframe(
            table, hide_index=True,
            column_config={
                "Win Rate %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                "Profit/Loss": st.column_config.NumberColumn(format="dollar"),
                "Average P/L": st.column_config.NumberColumn(format="dollar"),
            },
        )

if result.warnings:
    with st.expander(f"Run notes ({len(result.warnings)})", icon=":material/info:"):
        for warning in result.warnings:
            st.markdown(f"- {warning}")
