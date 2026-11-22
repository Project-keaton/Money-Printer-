"""Monthly analytics: return and win-rate heatmaps, best/worst months, seasonality."""

from __future__ import annotations

import streamlit as st

from dashboard.charts.monthly import monthly_returns_bar, returns_heatmap, seasonality_bar, win_rate_heatmap
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import chart, page_header, run_subtitle
from dashboard.utils import formatting as fmt
from dashboard.utils.analytics import monthly_series, monthly_table, monthly_trade_stats, trade_frame
from dashboard.utils.state import require_result

result = require_result()
table = monthly_table(result)
series = monthly_series(table)
stats = monthly_trade_stats(trade_frame(result))

page_header("Monthly Analytics", run_subtitle(result))

if series.empty:
    st.info("Not enough data for monthly statistics.")
    st.stop()

best, worst = series.idxmax(), series.idxmin()
traded_months = stats[stats["Trades"] > 0]
avg_win_rate = float(traded_months["Win Rate %"].mean()) if not traded_months.empty else float("nan")
render_kpis([
    KPI("Best Month", fmt.pct(series.max(), signed=True), tone="positive", caption=f"{best:%B %Y}"),
    KPI("Worst Month", fmt.pct(series.min(), signed=True), tone="negative", caption=f"{worst:%B %Y}"),
    KPI("Average Month", fmt.pct(series.mean(), signed=True), tone=fmt.tone(series.mean())),
    KPI("Positive Months", fmt.pct((series > 0).mean() * 100), caption=f"{int((series > 0).sum())} of {len(series)} months"),
    KPI("Avg Monthly Win Rate", fmt.pct(avg_win_rate), caption=f"over {len(traded_months)} months with trades"),
], columns=5)

chart(returns_heatmap(table), key="returns_heatmap")
chart(monthly_returns_bar(series), key="monthly_bar")

left, right = st.columns([3, 2], gap="medium")
with left:
    chart(win_rate_heatmap(stats, [int(y) for y in table.index]), key="winrate_heatmap")
with right:
    chart(seasonality_bar(series, height=70 + 34 * len(table)), key="seasonality")

with st.expander("Monthly returns table", icon=":material/table:"):
    st.dataframe(table.round(2), column_config={
        c: st.column_config.NumberColumn(format="%.2f%%") for c in table.columns
    })
