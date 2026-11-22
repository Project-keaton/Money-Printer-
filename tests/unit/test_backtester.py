"""Unit tests for the backtesting engine (synthetic data, no files needed unless tmp_path)."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtests.backtester import Backtester, plan_order_distances
from backtests.config import (
    PROJECT_ROOT,
    BacktestConfig,
    ConfigError,
    ExecutionSettings,
    RiskSettings,
    load_config,
)
from backtests.data_loader import DataLoadError, load_market_data
from backtests.performance import TRADE_COLUMNS, build_equity_curve, compute_metrics, monthly_returns, trades_to_frame
from backtests.report_generator import ReportGenerator
from backtests.trade_engine import ExitReason, Side, TradeEngine
from strategies import EmaCrossoverStrategy, RsiReversalStrategy, StrategyError, create_strategy, normalise_signals
from strategies.indicators import atr, ema, rsi

NO_COSTS = ExecutionSettings(spread_pips=0.0, commission_per_lot=0.0, slippage_pips=0.0)


def make_config(**kwargs: object) -> BacktestConfig:
    base = BacktestConfig(execution=NO_COSTS, risk=RiskSettings())
    return replace(base, **kwargs)  # type: ignore[arg-type]


def make_bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(rows), freq="D", tz="UTC", name="Date")
    frame = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=index)
    frame["Volume"] = 1000.0
    return frame


def make_signals(bars: pd.DataFrame, at: dict[int, int], stop: float = 0.0050, target: float = 0.0100,
                 **flags: dict[int, bool]) -> pd.DataFrame:
    raw = pd.DataFrame({"signal": 0}, index=bars.index)
    for i, value in at.items():
        raw.iloc[i, 0] = value
    for column, positions in flags.items():
        raw[column] = False
        for i in positions:
            raw.iloc[i, raw.columns.get_loc(column)] = True
    signals = normalise_signals(raw, bars.index)
    signals["stop_distance"] = stop
    signals["target_distance"] = target
    return signals


FLAT = (1.1000, 1.1005, 1.0995, 1.1000)


# ------------------------------------------------------------------ engine


def test_long_take_profit_with_risk_sizing() -> None:
    bars = make_bars([FLAT, (1.1000, 1.1050, 1.0990, 1.1040), (1.1040, 1.1120, 1.1030, 1.1110), FLAT])
    result = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1}))

    (trade,) = result.trades
    assert trade.side is Side.BUY
    assert trade.entry_time == bars.index[1]  # signal at bar 0 close -> fill at bar 1 open
    assert trade.entry_price == pytest.approx(1.1000)
    assert trade.stop_loss == pytest.approx(1.0950) and trade.take_profit == pytest.approx(1.1100)
    assert trade.units == pytest.approx(20_000)  # $100 risk / 0.0050 stop
    assert trade.lots == pytest.approx(0.2)
    assert trade.exit_reason is ExitReason.TAKE_PROFIT
    assert trade.exit_price == pytest.approx(1.1100)
    assert trade.pnl == pytest.approx(200.0)
    assert trade.return_pct == pytest.approx(2.0)
    assert trade.pips == pytest.approx(100.0)
    assert result.final_balance == pytest.approx(10_200.0)


def test_short_stop_loss_fills_at_gap_open() -> None:
    bars = make_bars([FLAT, FLAT, (1.1080, 1.1090, 1.1070, 1.1085), FLAT])
    (trade,) = TradeEngine(make_config()).run(bars, make_signals(bars, {0: -1})).trades

    assert trade.side is Side.SELL
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.exit_price == pytest.approx(1.1080)  # gapped above the 1.1050 stop
    assert trade.pnl == pytest.approx(-160.0)


@pytest.mark.parametrize(("priority", "reason", "pnl"), [
    ("stop_loss", ExitReason.STOP_LOSS, -100.0),
    ("take_profit", ExitReason.TAKE_PROFIT, 200.0),
])
def test_bar_touching_both_levels_uses_priority(priority: str, reason: ExitReason, pnl: float) -> None:
    bars = make_bars([FLAT, FLAT, (1.1000, 1.1150, 1.0900, 1.1000), FLAT])
    config = make_config(execution=replace(NO_COSTS, intrabar_priority=priority))
    (trade,) = TradeEngine(config).run(bars, make_signals(bars, {0: 1})).trades
    assert trade.exit_reason is reason
    assert trade.pnl == pytest.approx(pnl)


def test_spread_slippage_and_commission_are_applied() -> None:
    bars = make_bars([FLAT, FLAT, FLAT])
    config = make_config(execution=ExecutionSettings(spread_pips=1.0, commission_per_lot=7.0, slippage_pips=0.2))
    (trade,) = TradeEngine(config).run(bars, make_signals(bars, {0: 1})).trades

    assert trade.entry_price == pytest.approx(1.1000 + 0.00005 + 0.00002)  # ask + slippage
    assert trade.exit_reason is ExitReason.END_OF_DATA
    assert trade.exit_price == pytest.approx(1.1000 - 0.00005 - 0.00002)  # bid - slippage at last close
    assert trade.commission == pytest.approx(7.0 * trade.lots)
    expected_gross = (trade.exit_price - trade.entry_price) * trade.units
    assert trade.gross_pnl == pytest.approx(expected_gross)
    assert trade.pnl == pytest.approx(expected_gross - trade.commission)
    assert trade.pips == pytest.approx(-1.4)  # 1 pip spread + 2 x 0.2 pip slippage


def test_bid_price_basis_charges_full_spread_on_buys() -> None:
    bars = make_bars([FLAT, FLAT, FLAT])
    config = make_config(execution=replace(NO_COSTS, price_basis="bid", spread_pips=1.0))
    (trade,) = TradeEngine(config).run(bars, make_signals(bars, {0: 1})).trades
    assert trade.entry_price == pytest.approx(1.1001)
    assert trade.exit_price == pytest.approx(1.1000)


def test_signal_on_last_bar_is_not_executed() -> None:
    bars = make_bars([FLAT, FLAT, FLAT])
    result = TradeEngine(make_config()).run(bars, make_signals(bars, {2: 1}))
    assert result.trades == []
    assert result.skipped_entries["signal on last bar"] == 1


def test_single_position_mode_ignores_extra_signals() -> None:
    bars = make_bars([FLAT] * 6)
    signals = make_signals(bars, {0: 1, 1: 1, 2: 1})
    single = TradeEngine(make_config()).run(bars, signals)
    multi = TradeEngine(make_config(allow_multiple_positions=True, max_open_trades=2)).run(bars, signals)

    assert len(single.trades) == 1 and single.skipped_entries["max open trades reached"] == 2
    assert len(multi.trades) == 2 and multi.skipped_entries["max open trades reached"] == 1


def test_opposite_signal_closes_and_reverses() -> None:
    bars = make_bars([FLAT] * 5)
    trades = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1, 2: -1})).trades

    assert [t.side for t in trades] == [Side.BUY, Side.SELL]
    assert trades[0].exit_reason is ExitReason.OPPOSITE_SIGNAL
    assert trades[0].exit_time == trades[1].entry_time == bars.index[3]


def test_exit_signal_closes_position() -> None:
    bars = make_bars([FLAT] * 5)
    trades = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1}, exit_long=[2])).trades
    assert trades[0].exit_reason is ExitReason.SIGNAL and trades[0].exit_time == bars.index[3]


def test_leverage_cap_and_minimum_lot() -> None:
    bars = make_bars([FLAT] * 3)
    capped = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1}, stop=0.0001)).trades[0]
    assert capped.lots == pytest.approx(2.72)  # 10,000 x 30 / 1.10 = 272,727 units -> 2.72 lots

    tiny = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1}, stop=1.0))
    assert tiny.trades == [] and tiny.skipped_entries["position below minimum lot"] == 1


def test_missing_stop_distance_skips_entry_with_risk_sizing() -> None:
    bars = make_bars([FLAT] * 3)
    result = TradeEngine(make_config()).run(bars, make_signals(bars, {0: 1}, stop=float("nan")))
    assert result.trades == [] and result.skipped_entries["no stop distance (indicator warm-up)"] == 1


def test_equity_curve_marks_open_trades_to_market() -> None:
    bars = make_bars([FLAT, FLAT, (1.1000, 1.1030, 1.0990, 1.1020), FLAT])
    config = make_config(close_open_trades_at_end=False)
    curve = TradeEngine(config).run(bars, make_signals(bars, {0: 1})).equity_curve
    assert curve.loc[bars.index[2], "Equity"] == pytest.approx(10_000 + 0.0020 * 20_000)
    assert curve.loc[bars.index[2], "Balance"] == pytest.approx(10_000)
    assert curve["OpenTrades"].tolist() == [0, 1, 1, 1]


# ----------------------------------------------------------- order planning


def test_plan_order_distances_modes() -> None:
    bars = make_bars([FLAT] * 20)
    signals = normalise_signals(pd.Series(0, index=bars.index), bars.index)
    config = make_config()
    planned = plan_order_distances(bars, signals, config.risk, config.instrument)  # ATR x2, RR 2
    expected_stop = atr(bars, 14) * 2
    pd.testing.assert_series_equal(planned["stop_distance"], expected_stop, check_names=False)
    pd.testing.assert_series_equal(planned["target_distance"], expected_stop * 2, check_names=False)

    pips_risk = replace(config.risk, stop_loss=replace(config.risk.stop_loss, mode="pips", pips=25))
    planned = plan_order_distances(bars, signals, pips_risk, config.instrument)
    assert planned["stop_distance"].iloc[0] == pytest.approx(0.0025)
    assert planned["target_distance"].iloc[0] == pytest.approx(0.0050)


# ------------------------------------------------------------------ metrics


def test_metrics_from_known_trades() -> None:
    bars = make_bars([
        FLAT, (1.1000, 1.1110, 1.0990, 1.1100),               # bar1: long #1 -> TP +200
        FLAT, (1.1000, 1.1005, 1.0940, 1.0960),               # bar3: long #2 -> SL -100
        FLAT, (1.1000, 1.1110, 1.0990, 1.1100), FLAT,         # bar5: long #3 -> TP
    ])
    signals = make_signals(bars, {0: 1, 2: 1, 4: 1})
    engine = TradeEngine(make_config()).run(bars, signals)
    curve = build_equity_curve(engine.equity_curve, 10_000)
    m = compute_metrics(engine.trades, curve, 10_000)

    pnl = [t.pnl for t in engine.trades]
    # Trade 2 risks 1% of $10,200 = $102 -> 0.204 lots, rounded down to the 0.01 lot step = 0.20 lots.
    assert [t.lots for t in engine.trades] == pytest.approx([0.20, 0.20, 0.20])
    assert pnl == pytest.approx([200.0, -100.0, 200.0])
    assert (m.total_trades, m.winning_trades, m.losing_trades) == (3, 2, 1)
    assert m.win_rate_pct == pytest.approx(200 / 3) and m.loss_rate_pct == pytest.approx(100 / 3)
    assert m.profit_factor == pytest.approx(4.0)
    assert m.expectancy == pytest.approx(100.0)
    assert m.risk_reward_ratio == pytest.approx(2.0)
    assert m.average_win == pytest.approx(200.0) and m.average_loss == pytest.approx(-100.0)
    assert m.largest_win == pytest.approx(200) and m.largest_loss == pytest.approx(-100)
    assert m.ending_balance == pytest.approx(10_300.0)
    assert m.total_return_pct == pytest.approx(3.0)
    assert m.max_drawdown == pytest.approx(-100.0)
    assert m.max_drawdown_pct == pytest.approx(-100 / 10_200 * 100)
    assert m.average_trade_duration == pd.Timedelta(0)  # each trade opened and closed in one bar
    assert not math.isnan(m.sharpe_ratio)

    frame = trades_to_frame(engine.trades)
    assert list(frame.columns) == TRADE_COLUMNS
    assert frame["Cumulative P/L"].iloc[-1] == pytest.approx(sum(pnl), abs=0.01)


def test_metrics_without_trades() -> None:
    curve = build_equity_curve(
        pd.DataFrame({"Balance": 10_000.0, "Equity": 10_000.0, "OpenTrades": 0},
                     index=pd.date_range("2024-01-01", periods=5, tz="UTC")), 10_000)
    m = compute_metrics([], curve, 10_000)
    assert m.total_trades == 0 and math.isnan(m.profit_factor) and math.isnan(m.sharpe_ratio)
    assert m.average_trade_duration is None


def test_monthly_returns_table() -> None:
    index = pd.to_datetime(["2024-01-15", "2024-01-31", "2024-02-29", "2025-01-31"], utc=True)
    curve = pd.DataFrame({"Equity": [10_000.0, 10_100.0, 9_999.0, 10_999.0]}, index=index)
    table = monthly_returns(curve, 10_000)
    assert table.loc[2024, "Jan"] == pytest.approx(1.0)
    assert table.loc[2024, "Feb"] == pytest.approx(-1.0)
    assert table.loc[2024, "Total"] == pytest.approx(-0.01)
    assert table.loc[2025, "Jan"] == pytest.approx((10_999 / 9_999 - 1) * 100)
    assert math.isnan(table.loc[2024, "Mar"])


# --------------------------------------------------------------- indicators


def test_indicators() -> None:
    rising = pd.Series(np.arange(1.0, 40.0))
    assert rsi(rising, 14).dropna().eq(100.0).all()
    assert ema(rising, 10).iloc[:9].isna().all() and not math.isnan(ema(rising, 10).iloc[9])

    bars = make_bars([(1.0, 1.02, 0.99, 1.0)] * 30)
    assert atr(bars, 14).dropna().iloc[-1] == pytest.approx(0.03)


# --------------------------------------------------------------- strategies


def test_ema_crossover_signals_on_crosses_only() -> None:
    closes = [1.0] * 10 + [1.0 + 0.01 * i for i in range(1, 15)] + [1.14 - 0.02 * i for i in range(1, 15)]
    bars = make_bars([(c, c, c, c) for c in closes])
    signals = EmaCrossoverStrategy(fast_period=3, slow_period=8).generate_signals(bars)["signal"]
    assert (signals == 1).sum() == 1 and (signals == -1).sum() == 1
    assert signals[signals == 1].index[0] < signals[signals == -1].index[0]


def test_strategy_validation_and_registry() -> None:
    with pytest.raises(StrategyError):
        EmaCrossoverStrategy(fast_period=50, slow_period=20)
    with pytest.raises(StrategyError):
        RsiReversalStrategy(oversold=60, exit_level=50)
    with pytest.raises(StrategyError, match="Unknown strategy"):
        create_strategy("does_not_exist")
    with pytest.raises(StrategyError, match="Invalid parameters"):
        create_strategy("ema_crossover", {"fast": 3})
    assert isinstance(create_strategy("rsi_reversal", {"period": 10}), RsiReversalStrategy)


def test_normalise_signals_rejects_bad_output() -> None:
    index = pd.date_range("2024-01-01", periods=3, tz="UTC")
    with pytest.raises(StrategyError, match="1, -1 or 0"):
        normalise_signals(pd.Series([0, 2, 0], index=index), index)
    with pytest.raises(StrategyError, match="same index"):
        normalise_signals(pd.Series([0, 1], index=index[:2]), index)


# ------------------------------------------------------------- data loader


def _write_year(directory: Path, year: int, rows: int = 5) -> None:
    dates = pd.bdate_range(f"{year}-03-01", periods=rows)
    pd.DataFrame({"Date": dates.strftime("%Y-%m-%d"), "Open": 1.1, "High": 1.11, "Low": 1.09,
                  "Close": 1.1, "Volume": 10.0}).to_csv(directory / f"EURUSD_{year}.csv", index=False)


def test_loader_combines_years_and_skips_corrupted_files(tmp_path: Path) -> None:
    _write_year(tmp_path, 2020)
    _write_year(tmp_path, 2021)
    (tmp_path / "EURUSD_2022.csv").write_bytes(b"\x00\xff garbage \x00")
    (tmp_path / "EURUSD_2023.csv").write_text("Date,Open\n2023-01-02,1.1\n")
    (tmp_path / "GBPUSD_2020.csv").write_text("ignored")

    data, report = load_market_data(tmp_path, "EURUSD")

    assert len(data) == 10 and data.index.is_monotonic_increasing
    assert [p.name for p in report.files_loaded] == ["EURUSD_2020.csv", "EURUSD_2021.csv"]
    assert {p.name for p, _ in report.files_failed} == {"EURUSD_2022.csv", "EURUSD_2023.csv"}
    assert any("EURUSD_2023.csv" in w for w in report.warnings)

    filtered, _ = load_market_data(tmp_path, "EURUSD", start=pd.Timestamp("2021-01-01").date())
    assert filtered.index.min().year == 2021


def test_loader_errors(tmp_path: Path) -> None:
    with pytest.raises(DataLoadError, match="not found"):
        load_market_data(tmp_path / "missing", "EURUSD")
    with pytest.raises(DataLoadError, match="python -m data_pipeline"):
        load_market_data(tmp_path, "EURUSD")


# ------------------------------------------------------------------ config


def test_project_config_loads_and_overrides() -> None:
    config = load_config(PROJECT_ROOT / "config.yaml", {"execution.spread_pips": 0.5, "strategy.active": "rsi_reversal"})
    assert config.execution.spread_pips == 0.5
    assert config.strategy_name == "rsi_reversal" and "period" in config.strategy_params
    assert config.instrument.pip_size == 0.0001
    assert config.dataset_dir.name == "weekday"


@pytest.mark.parametrize("yaml_text, message", [
    ("execution:\n  spread_pips: -1\n", "spread_pips"),
    ("risk:\n  stop_loss:\n    mode: none\n", "needs a stop loss"),
    ("backtest:\n  dataset: hourly\n", "dataset"),
    ("backtest:\n  allow_multiple_positions: maybe\n", "true or false"),
])
def test_invalid_config_values(tmp_path: Path, yaml_text: str, message: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text)
    with pytest.raises(ConfigError, match=message):
        load_config(path)


# -------------------------------------------------------------- end to end


def test_backtest_and_reports_end_to_end(tmp_path: Path) -> None:
    t = np.arange(600)
    close = 1.10 + 0.03 * np.sin(t / 25) + 0.002 * np.sin(t / 3)
    bars = make_bars([(c, c + 0.004, c - 0.004, c) for c in close])
    config = make_config(execution=ExecutionSettings(), reports_dir=tmp_path, charts_dir=tmp_path / "charts")

    result = Backtester(config, EmaCrossoverStrategy(fast_period=5, slow_period=20)).run(bars)
    paths = ReportGenerator(config.reports_dir, config.charts_dir).generate(result)

    assert result.metrics.total_trades > 5
    for path in (paths.report, paths.trades, paths.equity_curve, paths.monthly_returns):
        assert path.is_file()
    assert sorted(p.name for p in paths.charts) == [
        "drawdown.png", "equity_curve.png", "monthly_returns.png", "win_loss_distribution.png",
    ]
    trades = pd.read_csv(paths.trades)
    assert list(trades.columns) == TRADE_COLUMNS and len(trades) == result.metrics.total_trades
    report = paths.report.read_text()
    for label in ("Starting Balance", "Ending Balance", "Sharpe Ratio", "Maximum Drawdown", "Expectancy Per Trade",
                  "Risk-Reward Ratio", "Profit Factor", "Average Trade Duration"):
        assert label in report
