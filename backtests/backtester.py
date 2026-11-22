"""Backtest orchestration: data -> strategy signals -> order plan -> simulation -> metrics."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import pandas as pd

from backtests.config import BacktestConfig, RiskSettings, Instrument
from backtests.data_loader import LoadReport, load_market_data
from backtests.performance import PerformanceMetrics, build_equity_curve, compute_metrics
from backtests.trade_engine import EngineResult, Trade, TradeEngine
from strategies.base import Strategy, StrategyError, normalise_signals
from strategies.indicators import atr

log = logging.getLogger(__name__)

#: Fewer bars than this cannot produce a meaningful backtest.
MIN_BARS = 30


@dataclass
class BacktestResult:
    config: BacktestConfig
    strategy: Strategy
    data: pd.DataFrame
    signals: pd.DataFrame
    trades: list[Trade]
    equity_curve: pd.DataFrame
    metrics: PerformanceMetrics
    engine: EngineResult
    load_report: LoadReport | None = None
    duration_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)


class Backtester:
    """Runs one strategy over historical data with the configured costs and risk rules.

    Example::

        config = load_config()
        strategy = create_strategy(config.strategy_name, config.strategy_params)
        result = Backtester(config, strategy).run()
    """

    def __init__(self, config: BacktestConfig, strategy: Strategy) -> None:
        self.config = config
        self.strategy = strategy

    def run(self, data: pd.DataFrame | None = None) -> BacktestResult:
        """Run the backtest.

        Args:
            data: optional OHLC frame indexed by UTC timestamp. When omitted, the
                yearly CSV files of the configured dataset are loaded.

        Raises:
            DataLoadError: if no market data is available.
            StrategyError: if the strategy fails or emits invalid signals.
        """
        started = time.monotonic()
        load_report: LoadReport | None = None
        if data is None:
            data, load_report = load_market_data(
                self.config.dataset_dir, self.config.symbol, self.config.start_date, self.config.end_date
            )
        if len(data) < MIN_BARS:
            raise StrategyError(f"Only {len(data)} bar(s) available; at least {MIN_BARS} are needed")

        log.info("Running %s on %d bars (%s -> %s)", self.strategy.describe(), len(data), data.index[0], data.index[-1])
        try:
            raw_signals = self.strategy.generate_signals(data)
        except StrategyError:
            raise
        except Exception as exc:
            raise StrategyError(f"Strategy {self.strategy.name} failed: {type(exc).__name__}: {exc}") from exc

        signals = normalise_signals(raw_signals, data.index)
        signals = plan_order_distances(data, signals, self.config.risk, self.config.instrument)

        engine_result = TradeEngine(self.config).run(data, signals)
        equity_curve = build_equity_curve(engine_result.equity_curve, self.config.starting_balance)
        metrics = compute_metrics(
            engine_result.trades, equity_curve, self.config.starting_balance, self.config.risk_free_rate
        )

        warnings = list(load_report.warnings) if load_report else []
        for reason, count in engine_result.skipped_entries.items():
            warnings.append(f"{count} entry signal(s) skipped: {reason}")
        if metrics.total_trades == 0:
            warnings.append("The strategy produced no trades")

        return BacktestResult(
            config=self.config,
            strategy=self.strategy,
            data=data,
            signals=signals,
            trades=engine_result.trades,
            equity_curve=equity_curve,
            metrics=metrics,
            engine=engine_result,
            load_report=load_report,
            duration_seconds=time.monotonic() - started,
            warnings=warnings,
        )


def plan_order_distances(
    data: pd.DataFrame, signals: pd.DataFrame, risk: RiskSettings, instrument: Instrument
) -> pd.DataFrame:
    """Fill ``stop_distance`` / ``target_distance`` from the risk settings.

    Distances set by the strategy itself take precedence. ATR-based distances
    use the ATR at the signal bar's close, so they are known before entry.
    """
    out = signals.copy()
    sl, tp = risk.stop_loss, risk.take_profit

    match sl.mode:
        case "pips":
            stop = pd.Series(sl.pips * instrument.pip_size, index=data.index)
        case "atr":
            stop = atr(data, sl.atr_period) * sl.atr_multiplier
        case _:
            stop = pd.Series(float("nan"), index=data.index)
    out["stop_distance"] = out["stop_distance"].fillna(stop)

    match tp.mode:
        case "pips":
            target = pd.Series(tp.pips * instrument.pip_size, index=data.index)
        case "atr":
            target = atr(data, tp.atr_period) * tp.atr_multiplier
        case "risk_reward":
            target = out["stop_distance"] * tp.risk_reward
        case _:
            target = pd.Series(float("nan"), index=data.index)
    out["target_distance"] = out["target_distance"].fillna(target)
    return out
