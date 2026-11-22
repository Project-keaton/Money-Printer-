"""ForexBot - main application entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"


def load_config(path: Path) -> dict:
    """Load the YAML configuration file."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def setup_logging(config: dict) -> None:
    """Configure console and file logging."""
    log_cfg = config.get("logging", {})
    log_file = PROJECT_ROOT / log_cfg.get("app_log", "logs/app.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=log_cfg.get("level", "INFO"),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ForexBot - Forex AI trading bot")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Path to the YAML config file")
    parser.add_argument("--mode", choices=["backtest", "paper", "live"],
                        help="Override the run mode set in config.yaml")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    mode = args.mode or config.get("app", {}).get("mode", "backtest")

    if mode == "backtest":
        # The backtesting engine has its own CLI, logging and reports (see backtests/README.md).
        from backtests.main import main as backtest_main

        return backtest_main(["--config", str(args.config)])

    setup_logging(config)
    log = logging.getLogger("forexbot")
    log.info("Starting ForexBot in '%s' mode", mode)

    # TODO: paper and live trading.
    if mode == "paper":
        log.info("Paper trading not implemented yet.")
    elif mode == "live":
        log.warning("Live trading not implemented yet.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
