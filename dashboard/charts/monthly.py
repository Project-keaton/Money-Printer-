"""Monthly analytics charts: return heatmap, win-rate heatmap, monthly bars, seasonality."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from dashboard.charts.theme import (
    BASELINE, DIVERGING, GAIN, INK, INK_SECONDARY, LOSS, MUTED, SEQUENTIAL, SURFACE, empty_figure, style,
)
from dashboard.utils.analytics import MONTHS


def returns_heatmap(table: pd.DataFrame, *, height: int | None = None) -> go.Figure:
    grid = table[MONTHS]
    values = grid.to_numpy(dtype=float)
    if not np.isfinite(values).any():
        return empty_figure("No monthly data", 300)
    limit = max(float(np.nanmax(np.abs(values))), 0.1)
    text = [["" if not np.isfinite(v) else ("0.0" if abs(v) < 0.05 else f"{v:+.1f}") for v in row] for row in values]
    totals = table["Total"].to_numpy(dtype=float)
    fig = go.Figure(go.Heatmap(
        z=values, x=MONTHS, y=[str(y) for y in grid.index], zmin=-limit, zmax=limit, zmid=0,
        colorscale=DIVERGING, xgap=2, ygap=2, text=text, texttemplate="%{text}",
        textfont={"size": 11, "color": INK},
        customdata=np.repeat(totals[:, None], len(MONTHS), axis=1),
        hovertemplate="<b>%{x} %{y}</b><br>Return %{z:+.2f}%<br>Year %{customdata:+.2f}%<extra></extra>",
        showscale=False,  # every cell is labelled; the title explains the colours
    ))
    # Row positions are category indexes: a y value like "2016" would be read as the number 2016.
    for row, total in enumerate(totals):
        if np.isfinite(total):
            fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=8, y=row, text=f"<b>{total:+.1f}%</b>",
                               showarrow=False, font={"color": INK, "size": 11})
    fig.add_annotation(x=1.0, xref="paper", xanchor="left", xshift=8, y=1.0, yref="paper", yanchor="bottom",
                       text="Year", showarrow=False, font={"color": MUTED, "size": 11})
    fig.update_yaxes(autorange="reversed", showgrid=False, type="category")
    fig.update_xaxes(showgrid=False, side="top", showline=False, ticks="")
    fig.update_layout(margin={"r": 70})
    return style(fig, title="Monthly returns (%) - blue = gain, red = loss, grey = flat", height=height or 70 + 34 * len(grid), showlegend=False)


def win_rate_heatmap(stats: pd.DataFrame, years: list[int], *, height: int | None = None) -> go.Figure:
    if stats.empty:
        return empty_figure("No trades yet", 300)
    rate = stats.pivot(index="Year", columns="Month", values="Win Rate %").reindex(index=years, columns=range(1, 13))
    count = stats.pivot(index="Year", columns="Month", values="Trades").reindex(index=years, columns=range(1, 13))
    pnl = stats.pivot(index="Year", columns="Month", values="Profit/Loss").reindex(index=years, columns=range(1, 13))
    values = rate.to_numpy(dtype=float)
    fig = go.Figure(go.Heatmap(
        z=values, x=MONTHS, y=[str(y) for y in years], zmin=0, zmax=100,
        colorscale=SEQUENTIAL, xgap=2, ygap=2,
        customdata=np.dstack([count.fillna(0).to_numpy(), pnl.fillna(0).to_numpy()]),
        hovertemplate="<b>%{x} %{y}</b><br>Win rate %{z:.0f}%<br>%{customdata[0]:.0f} trade(s) closed"
                      "<br>P/L %{customdata[1]:$,.2f}<extra></extra>",
        colorbar={"ticksuffix": "%", "outlinewidth": 0, "tickfont": {"color": INK_SECONDARY}, "thickness": 12},
    ))
    # Per-cell label colour: light ink on dark cells, dark ink on light cells.
    for r in range(len(years)):
        for c in range(len(MONTHS)):
            v = values[r, c]
            if np.isfinite(v):
                fig.add_annotation(x=c, y=r, text=f"{v:.0f}%", showarrow=False,
                                   font={"size": 11, "color": SURFACE if v >= 60 else INK})
    fig.update_yaxes(autorange="reversed", showgrid=False, type="category")
    fig.update_xaxes(showgrid=False, side="top", showline=False, ticks="")
    return style(fig, title="Monthly win rate (trades closed in the month; blank = no trades)",
                 height=height or 70 + 34 * len(years), showlegend=False)


def monthly_returns_bar(series: pd.Series, *, height: int = 340) -> go.Figure:
    if series.empty:
        return empty_figure("No monthly data", height)
    colors = [GAIN if v >= 0 else LOSS for v in series]
    fig = go.Figure(go.Bar(x=series.index, y=series.to_numpy(), marker={"color": colors},
                           hovertemplate="%{x|%b %Y}<br>%{y:+.2f}%<extra></extra>"))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_yaxes(ticksuffix="%")
    fig.update_layout(bargap=0.1)
    return style(fig, title="Monthly returns over time", height=height, showlegend=False)


def seasonality_bar(series: pd.Series, *, height: int = 320) -> go.Figure:
    """Average return for each calendar month across all years."""
    if series.empty:
        return empty_figure("No monthly data", height)
    by_month = series.groupby(series.index.month)
    avg = by_month.mean().reindex(range(1, 13))
    positive = by_month.apply(lambda s: (s > 0).mean() * 100).reindex(range(1, 13))
    colors = [GAIN if (v or 0) >= 0 else LOSS for v in avg]
    fig = go.Figure(go.Bar(
        x=MONTHS, y=avg.to_numpy(), marker={"color": colors, "cornerradius": 4},
        customdata=positive.to_numpy(),
        hovertemplate="<b>%{x}</b><br>Average %{y:+.2f}%<br>Positive in %{customdata:.0f}% of years<extra></extra>",
    ))
    fig.add_hline(y=0, line={"color": BASELINE, "width": 1})
    fig.update_yaxes(ticksuffix="%")
    return style(fig, title="Average return by calendar month", height=height, showlegend=False)
