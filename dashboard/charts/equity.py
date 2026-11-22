"""Equity, growth and cumulative-profit charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import (
    BASELINE, GAIN, INK, INK_SECONDARY, LOSS, MUTED, SERIES, empty_figure, money_axis, range_selector, style,
)


def equity_curve(curve: pd.DataFrame, starting_balance: float, *, height: int = 420,
                 show_balance: bool = True, title: str = "Account equity") -> go.Figure:
    """Equity (marked to market) and closed-trade balance over time."""
    fig = go.Figure()
    if show_balance:
        fig.add_trace(go.Scatter(
            x=curve.index, y=curve["Balance"], name="Balance (closed trades)", mode="lines",
            line={"color": SERIES[1], "width": 1.5, "shape": "hv"},
            hovertemplate="Balance %{y:$,.2f}<extra></extra>",
        ))
    fig.add_trace(go.Scatter(
        x=curve.index, y=curve["Equity"], name="Equity", mode="lines", line={"color": GAIN, "width": 2},
        hovertemplate="Equity %{y:$,.2f}<extra></extra>",
    ))
    fig.add_hline(y=starting_balance, line={"color": MUTED, "width": 1, "dash": "dot"},
                  annotation_text=f"Start ${starting_balance:,.0f}", annotation_position="top left",
                  annotation_font={"color": INK_SECONDARY, "size": 11})
    last = curve["Equity"].iloc[-1]
    fig.add_annotation(x=curve.index[-1], y=last, text=f"<b>${last:,.0f}</b>", showarrow=False,
                       xanchor="left", xshift=6, font={"color": INK, "size": 12})
    fig.update_xaxes(rangeselector=range_selector())
    money_axis(fig)
    return style(fig, title=title, height=height, hovermode="x unified")


def growth_curve(curve: pd.DataFrame, *, height: int = 360) -> go.Figure:
    """Account growth in percent since the start, shaded above/below zero."""
    growth = curve["GrowthPct"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.index, y=growth.clip(lower=0), mode="lines", line={"width": 0},
                             fill="tozeroy", fillcolor="rgba(57,135,229,0.22)", hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=curve.index, y=growth.clip(upper=0), mode="lines", line={"width": 0},
                             fill="tozeroy", fillcolor="rgba(230,103,103,0.22)", hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=curve.index, y=growth, mode="lines", name="Growth", line={"color": INK_SECONDARY, "width": 1.5},
                             hovertemplate="Growth %{y:+.2f}%<extra></extra>", showlegend=False))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(rangeselector=range_selector())
    return style(fig, title="Account growth since start (%)", height=height, hovermode="x unified")


def yearly_returns_bar(yearly: pd.DataFrame, *, height: int = 340) -> go.Figure:
    colors = [GAIN if v >= 0 else LOSS for v in yearly["Return %"]]
    fig = go.Figure(go.Bar(
        x=yearly["Year"].astype(str), y=yearly["Return %"], marker={"color": colors, "cornerradius": 4},
        text=[f"{v:+.1f}%" for v in yearly["Return %"]], textposition="outside",
        textfont={"color": INK_SECONDARY, "size": 11}, cliponaxis=False,
        customdata=yearly[["Profit", "End Equity"]].to_numpy(),
        hovertemplate="<b>%{x}</b><br>Return %{y:+.2f}%<br>Profit %{customdata[0]:$,.2f}"
                      "<br>Year-end equity %{customdata[1]:$,.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(type="category")
    return style(fig, title="Return by year", height=height, showlegend=False)


def cumulative_profit(trades: pd.DataFrame, *, height: int = 380) -> go.Figure:
    """Cumulative realised profit after each closed trade."""
    if trades.empty:
        return empty_figure("No trades yet", height)
    cum = trades["Cumulative P/L"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trades["Exit Date"], y=cum, mode="lines+markers", name="Cumulative P/L",
        line={"color": GAIN, "width": 2, "shape": "hv"},
        marker={"size": 8, "color": [GAIN if v > 0 else LOSS for v in trades["Profit/Loss"]],
                "line": {"color": "#1a1a19", "width": 2}},
        customdata=trades[["Trade ID", "Trade Type", "Profit/Loss", "Exit Reason"]].to_numpy(),
        hovertemplate="<b>Trade #%{customdata[0]}</b> %{customdata[1]}<br>%{x|%d %b %Y}"
                      "<br>Trade P/L %{customdata[2]:$,.2f} (%{customdata[3]})"
                      "<br>Cumulative %{y:$,.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_xaxes(rangeselector=range_selector())
    money_axis(fig)
    return style(fig, title="Cumulative profit by closed trade", height=height, showlegend=False)
