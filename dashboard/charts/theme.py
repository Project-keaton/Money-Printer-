"""Colour tokens and the Plotly template for the dark dashboard.

Palette: validated with the dataviz palette checker on the dark surface
(#1a1a19): gain/loss blue-red pair and the categorical slots all pass the
lightness, chroma, colour-vision-deficiency and contrast checks.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# Surfaces and ink
PAGE = "#0d0d0d"
SURFACE = "#1a1a19"
SURFACE_RAISED = "#242422"
INK = "#f0efec"
INK_SECONDARY = "#c3c2b7"
MUTED = "#898781"
GRID = "#2c2c2a"
BASELINE = "#383835"

# Data colours
GAIN = "#3987e5"        # profit, positive returns, equity
LOSS = "#e66767"        # loss, negative returns, drawdown
NEUTRAL = "#383835"     # diverging midpoint
SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"]
SEQUENTIAL = [[0.0, "#184f95"], [0.5, "#3987e5"], [1.0, "#b7d3f6"]]
DIVERGING = [[0.0, LOSS], [0.5, NEUTRAL], [1.0, GAIN]]

# Status (reserved for state, always shown with an icon + label)
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"
TEMPLATE = "forexbot_dark"
PLOTLY_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"], "scrollZoom": False}


def _axis(**overrides: object) -> dict[str, object]:
    axis: dict[str, object] = {
        "gridcolor": GRID, "linecolor": BASELINE, "zerolinecolor": BASELINE, "tickcolor": BASELINE,
        "tickfont": {"color": INK_SECONDARY}, "title": {"font": {"color": INK_SECONDARY}},
        "showgrid": True, "zeroline": False, "ticks": "outside", "ticklen": 4, "showline": True,
        "automargin": True,
    }
    axis.update(overrides)
    return axis


pio.templates[TEMPLATE] = go.layout.Template(
    layout={
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "colorway": SERIES,
        "font": {"family": FONT, "color": INK_SECONDARY, "size": 12},
        "title": {"font": {"color": INK, "size": 15}, "x": 0.01, "xanchor": "left", "y": 0.97, "yanchor": "top"},
        "xaxis": _axis(showgrid=False),
        "yaxis": _axis(showline=False, ticks=""),
        "hoverlabel": {"bgcolor": PAGE, "bordercolor": BASELINE, "font": {"family": FONT, "color": INK, "size": 12}},
        "legend": {"orientation": "h", "x": 0, "xanchor": "left", "y": 1.0, "yanchor": "bottom",
                   "font": {"color": INK_SECONDARY}, "bgcolor": "rgba(0,0,0,0)"},
        "margin": {"l": 64, "r": 24, "t": 72, "b": 44, "pad": 4},
        "hovermode": "closest",
        "bargap": 0.18,
    }
)


def style(fig: go.Figure, *, title: str | None = None, height: int = 380, hovermode: str | None = None,
          showlegend: bool = True) -> go.Figure:
    """Apply the dashboard template and common layout options."""
    fig.update_layout(template=TEMPLATE, height=height, showlegend=showlegend)
    if title:
        fig.update_layout(title={"text": title})
    if hovermode:
        fig.update_layout(hovermode=hovermode)
    return fig


def range_selector() -> dict[str, object]:
    """TradingView-style period buttons for time axes."""
    return {
        "buttons": [
            {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
            {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
            {"count": 3, "label": "3Y", "step": "year", "stepmode": "backward"},
            {"count": 5, "label": "5Y", "step": "year", "stepmode": "backward"},
            {"step": "all", "label": "All"},
        ],
        "bgcolor": SURFACE_RAISED, "activecolor": BASELINE, "bordercolor": BASELINE, "borderwidth": 1,
        "font": {"color": INK, "size": 11}, "x": 1, "xanchor": "right", "y": 1.02, "yanchor": "bottom",
    }


def money_axis(fig: go.Figure, row: int | None = None, col: int | None = None) -> None:
    fig.update_yaxes(tickprefix="$", tickformat=",.0f", row=row, col=col)


def empty_figure(message: str, height: int = 300) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                       font={"color": MUTED, "size": 14})
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return style(fig, height=height, showlegend=False)
