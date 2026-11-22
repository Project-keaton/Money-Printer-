"""Writes the performance report, trade log, equity curve and charts for a backtest."""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless rendering: no display needed (servers, CI)

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402
from matplotlib.ticker import FuncFormatter, PercentFormatter  # noqa: E402

from backtests.backtester import BacktestResult  # noqa: E402
from backtests.config import PROJECT_ROOT, BacktestConfig  # noqa: E402
from backtests.performance import PerformanceMetrics, format_duration, monthly_returns, trades_to_frame  # noqa: E402

log = logging.getLogger(__name__)

# Chart palette (validated for colour-vision deficiency and contrast on the light surface).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
GAIN = "#2a78d6"      # blue: equity, profits, positive months
LOSS = "#e34948"      # red: drawdown, losses, negative months
NEUTRAL = "#f0efec"   # diverging midpoint

_WIDTH = 64


@dataclass
class ReportPaths:
    report: Path
    trades: Path
    equity_curve: Path
    monthly_returns: Path
    charts: list[Path] = field(default_factory=list)


class ReportGenerator:
    """Creates every output file for a :class:`BacktestResult`."""

    def __init__(self, reports_dir: Path, charts_dir: Path) -> None:
        self.reports_dir = reports_dir
        self.charts_dir = charts_dir

    def generate(self, result: BacktestResult, *, charts: bool = True) -> ReportPaths:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        date_format = _date_format(result.equity_curve.index)

        paths = ReportPaths(
            report=self.reports_dir / "performance_report.txt",
            trades=self.reports_dir / "trades.csv",
            equity_curve=self.reports_dir / "equity_curve.csv",
            monthly_returns=self.reports_dir / "monthly_returns.csv",
        )
        _atomic_csv(trades_to_frame(result.trades, date_format), paths.trades)
        _atomic_csv(_equity_export(result.equity_curve, date_format), paths.equity_curve)
        monthly = monthly_returns(result.equity_curve, result.config.starting_balance)
        _atomic_csv(monthly.round(2).reset_index(), paths.monthly_returns)

        if charts:
            paths.charts = self._charts(result, monthly)

        _atomic_text(render_report(result, paths), paths.report)
        log.info("Reports written to %s", self.reports_dir)
        return paths

    # ----------------------------------------------------------------- charts

    def _charts(self, result: BacktestResult, monthly: pd.DataFrame) -> list[Path]:
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        builders = (
            ("equity_curve.png", _equity_chart),
            ("drawdown.png", _drawdown_chart),
            ("monthly_returns.png", _monthly_chart),
            ("win_loss_distribution.png", _distribution_chart),
        )
        written = []
        with plt.rc_context(_STYLE):
            for filename, builder in builders:
                path = self.charts_dir / filename
                try:
                    fig = builder(result, monthly)
                    fig.savefig(path, dpi=150, facecolor=SURFACE)
                    plt.close(fig)
                    written.append(path)
                except Exception:  # a broken chart must not lose the rest of the report
                    log.exception("Could not create chart %s", filename)
                    plt.close("all")
        return written


# --------------------------------------------------------------------------- #
# Text report
# --------------------------------------------------------------------------- #


def render_report(result: BacktestResult, paths: ReportPaths | None = None) -> str:
    cfg, m = result.config, result.metrics
    ex, rk = cfg.execution, cfg.risk
    lines: list[str] = []

    def section(title: str) -> None:
        lines.extend(["", title.upper(), "-" * _WIDTH])

    def row(label: str, value: str) -> None:
        lines.append(f"  {label:<30}{value}")

    lines += ["=" * _WIDTH, f"  BACKTEST PERFORMANCE REPORT - {cfg.symbol}", "=" * _WIDTH]
    row("Generated", f"{datetime.now():%Y-%m-%d %H:%M:%S}")
    row("Strategy", result.strategy.describe())
    row("Dataset", f"{cfg.dataset} ({_rel(cfg.dataset_dir)})")
    row("Period", f"{m.start:%Y-%m-%d} -> {m.end:%Y-%m-%d} ({len(result.data):,} bars)")

    section("Account")
    row("Starting Balance", _money(m.starting_balance))
    row("Ending Balance", _money(m.ending_balance))
    if not math.isclose(m.ending_balance, m.ending_equity):
        row("Ending Equity (open trades)", _money(m.ending_equity))
    row("Total Return", _pct(m.total_return_pct))
    row("Total Profit", _money(m.total_profit))
    row("CAGR", _pct(m.cagr_pct))

    section("Trades")
    row("Total Trades", f"{m.total_trades:,}")
    row("Winning Trades", f"{m.winning_trades:,}")
    row("Losing Trades", f"{m.losing_trades:,}")
    if m.breakeven_trades:
        row("Break-even Trades", f"{m.breakeven_trades:,}")
    row("Win Rate", _pct(m.win_rate_pct, signed=False))
    row("Loss Rate", _pct(m.loss_rate_pct, signed=False))
    row("Average Winning Trade", _money(m.average_win))
    row("Average Losing Trade", _money(m.average_loss))
    row("Largest Winning Trade", _money(m.largest_win))
    row("Largest Losing Trade", _money(m.largest_loss))
    row("Average Trade Duration", format_duration(m.average_trade_duration))
    row("Expectancy Per Trade", _money(m.expectancy))
    row("Risk-Reward Ratio", _ratio(m.risk_reward_ratio))

    section("Risk-adjusted")
    row("Profit Factor", _ratio(m.profit_factor))
    row("Sharpe Ratio (annualised)", _ratio(m.sharpe_ratio))
    row("Maximum Drawdown", f"{_money(m.max_drawdown)} ({_pct(m.max_drawdown_pct)})")
    row("Time in Market", _pct(m.exposure_pct, signed=False))

    section("Costs")
    row("Gross Profit / Gross Loss", f"{_money(m.gross_profit)} / {_money(m.gross_loss)}")
    row("Total Commission", _money(m.total_commission))

    section("Settings")
    row("Spread", f"{ex.spread_pips:g} pips ({ex.price_basis} prices)")
    row("Commission", f"{_money(ex.commission_per_lot)} per lot round turn")
    row("Slippage", f"{ex.slippage_pips:g} pips")
    if rk.position_sizing == "risk":
        row("Position Sizing", f"{rk.risk_per_trade * 100:g}% of balance per trade")
    else:
        row("Position Sizing", f"fixed {rk.fixed_lots:g} lots")
    row("Stop Loss", _describe_stop(cfg))
    row("Take Profit", _describe_target(cfg))
    row("Max Open Trades", str(cfg.max_positions))
    row("Same-bar SL & TP", f"{ex.intrabar_priority.replace('_', ' ')} assumed first")

    if result.warnings:
        section("Notes")
        lines += [f"  - {w}" for w in result.warnings]

    if paths is not None:
        section("Output files")
        for path in (paths.report, paths.trades, paths.equity_curve, paths.monthly_returns, *paths.charts):
            lines.append(f"  {_rel(path)}")

    lines += ["", "=" * _WIDTH]
    return "\n".join(lines) + "\n"


def summary_lines(m: PerformanceMetrics) -> list[str]:
    """Short console summary."""
    return [
        f"Return {_pct(m.total_return_pct)} | Profit {_money(m.total_profit)} | Ending balance {_money(m.ending_balance)}",
        f"Trades {m.total_trades} | Win rate {_pct(m.win_rate_pct, signed=False)} | "
        f"Profit factor {_ratio(m.profit_factor)} | Sharpe {_ratio(m.sharpe_ratio)} | "
        f"Max drawdown {_pct(m.max_drawdown_pct)}",
    ]


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #

_STYLE = {
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": BASELINE,
    "axes.labelcolor": INK_SECONDARY,
    "axes.titlecolor": INK,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 12,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.grid.axis": "y",
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_SECONDARY,
    "ytick.labelcolor": INK_SECONDARY,
    "font.size": 10,
    "legend.frameon": False,
    "legend.labelcolor": INK_SECONDARY,
    "figure.constrained_layout.use": True,
}


def _equity_chart(result: BacktestResult, _monthly: pd.DataFrame) -> plt.Figure:
    curve = result.equity_curve
    start = result.config.starting_balance
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(curve.index, curve["Equity"], color=GAIN, linewidth=2)
    ax.axhline(start, color=MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(
        f"Starting balance {_money(start)}", xy=(curve.index[0], start), xytext=(4, 6),
        textcoords="offset points", color=INK_SECONDARY, fontsize=9,
    )
    end = curve["Equity"].iloc[-1]
    ax.annotate(
        _money(end), xy=(curve.index[-1], end), xytext=(6, 0), textcoords="offset points",
        va="center", color=INK, fontsize=9, fontweight="bold",
    )
    ax.set_title(f"Account equity - {result.config.symbol} {result.strategy.name}")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _money(v, decimals=0)))
    ax.margins(x=0.01)
    return fig


def _drawdown_chart(result: BacktestResult, _monthly: pd.DataFrame) -> plt.Figure:
    curve = result.equity_curve
    dd = curve["DrawdownPct"]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(curve.index, dd, 0, color=LOSS, alpha=0.18, linewidth=0)
    ax.plot(curve.index, dd, color=LOSS, linewidth=2)
    ax.axhline(0, color=BASELINE, linewidth=1)
    worst = dd.idxmin()
    ax.annotate(
        f"Max drawdown {dd.min():.1f}%", xy=(worst, dd.min()), xytext=(0, -8), textcoords="offset points",
        color=INK, fontsize=9, fontweight="bold", va="top", ha="center",
    )
    ax.set_title("Drawdown from peak equity")
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_ylim(bottom=min(dd.min() * 1.2, -1.0), top=0.5)
    ax.margins(x=0.01)
    return fig


def _monthly_chart(_result: BacktestResult, monthly: pd.DataFrame) -> plt.Figure:
    grid = monthly.drop(columns="Total")
    values = grid.to_numpy(dtype=float)
    limit = max(float(np.nanmax(np.abs(values))) if np.isfinite(values).any() else 1.0, 0.1)
    cmap = LinearSegmentedColormap.from_list("returns", [LOSS, NEUTRAL, GAIN])
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)

    fig, ax = plt.subplots(figsize=(12, 0.45 * len(grid) + 1.8))
    ax.imshow(np.ma.masked_invalid(values), cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(len(grid.columns)), grid.columns)
    ax.set_yticks(range(len(grid.index)), grid.index)
    ax.tick_params(length=0)
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    # 2px surface gaps between cells
    ax.set_xticks(np.arange(-0.5, len(grid.columns)), minor=True)
    ax.set_yticks(np.arange(-0.5, len(grid.index)), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)

    for (r, c), v in np.ndenumerate(values):
        if not np.isfinite(v):
            continue
        if abs(v) < 0.05:  # flat month (usually no trades): quiet label
            ax.text(c, r, "0.0", ha="center", va="center", fontsize=8, color=MUTED)
        else:
            strong = abs(v) / limit > 0.6
            ax.text(c, r, f"{v:+.1f}", ha="center", va="center", fontsize=8, color="#ffffff" if strong else INK)

    yearly = monthly["Total"]
    for r, v in enumerate(yearly):
        if np.isfinite(v):
            ax.text(len(grid.columns) - 0.35, r, f"{v:+.1f}%", ha="left", va="center", fontsize=9,
                    color=INK, fontweight="bold")
    ax.text(len(grid.columns) - 0.35, -0.85, "Total", ha="left", va="center", fontsize=9, color=INK_SECONDARY)
    ax.set_xlim(-0.5, len(grid.columns) + 0.6)
    ax.set_title("Monthly returns (%)  -  blue = gain, red = loss")
    return fig


def _distribution_chart(result: BacktestResult, _monthly: pd.DataFrame) -> plt.Figure:
    pnl = np.array([t.pnl for t in result.trades], dtype=float)
    fig, ax = plt.subplots(figsize=(11, 5))
    if pnl.size == 0:
        ax.text(0.5, 0.5, "No trades", transform=ax.transAxes, ha="center", va="center", color=MUTED)
        ax.set_title("Win/loss distribution")
        return fig

    bins = np.histogram_bin_edges(pnl, bins=min(40, max(10, pnl.size // 5)))
    if 0.0 not in bins and bins[0] < 0 < bins[-1]:
        bins = np.sort(np.append(bins, 0.0))  # never let one bar mix wins and losses
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    ax.hist(losses, bins=bins, color=LOSS, edgecolor=SURFACE, linewidth=1.5,
            label=f"Losing trades ({(pnl < 0).sum()})")
    ax.hist(wins, bins=bins, color=GAIN, edgecolor=SURFACE, linewidth=1.5,
            label=f"Winning trades ({wins.size})")
    ax.axvline(0, color=BASELINE, linewidth=1)
    ax.axvline(pnl.mean(), color=INK_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(f"Average {_money(pnl.mean())}", xy=(pnl.mean(), 1), xycoords=("data", "axes fraction"),
                xytext=(-4 if pnl.mean() < 0 else 4, -4), textcoords="offset points", va="top",
                ha="right" if pnl.mean() < 0 else "left", color=INK_SECONDARY, fontsize=9)
    ax.set_title("Win/loss distribution - profit/loss per trade")
    ax.set_xlabel("Profit/loss per trade")
    ax.set_ylabel("Number of trades")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _money(v, decimals=0)))
    ax.legend(loc="upper right")
    return fig


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _equity_export(curve: pd.DataFrame, date_format: str) -> pd.DataFrame:
    out = curve[["Balance", "Equity", "CumulativeProfit", "RealizedProfit", "Drawdown", "DrawdownPct", "OpenTrades"]]
    out = out.round({"Balance": 2, "Equity": 2, "CumulativeProfit": 2, "RealizedProfit": 2,
                     "Drawdown": 2, "DrawdownPct": 4}).reset_index()
    out["Date"] = out["Date"].dt.strftime(date_format)
    return out


def _date_format(index: pd.DatetimeIndex) -> str:
    midnight = (index.hour == 0) & (index.minute == 0)
    return "%Y-%m-%d" if midnight.all() else "%Y-%m-%d %H:%M"


def _atomic_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_csv(tmp, index=False, lineterminator="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _atomic_text(text: str, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _money(value: float, decimals: int = 2) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.{decimals}f}"


def _pct(value: float, signed: bool = True) -> str:
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def _ratio(value: float) -> str:
    if math.isnan(value):
        return "n/a"
    if math.isinf(value):
        return "inf (no losses)"
    return f"{value:.2f}"


def _describe_stop(cfg: BacktestConfig) -> str:
    sl = cfg.risk.stop_loss
    return {"pips": f"{sl.pips:g} pips", "atr": f"{sl.atr_multiplier:g} x ATR({sl.atr_period})"}.get(sl.mode, "none")


def _describe_target(cfg: BacktestConfig) -> str:
    tp = cfg.risk.take_profit
    return {
        "pips": f"{tp.pips:g} pips",
        "atr": f"{tp.atr_multiplier:g} x ATR({tp.atr_period})",
        "risk_reward": f"{tp.risk_reward:g} x stop distance",
    }.get(tp.mode, "none")


def _rel(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
