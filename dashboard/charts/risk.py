"""Drawdown and recovery charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import BASELINE, INK, INK_SECONDARY, LOSS, MUTED, empty_figure, range_selector, style


def drawdown_curve(curve: pd.DataFrame, *, height: int = 380) -> go.Figure:
    dd = curve["DrawdownPct"]
    fig = go.Figure(go.Scatter(
        x=curve.index, y=dd, mode="lines", fill="tozeroy", fillcolor="rgba(230,103,103,0.20)",
        line={"color": LOSS, "width": 2}, customdata=curve["Drawdown"],
        hovertemplate="Drawdown %{y:.2f}% (%{customdata:$,.2f})<extra></extra>",
    ))
    worst = dd.idxmin()
    fig.add_annotation(x=worst, y=dd.min(), text=f"<b>Max {dd.min():.1f}%</b>", showarrow=True, arrowhead=0,
                       arrowcolor=MUTED, ax=0, ay=28, font={"color": INK, "size": 12})
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_yaxes(ticksuffix="%", range=[min(dd.min() * 1.25, -1), 0.5])
    fig.update_xaxes(rangeselector=range_selector())
    return style(fig, title="Drawdown from peak equity (underwater curve)", height=height, showlegend=False,
                 hovermode="x unified")


def drawdown_episodes_bar(episodes: pd.DataFrame, *, height: int = 340) -> go.Figure:
    """Depth of the largest drawdowns; hover shows how long each took to recover."""
    if episodes.empty:
        return empty_figure("No drawdowns", height)
    data = episodes.sort_values("Peak Date")
    recovery = [f"{int(d)} days" if r else "not recovered" for d, r in zip(data["Days to Recover"].fillna(0), data["Recovered"])]
    labels = data["Peak Date"].dt.strftime("%b %Y")
    fig = go.Figure(go.Bar(
        x=labels, y=data["Depth %"], marker={"color": LOSS, "cornerradius": 4},
        text=[f"{v:.1f}%" for v in data["Depth %"]], textposition="outside", cliponaxis=False,
        textfont={"color": INK_SECONDARY, "size": 11},
        customdata=list(zip(data["Trough Date"].dt.strftime("%d %b %Y"), data["Total Days"], recovery)),
        hovertemplate="<b>Peak %{x}</b><br>Depth %{y:.2f}%<br>Trough %{customdata[0]}"
                      "<br>Recovery %{customdata[2]}<br>Total %{customdata[1]} days<extra></extra>",
    ))
    fig.update_yaxes(ticksuffix="%", autorange="reversed")
    fig.update_xaxes(type="category", title="Drawdown start (equity peak)")
    return style(fig, title="Largest drawdowns", height=height, showlegend=False)
