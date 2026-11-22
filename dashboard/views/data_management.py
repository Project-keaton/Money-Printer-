"""Data management: dataset statistics, data-quality report, price chart and data updates."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import streamlit as st

from backtests.config import PROJECT_ROOT, ConfigError
from dashboard.charts.market import price_chart, rows_per_year
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import chart, page_header, section
from dashboard.utils.data_quality import DatasetQuality, latest_download_report, scan_dataset
from dashboard.utils.state import current_config, dataset_signature, rerun_backtest

page_header("Data Management", "Historical data used by the backtester, its quality, and data updates.")

try:
    cfg = current_config()
except ConfigError as exc:
    st.error(f"config.yaml is invalid: {exc}")
    st.stop()


@st.cache_data(show_spinner="Scanning data files...")
def _scan(directory: str, symbol: str, signature: str) -> DatasetQuality:  # signature: cache key only
    return scan_dataset(Path(directory), symbol)


labels = {"weekday": "Monday-Friday (data/weekday)", "raw": "Raw with Sunday candles (data/)"}
choice = st.segmented_control("Dataset", list(labels), format_func=labels.get, default=cfg.dataset, required=True)
directory = cfg.data_dir / "weekday" if choice == "weekday" else cfg.data_dir
quality = _scan(str(directory), cfg.symbol, dataset_signature(replace(cfg, dataset=choice)))

if not quality.files:
    st.warning(f"No {cfg.symbol}_<YEAR>.csv files in {directory}. Download data below.")
else:
    years = quality.years
    render_kpis([
        KPI("Total Rows", f"{quality.total_rows:,}", caption=f"{len(quality.files)} files"),
        KPI("Available Years", f"{len(years)}", caption=f"{min(years)} – {max(years)}" if years else ""),
        KPI("Missing Values", f"{quality.missing_values:,}",
            tone="positive" if not quality.missing_values else "negative",
            badge="Clean" if not quality.missing_values else "Needs attention"),
        KPI("Duplicate Records", f"{quality.duplicates:,}", tone="positive" if not quality.duplicates else "negative",
            badge="None" if not quality.duplicates else "Found"),
        KPI("Invalid OHLC Rows", f"{quality.invalid_ohlc:,}", tone="positive" if not quality.invalid_ohlc else "negative",
            badge="None" if not quality.invalid_ohlc else "Found"),
    ], columns=5)

    section("Data quality report", "Checked per file: readable, required columns, missing values, duplicate dates, OHLC consistency")
    frame = quality.to_frame()
    frame["Status"] = frame["Status"].map({"OK": "✓ OK", "Issues": "⚠ Issues"})
    st.dataframe(frame, hide_index=True, column_config={
        "Year": st.column_config.NumberColumn(format="%d"),
        "Rows": st.column_config.NumberColumn(format="%d"),
    })

    gap_days = quality.missing_trading_days
    with st.expander(f"Missing trading days: {gap_days} (weekdays with no candle, excluding 1 Jan and 25 Dec)",
                     icon=":material/event_busy:"):
        if quality.gaps:
            st.dataframe(pd.DataFrame([{"From": g.start.date(), "To": g.end.date(), "Days": g.missing_periods}
                                       for g in quality.gaps]), hide_index=True)
        else:
            st.write("No gaps found.")

    left, right = st.columns([2, 3], gap="medium")
    with left:
        chart(rows_per_year(frame), key="rows_per_year")
    with right:
        year = st.selectbox("Price chart year", sorted(years, reverse=True))
        try:
            prices = pd.read_csv(directory / f"{cfg.symbol}_{year}.csv", parse_dates=["Date"]).set_index("Date")
            chart(price_chart(prices, prices.index.min(), prices.index.max(), title=f"{cfg.symbol} {year}", height=420),
                  key="data_price")
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"Cannot chart {year}: {exc}")

report = latest_download_report(cfg.reports_dir, cfg.symbol)
if report is not None:
    with st.expander(f"Latest download summary ({report.name})", icon=":material/summarize:"):
        st.code(report.read_text(encoding="utf-8"), language=None)

section("Update data", "Runs the data pipeline. Downloads take about a minute; the backtest re-runs automatically afterwards.")
u1, u2, _ = st.columns([1, 1, 2])


def _run_pipeline(args: list[str], label: str) -> None:
    with st.status(label, expanded=True) as status:
        try:
            proc = subprocess.run([sys.executable, "-m", "data_pipeline", *args], cwd=PROJECT_ROOT,
                                  capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            status.update(label="Timed out after 30 minutes", state="error")
            return
        output = (proc.stdout + "\n" + proc.stderr).strip()
        st.code(output[-6000:] or "(no output)", language=None)
        if proc.returncode == 0:
            status.update(label=f"{label} - done", state="complete")
        else:
            status.update(label=f"{label} - finished with exit code {proc.returncode} (see output)", state="error")
    st.cache_data.clear()
    rerun_backtest()


if u1.button("Download / update data", icon=":material/cloud_download:", width="stretch",
             help="python -m data_pipeline (provider and dates from .env)"):
    _run_pipeline(["--no-progress"], "Downloading data")
if u2.button("Rebuild Monday-Friday dataset", icon=":material/build:", width="stretch",
             help="python -m data_pipeline --build-weekday (no download)"):
    _run_pipeline(["--build-weekday"], "Rebuilding Monday-Friday dataset")
