"""Sidebar: brand, current run summary and actions."""

from __future__ import annotations

from html import escape

import streamlit as st

from backtests.report_generator import ReportGenerator
from dashboard.utils import formatting as fmt
from dashboard.utils.state import clear_overrides, get_overrides, get_result, rerun_backtest


def render_sidebar() -> None:
    with st.sidebar:
        st.html('<div class="fb-section-caption" style="margin-top:0.5rem">CURRENT BACKTEST</div>')
        result = get_result()
        if result is None:
            return

        m = result.metrics
        rows = [
            ("Strategy", result.strategy.name),
            ("Pair", result.config.symbol),
            ("Period", f"{m.start:%Y} – {m.end:%Y}"),
            ("Trades", fmt.integer(m.total_trades)),
            ("Return", fmt.pct(m.total_return_pct, signed=True)),
            ("Balance", fmt.money(m.ending_balance)),
        ]
        body = "".join(f'<div class="fb-run-row"><span>{escape(k)}</span><span>{escape(v)}</span></div>' for k, v in rows)
        pill = '<span class="fb-pill">Unsaved settings</span>' if get_overrides() else ""
        st.html(f'<div class="fb-run">{pill}{body}</div>')

        if get_overrides() and st.button("Reset to config.yaml", icon=":material/restart_alt:", width="stretch"):
            clear_overrides()
            st.rerun()
        if st.button("Re-run backtest", icon=":material/refresh:", width="stretch",
                     help="Run again, e.g. after editing config.yaml by hand"):
            rerun_backtest()
            st.rerun()
        if st.button("Export reports", icon=":material/download:", width="stretch",
                     help="Write performance_report.txt, trades.csv, equity_curve.csv and charts to reports/"):
            with st.spinner("Writing reports..."):
                paths = ReportGenerator(result.config.reports_dir, result.config.charts_dir).generate(result)
            st.toast(f"Reports saved to {paths.report.parent}", icon=":material/check_circle:")
