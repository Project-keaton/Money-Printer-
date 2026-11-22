"""Command-line entry point for the backtesting engine.

Usage (from the ForexBot project root)::

    python -m backtests                              # settings from config.yaml
    python -m backtests --strategy rsi_reversal
    python -m backtests --spread 0.8 --risk 0.5 --start 2020-01-01
    python -m backtests --dataset raw --no-charts

Exit codes:
    0  backtest completed and reports were written
    2  configuration error
    3  data or strategy error
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from backtests.backtester import Backtester, BacktestResult
from backtests.config import DEFAULT_CONFIG_PATH, BacktestConfig, ConfigError, load_config
from backtests.data_loader import DataLoadError
from backtests.report_generator import ReportGenerator, ReportPaths, summary_lines
from data_pipeline.logger import setup_logging
from strategies import STRATEGIES, StrategyError, create_strategy

EXIT_OK, EXIT_CONFIG, EXIT_FAILED = 0, 2, 3

log = logging.getLogger("backtests")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m backtests", description="Backtest a strategy on historical data.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="settings file (default: config.yaml)")
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), help="override strategy.active")
    parser.add_argument("--symbol", help="override backtest.symbol, e.g. GBPUSD")
    parser.add_argument("--dataset", choices=["weekday", "raw"], help="override backtest.dataset")
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="override backtest.start_date")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="override backtest.end_date")
    parser.add_argument("--balance", type=float, help="override backtest.starting_balance")
    parser.add_argument("--risk", type=float, metavar="PERCENT", help="risk per trade in percent, e.g. 1 = 1%%")
    parser.add_argument("--spread", type=float, metavar="PIPS", help="override execution.spread_pips")
    parser.add_argument("--commission", type=float, help="override execution.commission_per_lot")
    parser.add_argument("--slippage", type=float, metavar="PIPS", help="override execution.slippage_pips")
    parser.add_argument("--no-charts", action="store_true", help="skip chart generation")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="override logging.level")
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> BacktestConfig:
    overrides = {
        "strategy.active": args.strategy,
        "backtest.symbol": args.symbol,
        "backtest.dataset": args.dataset,
        "backtest.start_date": args.start,
        "backtest.end_date": args.end,
        "backtest.starting_balance": args.balance,
        "risk.risk_per_trade": None if args.risk is None else args.risk / 100.0,
        "execution.spread_pips": args.spread,
        "execution.commission_per_lot": args.commission,
        "execution.slippage_pips": args.slippage,
        "logging.level": args.log_level,
    }
    return load_config(args.config, overrides)


def run(config: BacktestConfig, *, charts: bool = True) -> tuple[BacktestResult, ReportPaths]:
    """Run one backtest and write all reports. Raises on data/strategy errors."""
    strategy = create_strategy(config.strategy_name, config.strategy_params)
    result = Backtester(config, strategy).run()
    paths = ReportGenerator(config.reports_dir, config.charts_dir).generate(result, charts=charts)
    return result, paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = build_config(args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    setup_logging(config.log_dir, config.log_level, file_prefix="backtest")
    log.info("Backtest started with %r", config)
    print(f"Backtesting {config.strategy_name} on {config.symbol} ({config.dataset} dataset) ...", flush=True)

    try:
        result, paths = run(config, charts=not args.no_charts)
    except (DataLoadError, StrategyError, ConfigError) as exc:
        log.error("Backtest failed: %s", exc)
        return EXIT_FAILED

    m = result.metrics
    print(f"{m.start:%Y-%m-%d} -> {m.end:%Y-%m-%d}, {len(result.data):,} bars, {result.duration_seconds:.1f}s\n")
    print("\n".join(summary_lines(m)))
    for warning in result.warnings:
        print(f"  note: {warning}")
    print(f"\nReport:       {paths.report}")
    print(f"Trades:       {paths.trades}")
    print(f"Equity curve: {paths.equity_curve}")
    if paths.charts:
        print(f"Charts:       {paths.charts[0].parent} ({len(paths.charts)} files)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
