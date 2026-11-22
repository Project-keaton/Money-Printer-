"""Tests for the dashboard's pure helpers and a headless smoke test of every page."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from backtests.backtester import Backtester
from backtests.config import PROJECT_ROOT, BacktestConfig, ConfigError, ExecutionSettings, load_config
from dashboard.utils.analytics import (
    breakdown, drawdown_episodes, losing_streaks, monthly_series, monthly_table, monthly_trade_stats, trade_frame,
    yearly_returns,
)
from dashboard.utils.config_io import save_config_values, to_yaml_scalar, update_yaml_text
from dashboard.utils.data_quality import scan_dataset
from strategies import EmaCrossoverStrategy


@pytest.fixture(scope="module")
def result():  # type: ignore[no-untyped-def]
    t = np.arange(800)
    close = 1.10 + 0.03 * np.sin(t / 30) + 0.002 * np.sin(t / 3)
    index = pd.bdate_range("2021-01-01", periods=len(t), tz="UTC", name="Date")
    bars = pd.DataFrame({"Open": close, "High": close + 0.004, "Low": close - 0.004, "Close": close, "Volume": 1.0},
                        index=index)
    config = BacktestConfig(execution=ExecutionSettings())
    return Backtester(config, EmaCrossoverStrategy(fast_period=5, slow_period=20)).run(bars)


# --------------------------------------------------------------- analytics


def test_trade_frame_and_breakdowns(result) -> None:  # type: ignore[no-untyped-def]
    trades = trade_frame(result)
    assert len(trades) == result.metrics.total_trades > 5
    assert trades["Cumulative P/L"].iloc[-1] == pytest.approx(sum(t.pnl for t in result.trades))
    assert set(trades["Outcome"]) <= {"Win", "Loss", "Break-even"}

    by_side = breakdown(trades, "Trade Type")
    assert by_side["Trades"].sum() == len(trades)
    assert by_side["Profit/Loss"].sum() == pytest.approx(trades["Profit/Loss"].sum())

    stats = monthly_trade_stats(trades)
    assert stats["Trades"].sum() == len(trades)
    assert stats["Win Rate %"].between(0, 100).all()


def test_yearly_and_monthly_returns_are_consistent(result) -> None:  # type: ignore[no-untyped-def]
    yearly = yearly_returns(result)
    compounded = np.prod(1 + yearly["Return %"] / 100) - 1
    assert compounded * 100 == pytest.approx(result.metrics.total_return_pct, abs=1e-6)

    table = monthly_table(result)
    series = monthly_series(table)
    assert series.index.is_monotonic_increasing
    assert (np.prod(1 + series / 100) - 1) * 100 == pytest.approx(result.metrics.total_return_pct, abs=1e-6)


def test_drawdown_episodes(result) -> None:  # type: ignore[no-untyped-def]
    episodes = drawdown_episodes(result)
    assert not episodes.empty
    assert episodes["Depth %"].iloc[0] == pytest.approx(result.metrics.max_drawdown_pct)
    assert episodes["Depth %"].is_monotonic_increasing  # deepest first
    recovered = episodes[episodes["Recovered"]]
    assert (recovered["Recovery Date"] > recovered["Trough Date"]).all()
    assert (episodes["Trough Date"] >= episodes["Peak Date"]).all()


def test_losing_streaks() -> None:
    trades = pd.DataFrame({
        "Entry Date": pd.date_range("2024-01-01", periods=7),
        "Exit Date": pd.date_range("2024-01-02", periods=7),
        "Profit/Loss": [10.0, -1.0, -2.0, -3.0, 5.0, -4.0, -1.0],
    })
    streaks = losing_streaks(trades)
    assert streaks["Losing Trades"].tolist() == [3, 2]
    assert streaks["Total Loss"].iloc[0] == pytest.approx(-6.0)


# --------------------------------------------------------------- config io


YAML_TEXT = """# top comment
backtest:
  starting_balance: 10000   # balance comment
  start_date: null          # dates
risk:
  risk_per_trade: 0.01
  stop_loss:
    mode: atr               # pips | atr | none
    pips: 30
strategy:
  active: ema_crossover
  ema_crossover:
    fast_period: 20
    long_only: false
"""


def test_update_yaml_preserves_comments_and_layout() -> None:
    out = update_yaml_text(YAML_TEXT, {
        "backtest.starting_balance": 25000.0,
        "backtest.start_date": "2020-01-01",
        "risk.stop_loss.mode": "pips",
        "risk.risk_per_trade": 0.005,
        "strategy.ema_crossover.long_only": True,
    })
    assert "# top comment" in out and "# balance comment" in out and "# pips | atr | none" in out
    assert "    mode: pips" in out
    data = yaml.safe_load(out)
    assert data["backtest"]["starting_balance"] == 25000.0
    assert str(data["backtest"]["start_date"]) == "2020-01-01"
    assert data["risk"]["risk_per_trade"] == 0.005
    assert data["risk"]["stop_loss"]["pips"] == 30
    assert data["strategy"]["ema_crossover"]["long_only"] is True
    assert len(out.splitlines()) == len(YAML_TEXT.splitlines())


def test_update_yaml_rejects_unknown_keys() -> None:
    with pytest.raises(KeyError, match="risk.nope"):
        update_yaml_text(YAML_TEXT, {"risk.nope": 1})


@pytest.mark.parametrize("value, expected", [
    (None, "null"), (True, "true"), (3, "3"), (0.00001, "0.00001"), (10000.0, "10000.0"), ("atr", "atr"),
    ("2020-01-01", '"2020-01-01"'),
])
def test_to_yaml_scalar(value: object, expected: str) -> None:
    assert to_yaml_scalar(value) == expected
    assert yaml.safe_load(f"k: {expected}")["k"] == (value if expected != '"2020-01-01"' else "2020-01-01")


def test_save_config_values_validates_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(ConfigError):
        save_config_values(path, {"execution.spread_pips": -5.0})
    assert path.read_text(encoding="utf-8") == original  # untouched on error

    save_config_values(path, {"execution.spread_pips": 0.7, "strategy.active": "rsi_reversal"})
    config = load_config(path)
    assert config.execution.spread_pips == 0.7 and config.strategy_name == "rsi_reversal"
    assert not list(tmp_path.glob(".config-*"))  # temp file cleaned up


# ------------------------------------------------------------ data quality


def test_scan_dataset_reports_problems(tmp_path: Path) -> None:
    good = pd.DataFrame({"Date": pd.bdate_range("2020-01-06", periods=5).strftime("%Y-%m-%d"),
                         "Open": 1.1, "High": 1.11, "Low": 1.09, "Close": 1.1, "Volume": 1.0})
    good.to_csv(tmp_path / "EURUSD_2020.csv", index=False)
    bad = good.copy()
    bad["Date"] = bad["Date"].str.replace("2020", "2021")
    bad.loc[1, "Close"] = None           # missing value
    bad.loc[2, "Date"] = bad.loc[3, "Date"]  # duplicate date
    bad.loc[4, "High"] = 1.0             # High below Low
    bad.to_csv(tmp_path / "EURUSD_2021.csv", index=False)
    (tmp_path / "EURUSD_2022.csv").write_text("not,a,valid\nfile")

    quality = scan_dataset(tmp_path, "EURUSD")
    by_year = {f.year: f for f in quality.files}
    assert by_year[2020].status == "OK"
    assert (by_year[2021].missing_values, by_year[2021].duplicates, by_year[2021].invalid_ohlc) == (1, 1, 1)
    assert by_year[2022].problems and by_year[2022].rows == 0
    assert quality.total_rows == 10 and quality.years == [2020, 2021]


# ------------------------------------------------------- headless app test

PAGES = ["overview", "backtest_results", "trade_history", "performance", "risk_analysis", "monthly",
         "strategy_settings", "data_management"]


@pytest.mark.skipif(not list((PROJECT_ROOT / "data" / "weekday").glob("EURUSD_*.csv")),
                    reason="needs the downloaded EUR/USD data")
def test_every_dashboard_page_renders_without_errors() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(PROJECT_ROOT / "dashboard" / "app.py"), default_timeout=180)
    app.run()
    for page in PAGES:
        app.switch_page(f"views/{page}.py")
        app.run()
        assert not app.exception, f"{page}: {[e.message for e in app.exception]}"
        assert not app.error, f"{page}: {[e.value for e in app.error]}"


@pytest.mark.skipif(not list((PROJECT_ROOT / "data" / "weekday").glob("EURUSD_*.csv")),
                    reason="needs the downloaded EUR/USD data")
def test_strategy_page_applies_unsaved_settings() -> None:
    from streamlit.testing.v1 import AppTest

    config_before = (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")
    app = AppTest.from_file(str(PROJECT_ROOT / "dashboard" / "app.py"), default_timeout=180)
    app.run()
    app.switch_page("views/strategy_settings.py")
    app.run()
    active = next(s for s in app.selectbox if s.label == "Active strategy")
    active.set_value("rsi_reversal")
    next(b for b in app.button if b.label == "Run backtest").click()
    app.run()

    assert not app.exception
    assert app.session_state["config_overrides"]["strategy.active"] == "rsi_reversal"
    assert (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8") == config_before  # not saved
