"""Trade history: searchable, filterable, sortable table of every trade."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import page_header, run_subtitle
from dashboard.utils import formatting as fmt
from dashboard.utils.analytics import trade_frame
from dashboard.utils.state import require_result

result = require_result()
trades = trade_frame(result)

page_header("Trade History", run_subtitle(result))

if trades.empty:
    st.info("The strategy produced no trades with the current settings.")
    st.stop()

# ------------------------------------------------------------------ filters
c1, c2, c3, c4 = st.columns([3, 2, 2, 3], vertical_alignment="bottom")
with c1:
    search = st.text_input("Search", placeholder="Trade ID, type, exit reason or date (e.g. 2021-03)",
                           help="Matches any part of the ID, type, exit reason, entry or exit date")
with c2:
    sides = st.multiselect("Trade type", ["Buy", "Sell"], default=["Buy", "Sell"])
with c3:
    outcome = st.segmented_control("Outcome", ["All", "Winners", "Losers"], default="All")
with c4:
    reasons_available = sorted(trades["Exit Reason"].unique())
    reasons = st.multiselect("Exit reason", reasons_available, default=reasons_available)

first, last = trades["Entry Date"].min().date(), trades["Exit Date"].max().date()
d1, d2 = st.columns([2, 3], vertical_alignment="bottom")
with d1:
    period = st.date_input("Entry date range", value=(first, last), min_value=first, max_value=last)
with d2:
    show_all = st.toggle("Show all columns (stop loss, take profit, lots, pips, balance ...)", value=False)

filtered = trades[trades["Trade Type"].isin(sides) & trades["Exit Reason"].isin(reasons)]
if outcome == "Winners":
    filtered = filtered[filtered["Profit/Loss"] > 0]
elif outcome == "Losers":
    filtered = filtered[filtered["Profit/Loss"] < 0]
if isinstance(period, tuple) and len(period) == 2:
    lo, hi = pd.Timestamp(period[0]), pd.Timestamp(period[1]) + pd.Timedelta(days=1)
    filtered = filtered[(filtered["Entry Date"] >= lo) & (filtered["Entry Date"] < hi)]
if search.strip():
    needle = search.strip().lower()
    haystack = (
        filtered["Trade ID"].astype(str) + " " + filtered["Trade Type"] + " " + filtered["Exit Reason"] + " "
        + filtered["Entry Date"].dt.strftime("%Y-%m-%d") + " " + filtered["Exit Date"].dt.strftime("%Y-%m-%d")
    ).str.lower()
    filtered = filtered[haystack.str.contains(needle, regex=False)]

# ------------------------------------------------------------------ summary
pnl = filtered["Profit/Loss"]
render_kpis([
    KPI("Trades shown", f"{len(filtered):,} of {len(trades):,}"),
    KPI("Net P/L", fmt.signed_money(float(pnl.sum())), tone=fmt.tone(float(pnl.sum()))),
    KPI("Win rate", fmt.pct((pnl > 0).mean() * 100 if len(pnl) else 0.0)),
    KPI("Average P/L", fmt.signed_money(float(pnl.mean()) if len(pnl) else 0.0), tone=fmt.tone(float(pnl.mean()) if len(pnl) else 0.0)),
], columns=4)

# -------------------------------------------------------------------- table
base_columns = ["Trade ID", "Entry Date", "Exit Date", "Trade Type", "Entry Price", "Exit Price",
                "Profit/Loss", "Trade Duration"]
extra_columns = ["Outcome", "Exit Reason", "Stop Loss", "Take Profit", "Lots", "Pips", "Return %",
                 "Commission", "Balance After", "Cumulative P/L"]
columns = base_columns + (extra_columns if show_all else ["Outcome", "Exit Reason"])
view = filtered[columns].copy()
view["Outcome"] = view["Outcome"].map({"Win": "▲ Win", "Loss": "▼ Loss", "Break-even": "● Even"})

st.dataframe(
    view,
    hide_index=True,
    height=min(38 + 35 * len(view), 640),
    column_config={
        "Trade ID": st.column_config.NumberColumn("ID", format="%d", width="small"),
        "Entry Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "Exit Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
        "Trade Type": st.column_config.TextColumn("Type", width="small"),
        "Entry Price": st.column_config.NumberColumn(format="%.5f"),
        "Exit Price": st.column_config.NumberColumn(format="%.5f"),
        "Stop Loss": st.column_config.NumberColumn(format="%.5f"),
        "Take Profit": st.column_config.NumberColumn(format="%.5f"),
        "Profit/Loss": st.column_config.NumberColumn(format="dollar"),
        "Trade Duration": st.column_config.TextColumn("Duration"),
        "Lots": st.column_config.NumberColumn(format="%.2f"),
        "Pips": st.column_config.NumberColumn(format="%.1f"),
        "Return %": st.column_config.NumberColumn(format="%.2f%%"),
        "Commission": st.column_config.NumberColumn(format="dollar"),
        "Balance After": st.column_config.NumberColumn(format="dollar"),
        "Cumulative P/L": st.column_config.NumberColumn(format="dollar"),
    },
)
st.caption("Click a column header to sort. Duration is measured between the entry and exit bars.")

export = filtered.drop(columns=["Duration", "Units"]).copy()
for column in ("Entry Date", "Exit Date"):
    export[column] = export[column].dt.strftime("%Y-%m-%d")
st.download_button("Download filtered trades (CSV)", export.to_csv(index=False).encode("utf-8"),
                   file_name="trades_filtered.csv", mime="text/csv", icon=":material/download:")
