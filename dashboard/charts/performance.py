"""Trade-level performance charts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dashboard.utils.formatting import money
from dashboard.charts.theme import BASELINE, GAIN, INK_SECONDARY, LOSS, SURFACE, empty_figure, money_axis, style


def pnl_by_trade(trades: pd.DataFrame, *, height: int = 360) -> go.Figure:
    if trades.empty:
        return empty_figure("No trades yet", height)
    colors = [GAIN if v > 0 else LOSS for v in trades["Profit/Loss"]]
    fig = go.Figure(go.Bar(
        x=trades["Trade ID"], y=trades["Profit/Loss"], marker={"color": colors, "cornerradius": 3},
        customdata=trades[["Trade Type", "Exit Date", "Exit Reason", "Trade Duration"]].to_numpy(),
        hovertemplate="<b>Trade #%{x}</b> %{customdata[0]}<br>P/L %{y:$,.2f}<br>Closed %{customdata[1]|%d %b %Y}"
                      "<br>%{customdata[2]} after %{customdata[3]}<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_xaxes(title="Trade #")
    money_axis(fig)
    return style(fig, title="Profit/loss per trade", height=height, showlegend=False)


def pnl_distribution(trades: pd.DataFrame, *, height: int = 360) -> go.Figure:
    if trades.empty:
        return empty_figure("No trades yet", height)
    pnl = trades["Profit/Loss"].to_numpy(float)
    edges = np.histogram_bin_edges(pnl, bins=min(30, max(8, len(pnl) // 3)))
    size = float(edges[1] - edges[0]) if len(edges) > 1 else 1.0
    start = float(np.floor(pnl.min() / size) * size) if size else float(pnl.min())
    bins = {"start": start, "end": float(pnl.max()) + size, "size": size}  # bins aligned so 0 is an edge
    fig = go.Figure()
    for label, values, color in (("Losing trades", pnl[pnl <= 0], LOSS), ("Winning trades", pnl[pnl > 0], GAIN)):
        fig.add_trace(go.Histogram(
            x=values, xbins=bins, name=f"{label} ({len(values)})", marker={"color": color, "line": {"color": SURFACE, "width": 2}},
            hovertemplate="%{x}<br>%{y} trade(s)<extra>" + label + "</extra>",
        ))
    mean = float(pnl.mean())
    fig.add_vline(x=mean, line={"color": INK_SECONDARY, "width": 1, "dash": "dash"})
    fig.add_annotation(x=mean, y=1, yref="paper", yanchor="top", xanchor="right" if mean < 0 else "left",
                       xshift=-6 if mean < 0 else 6, showarrow=False, text=f"Average {money(mean)}",
                       font={"color": INK_SECONDARY, "size": 11})
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(tickprefix="$", tickformat=",.0f", title="Profit/loss per trade")
    fig.update_yaxes(title="Trades")
    return style(fig, title="Win/loss distribution", height=height)


def breakdown_bar(table: pd.DataFrame, by: str, *, title: str, height: int = 320) -> go.Figure:
    """Net P/L per group (e.g. exit reason or trade type) with trade counts in labels."""
    if table.empty:
        return empty_figure("No trades yet", height)
    table = table.sort_values("Profit/Loss")
    colors = [GAIN if v >= 0 else LOSS for v in table["Profit/Loss"]]
    fig = go.Figure(go.Bar(
        y=table[by], x=table["Profit/Loss"], orientation="h", marker={"color": colors, "cornerradius": 4},
        text=[f"{n} trades · {w:.0f}% win" for n, w in zip(table["Trades"], table["Win Rate %"])],
        textposition="auto", textfont={"size": 11},
        customdata=table[["Trades", "Win Rate %", "Average P/L"]].to_numpy(),
        hovertemplate="<b>%{y}</b><br>Net P/L %{x:$,.2f}<br>%{customdata[0]} trades, %{customdata[1]:.1f}% winners"
                      "<br>Average %{customdata[2]:$,.2f}<extra></extra>",
    ))
    fig.add_vline(x=0, line={"color": BASELINE, "width": 1})
    fig.update_xaxes(tickprefix="$", tickformat=",.0f", showgrid=True)
    fig.update_yaxes(showgrid=False)
    return style(fig, title=title, height=height, showlegend=False)


def duration_vs_pnl(trades: pd.DataFrame, *, height: int = 360) -> go.Figure:
    if trades.empty:
        return empty_figure("No trades yet", height)
    fig = go.Figure()
    for label, mask, color in (("Winners", trades["Profit/Loss"] > 0, GAIN), ("Losers", trades["Profit/Loss"] <= 0, LOSS)):
        subset = trades[mask]
        fig.add_trace(go.Scatter(
            x=subset["Duration (Days)"], y=subset["Profit/Loss"], mode="markers", name=label,
            marker={"color": color, "size": 10, "line": {"color": SURFACE, "width": 2}},
            customdata=subset[["Trade ID", "Trade Type", "Exit Reason"]].to_numpy(),
            hovertemplate="<b>Trade #%{customdata[0]}</b> %{customdata[1]}<br>%{x:.0f} days<br>P/L %{y:$,.2f}"
                          "<br>%{customdata[2]}<extra></extra>",
        ))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_xaxes(title="Days in trade", showgrid=True)
    money_axis(fig)
    return style(fig, title="Trade duration vs profit/loss", height=height)
