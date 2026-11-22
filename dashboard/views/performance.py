"""Performance analytics: trade statistics and distribution charts."""

from __future__ import annotations

import streamlit as st

from dashboard.charts.performance import breakdown_bar, duration_vs_pnl, pnl_by_trade, pnl_distribution
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import chart, page_header, run_subtitle, section
from dashboard.utils import formatting as fmt
from dashboard.utils.analytics import breakdown, trade_frame
from dashboard.utils.state import require_result

result = require_result()
m = result.metrics
trades = trade_frame(result)

page_header("Performance Analytics", run_subtitle(result))

render_kpis([
    KPI("Win Rate", fmt.pct(m.win_rate_pct), caption=f"{m.winning_trades} of {m.total_trades} trades"),
    KPI("Loss Rate", fmt.pct(m.loss_rate_pct), caption=f"{m.losing_trades} of {m.total_trades} trades"),
    KPI("Average Winner", fmt.money(m.average_win), tone="positive" if m.average_win > 0 else "neutral"),
    KPI("Average Loser", fmt.money(m.average_loss), tone="negative" if m.average_loss < 0 else "neutral"),
    KPI("Largest Winner", fmt.money(m.largest_win), tone="positive" if m.largest_win > 0 else "neutral"),
    KPI("Largest Loser", fmt.money(m.largest_loss), tone="negative" if m.largest_loss < 0 else "neutral"),
    KPI("Profit Factor", fmt.ratio(m.profit_factor), tone=fmt.tone((m.profit_factor or 0) - 1),
        badge="Above 1" if m.profit_factor > 1 else "Below 1", help="Gross profit / gross loss"),
    KPI("Expectancy", fmt.signed_money(m.expectancy), tone=fmt.tone(m.expectancy), caption="average P/L per trade"),
    KPI("Sharpe Ratio", fmt.ratio(m.sharpe_ratio), tone=fmt.tone(m.sharpe_ratio), caption="annualised"),
    KPI("Risk-Reward Ratio", fmt.ratio(m.risk_reward_ratio), caption="avg winner / avg loser"),
], columns=5)

st.html(
    f'<div class="fb-section-caption">Gross profit {fmt.money(m.gross_profit)} · gross loss '
    f"{fmt.money(m.gross_loss)} · commission {fmt.money(m.total_commission)} · average trade duration "
    f"{fmt.duration(m.average_trade_duration)} · time in market {fmt.pct(m.exposure_pct)}</div>"
)

chart(pnl_by_trade(trades), key="pnl_by_trade")

left, right = st.columns(2, gap="medium")
with left:
    chart(pnl_distribution(trades), key="distribution")
with right:
    chart(duration_vs_pnl(trades), key="duration")

left, right = st.columns(2, gap="medium")
by_side = breakdown(trades, "Trade Type")
by_reason = breakdown(trades, "Exit Reason")
with left:
    chart(breakdown_bar(by_side, "Trade Type", title="Long vs short", height=260), key="by_side")
with right:
    chart(breakdown_bar(by_reason, "Exit Reason", title="Net P/L by exit reason", height=260), key="by_reason")

section("Breakdown tables")
money = st.column_config.NumberColumn(format="dollar")
rate = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)
left, right = st.columns(2, gap="medium")
with left:
    st.dataframe(by_side, hide_index=True, column_config={"Win Rate %": rate, "Profit/Loss": money, "Average P/L": money})
with right:
    st.dataframe(by_reason, hide_index=True, column_config={"Win Rate %": rate, "Profit/Loss": money, "Average P/L": money})
