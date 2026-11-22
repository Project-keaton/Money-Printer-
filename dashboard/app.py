"""ForexBot dashboard - Streamlit entry point.

Run from the project root:

    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project packages (backtests, strategies, data_pipeline, dashboard) importable
# when Streamlit runs this file as a script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from dashboard.components.layout import load_css  # noqa: E402
from dashboard.components.sidebar import render_sidebar  # noqa: E402
from dashboard.utils.state import init_logging  # noqa: E402

# Page scripts live in views/: a folder named "pages" would switch Streamlit to its
# legacy file-based routing, which breaks refreshing or bookmarking a page.
PAGES_DIR = Path(__file__).resolve().parent / "views"

st.set_page_config(
    page_title="ForexBot Dashboard",
    page_icon=":material/candlestick_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_logging()
load_css()
st.logo(str(Path(__file__).resolve().parent / "assets" / "logo.svg"), size="large")


def page(file: str, title: str, icon: str, default: bool = False) -> st.Page:
    return st.Page(PAGES_DIR / file, title=title, icon=icon, default=default)


navigation = st.navigation({
    "Results": [
        page("overview.py", "Overview", ":material/dashboard:", default=True),
        page("backtest_results.py", "Backtest Results", ":material/show_chart:"),
        page("trade_history.py", "Trade History", ":material/receipt_long:"),
        page("performance.py", "Performance Analytics", ":material/insights:"),
        page("risk_analysis.py", "Risk Analysis", ":material/trending_down:"),
        page("monthly.py", "Monthly Analytics", ":material/calendar_month:"),
    ],
    "Setup": [
        page("strategy_settings.py", "Strategy Settings", ":material/tune:"),
        page("data_management.py", "Data Management", ":material/database:"),
    ],
})
render_sidebar()
navigation.run()
