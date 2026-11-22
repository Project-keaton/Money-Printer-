"""Price charts: candlesticks with strategy indicators and trade markers."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard.charts.theme import BASELINE, GAIN, INK, INK_SECONDARY, LOSS, MUTED, SERIES, SURFACE, empty_figure, style
from strategies import EmaCrossoverStrategy, RsiReversalStrategy, Strategy
from strategies.indicators import ema, rsi

ENTRY_COLOR = SERIES[3]  # yellow: distinct from the blue/red candles


def price_chart(
    data: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    strategy: Strategy | None = None,
    trades: pd.DataFrame | None = None,
    title: str = "EUR/USD",
    height: int = 560,
) -> go.Figure:
    """Candlestick chart of ``data`` between ``start`` and ``end``.

    Indicators are computed on the full history first, so values at the start of
    the window are not distorted by warm-up.
    """
    frame = data.copy()
    frame.index = frame.index.tz_convert(None) if frame.index.tz is not None else frame.index
    overlays: dict[str, pd.Series] = {}
    rsi_series: pd.Series | None = None
    if isinstance(strategy, EmaCrossoverStrategy):
        overlays[f"EMA {strategy.fast_period}"] = ema(frame["Close"], strategy.fast_period)
        overlays[f"EMA {strategy.slow_period}"] = ema(frame["Close"], strategy.slow_period)
    if isinstance(strategy, RsiReversalStrategy):
        rsi_series = rsi(frame["Close"], strategy.period)

    window = (frame.index >= start) & (frame.index <= end)
    view = frame.loc[window]
    if view.empty:
        return empty_figure("No price data in this period", height)

    rows = 2 if rsi_series is not None else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.04,
                        row_heights=[0.72, 0.28] if rows == 2 else [1.0])
    fig.add_trace(go.Candlestick(
        x=view.index, open=view["Open"], high=view["High"], low=view["Low"], close=view["Close"], name="Price",
        increasing={"line": {"color": GAIN, "width": 1}, "fillcolor": GAIN},
        decreasing={"line": {"color": LOSS, "width": 1}, "fillcolor": LOSS},
        showlegend=False,
    ), row=1, col=1)

    for (name, series), color in zip(overlays.items(), (SERIES[1], SERIES[6])):
        fig.add_trace(go.Scatter(x=view.index, y=series[window], name=name, mode="lines",
                                 line={"color": color, "width": 1.5}, hovertemplate=name + " %{y:.5f}<extra></extra>"),
                      row=1, col=1)

    if trades is not None and not trades.empty:
        _add_trade_markers(fig, trades, start, end)

    if rsi_series is not None and isinstance(strategy, RsiReversalStrategy):
        fig.add_trace(go.Scatter(x=view.index, y=rsi_series[window], name=f"RSI {strategy.period}", mode="lines",
                                 line={"color": SERIES[6], "width": 1.5},
                                 hovertemplate="RSI %{y:.1f}<extra></extra>"), row=2, col=1)
        for level in (strategy.oversold, strategy.overbought):
            fig.add_hline(y=level, line={"color": MUTED, "width": 1, "dash": "dot"}, row=2, col=1)
        fig.update_yaxes(range=[0, 100], title="RSI", row=2, col=1)

    weekend_rows = (view.index.day_of_week >= 5).any()
    fig.update_xaxes(rangeslider_visible=False,
                     rangebreaks=[] if weekend_rows else [{"bounds": ["sat", "mon"]}])
    fig.update_yaxes(tickformat=".4f", row=1, col=1)
    return style(fig, title=title, height=height, hovermode="x unified")


def _add_trade_markers(fig: go.Figure, trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> None:
    entries = trades[(trades["Entry Date"] >= start) & (trades["Entry Date"] <= end)]
    exits = trades[(trades["Exit Date"] >= start) & (trades["Exit Date"] <= end)]
    for side, symbol in (("Buy", "triangle-up"), ("Sell", "triangle-down")):
        subset = entries[entries["Trade Type"] == side]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["Entry Date"], y=subset["Entry Price"], mode="markers", name=f"{side} entry",
            marker={"symbol": symbol, "size": 13, "color": ENTRY_COLOR, "line": {"color": SURFACE, "width": 1.5}},
            customdata=subset[["Trade ID", "Stop Loss", "Take Profit"]].to_numpy(),
            hovertemplate=f"<b>{side} #%{{customdata[0]}}</b> at %{{y:.5f}}<br>SL %{{customdata[1]:.5f}}"
                          "  TP %{customdata[2]:.5f}<extra></extra>",
        ), row=1, col=1)
    if not exits.empty:
        fig.add_trace(go.Scatter(
            x=exits["Exit Date"], y=exits["Exit Price"], mode="markers", name="Exit",
            marker={"symbol": "x-thin", "size": 12, "color": INK, "line": {"color": INK, "width": 2}},
            customdata=exits[["Trade ID", "Exit Reason", "Profit/Loss"]].to_numpy(),
            hovertemplate="<b>Exit #%{customdata[0]}</b> at %{y:.5f}<br>%{customdata[1]}"
                          "<br>P/L %{customdata[2]:$,.2f}<extra></extra>",
        ), row=1, col=1)


def rows_per_year(quality_frame: pd.DataFrame, *, height: int = 300) -> go.Figure:
    if quality_frame.empty:
        return empty_figure("No data files", height)
    fig = go.Figure(go.Bar(
        x=quality_frame["Year"].astype(str), y=quality_frame["Rows"], marker={"color": GAIN, "cornerradius": 4},
        text=quality_frame["Rows"], textposition="outside", cliponaxis=False,
        textfont={"color": INK_SECONDARY, "size": 11},
        hovertemplate="<b>%{x}</b><br>%{y:,} rows<extra></extra>",
    ))
    fig.update_xaxes(type="category")
    fig.update_yaxes(title="Rows")
    return style(fig, title="Candles per year", height=height, showlegend=False)


__all__ = ["price_chart", "rows_per_year", "BASELINE", "INK"]
