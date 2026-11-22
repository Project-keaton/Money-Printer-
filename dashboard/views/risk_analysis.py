"""Risk analysis: drawdowns, recovery periods and worst trading periods."""

from __future__ import annotations

import math

import streamlit as st

from dashboard.charts.risk import drawdown_curve, drawdown_episodes_bar
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import chart, page_header, run_subtitle, section
from dashboard.utils import formatting as fmt
from dashboard.utils.analytics import (
    current_drawdown_pct, drawdown_episodes, equity_frame, losing_streaks, longest_drawdown_days, monthly_table,
    trade_frame, worst_months,
)
from dashboard.utils.state import require_result

result = require_result()
m = result.metrics
trades = trade_frame(result)
episodes = drawdown_episodes(result)
streaks = losing_streaks(trades)
recovery_factor = m.total_profit / abs(m.max_drawdown) if m.max_drawdown else math.nan
current = current_drawdown_pct(result)

page_header("Risk Analysis", run_subtitle(result))

render_kpis([
    KPI("Maximum Drawdown", fmt.pct(m.max_drawdown_pct), tone="negative" if m.max_drawdown < 0 else "neutral",
        caption=fmt.money(m.max_drawdown)),
    KPI("Current Drawdown", fmt.pct(current), tone="negative" if current < 0 else "positive",
        badge="At equity high" if current >= 0 else "Below peak"),
    KPI("Longest Drawdown", f"{longest_drawdown_days(episodes):,} days", caption="peak to recovery (or today)"),
    KPI("Recovery Factor", fmt.ratio(recovery_factor), tone=fmt.tone(recovery_factor),
        help="Net profit / maximum drawdown. Above 1 means profits outweighed the worst drawdown."),
    KPI("Longest Losing Streak", f"{int(streaks['Losing Trades'].max()) if not streaks.empty else 0} trades",
        caption=fmt.money(float(streaks["Total Loss"].iloc[0])) if not streaks.empty else ""),
], columns=5)

chart(drawdown_curve(equity_frame(result)), key="drawdown")

section("Recovery periods", "The deepest drawdowns: how far equity fell and how long it took to regain the previous peak")
top = episodes.head(10)
if len(top) == 1 and not bool(top["Recovered"].iloc[0]):
    st.info(f"Equity has not regained its {top['Peak Date'].iloc[0]:%d %b %Y} peak, so the whole period since then "
            "counts as one drawdown. Its deepest point and length are shown below.", icon=":material/info:")
if len(top) >= 2:
    left, right = st.columns([2, 3], gap="medium")
    with left:
        chart(drawdown_episodes_bar(top), key="episodes")
else:
    right = st.container()
with right:
    if top.empty:
        st.info("Equity never fell below its peak.")
    else:
        table = top.copy()
        table["Recovery"] = table.apply(
            lambda r: f"{int(r['Days to Recover'])} days" if r["Recovered"] else "Not yet recovered", axis=1)
        st.dataframe(
            table[["Peak Date", "Trough Date", "Recovery Date", "Depth %", "Depth $", "Days to Trough", "Recovery", "Total Days"]],
            hide_index=True,
            column_config={
                "Peak Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Trough Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Recovery Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Depth %": st.column_config.NumberColumn(format="%.2f%%"),
                "Depth $": st.column_config.NumberColumn(format="dollar"),
            },
        )

section("Worst trading periods")
left, right = st.columns(2, gap="medium")
with left:
    st.markdown("**Worst months**")
    st.dataframe(worst_months(monthly_table(result)), hide_index=True,
                 column_config={"Return %": st.column_config.NumberColumn(format="%.2f%%")})
with right:
    st.markdown("**Longest losing streaks**")
    if streaks.empty:
        st.info("No losing trades.")
    else:
        st.dataframe(streaks, hide_index=True, column_config={
            "Start": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "End": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Total Loss": st.column_config.NumberColumn(format="dollar"),
        })

with st.expander("Risk settings used in this backtest", icon=":material/shield:"):
    rk, ex = result.config.risk, result.config.execution
    st.markdown(
        f"- **Risk per trade:** {rk.risk_per_trade * 100:g}% of balance ({rk.position_sizing} sizing)\n"
        f"- **Stop loss:** {rk.stop_loss.mode} · **Take profit:** {rk.take_profit.mode}\n"
        f"- **Max leverage:** {rk.max_leverage:g}x · **Max open trades:** {result.config.max_positions}\n"
        f"- **Costs:** {ex.spread_pips:g} pip spread, {fmt.money(ex.commission_per_lot)} per lot, {ex.slippage_pips:g} pip slippage"
    )
