"""KPI cards in the style of trading-platform summary tiles."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

import streamlit as st

Tone = Literal["positive", "negative", "neutral"]
_ICONS: dict[str, str] = {"positive": "▲", "negative": "▼", "neutral": "●"}


@dataclass(frozen=True, slots=True)
class KPI:
    """One summary tile.

    ``value`` is always shown in the primary text colour; direction is conveyed
    by the accent bar and an optional badge that pairs an icon with a word, so
    the meaning never depends on colour alone.
    """

    label: str
    value: str
    caption: str = ""
    tone: Tone = "neutral"
    badge: str = ""
    help: str = ""


def kpi_html(kpi: KPI) -> str:
    badge = ""
    if kpi.badge:
        badge = (f'<span class="kpi-badge {kpi.tone}"><span class="icon">{_ICONS[kpi.tone]}</span>'
                 f"{escape(kpi.badge)}</span>")
    caption = f'<span class="kpi-caption">{escape(kpi.caption)}</span>' if kpi.caption else ""
    title = f' title="{escape(kpi.help)}"' if kpi.help else ""
    return (
        f'<div class="kpi-card {kpi.tone}"{title}>'
        f'<div class="kpi-label">{escape(kpi.label)}</div>'
        f'<div class="kpi-value">{escape(kpi.value)}</div>'
        f'<div class="kpi-foot">{badge}{caption}</div>'
        "</div>"
    )


def render_kpis(kpis: list[KPI], columns: int = 5) -> None:
    """Render cards in a responsive grid (collapses to 3 or 2 columns on narrow screens)."""
    cards = "".join(kpi_html(k) for k in kpis)
    st.html(f'<div class="kpi-grid" style="--kpi-cols:{columns}">{cards}</div>')
