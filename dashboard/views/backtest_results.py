"""Backtest results: equity curve, account growth, cumulative profit and trades on the price chart."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.charts.equity import cumulative_profit, equity_curve, growth_curve, yearly_returns_bar
from dashboard.charts.market import price_chart
from dashboard.components.layout import chart, page_header, run_subtitle, section
from dashboard.utils.analytics import equity_frame, trade_frame, yearly_returns
from dashboard.utils.state import require_result

result = require_result()
curve = equity_frame(result)
trades = trade_frame(result)

page_header("Backtest Results", run_subtitle(result))

chart(equity_curve(curve, result.config.starting_balance, height=460), key="equity")

left, right = st.columns(2, gap="medium")
with left:
    chart(growth_curve(curve), key="growth")
with right:
    chart(yearly_returns_bar(yearly_returns(result)), key="yearly")

chart(cumulative_profit(trades), key="cumulative")

section("Trades on the price chart", "Candles with the strategy's indicators; ▲/▼ entries, × exits. Hover for details.")
data = result.data
available_years = sorted(data.index.year.unique().tolist(), reverse=True)
col_year, col_info = st.columns([1, 3], vertical_alignment="bottom")
with col_year:
    year = st.selectbox("Year", available_years, index=0)
with col_info:
    in_year = trades[trades["Entry Date"].dt.year == year] if not trades.empty else trades
    st.caption(f"{len(in_year)} trade(s) opened in {year}")

start, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31 23:59")
chart(price_chart(data, start, end, strategy=result.strategy, trades=trades,
                  title=f"{result.config.symbol} {year} - {result.strategy.name}"), key="price")

with st.expander("Equity curve data", icon=":material/table:"):
    st.dataframe(
        curve.reset_index()[["Date", "Balance", "Equity", "CumulativeProfit", "DrawdownPct", "OpenTrades"]],
        hide_index=True,
        column_config={
            "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "Balance": st.column_config.NumberColumn(format="dollar"),
            "Equity": st.column_config.NumberColumn(format="dollar"),
            "CumulativeProfit": st.column_config.NumberColumn("Cumulative Profit", format="dollar"),
            "DrawdownPct": st.column_config.NumberColumn("Drawdown %", format="%.2f%%"),
        },
    )
