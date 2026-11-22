"""Page-level layout helpers."""

from __future__ import annotations

from html import escape
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from backtests.backtester import BacktestResult
from dashboard.charts.theme import PLOTLY_CONFIG

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def load_css() -> None:
    st.html(f"<style>{(ASSETS / 'style.css').read_text(encoding='utf-8')}</style>")


def page_header(title: str, subtitle: str = "", eyebrow: str = "ForexBot") -> None:
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.html(f'<div class="fb-header"><div class="fb-eyebrow">{escape(eyebrow)}</div>'
            f"<h1>{escape(title)}</h1>{sub}</div>")


def section(title: str, caption: str = "") -> None:
    cap = f'<div class="fb-section-caption">{escape(caption)}</div>' if caption else ""
    st.html(f'<div class="fb-section">{escape(title)}</div>{cap}')


def chart(fig: go.Figure, key: str | None = None) -> None:
    """Render a Plotly figure with the dashboard theme (not Streamlit's)."""
    st.plotly_chart(fig, theme=None, config=PLOTLY_CONFIG, key=key)


def run_subtitle(result: BacktestResult) -> str:
    """One-line description of a run: strategy, pair, dataset, period, bars."""
    m = result.metrics
    return (f"{result.strategy.describe()} · {result.config.symbol} {result.config.dataset} dataset · "
            f"{m.start:%d %b %Y} – {m.end:%d %b %Y} · {len(result.data):,} bars")
