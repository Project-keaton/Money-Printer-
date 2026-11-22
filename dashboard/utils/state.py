"""Session state and cached backtest runs.

The dashboard runs backtests in-process with the existing engine. Results are
cached on (config file contents, unsaved overrides, data files), so pages
switch instantly and a run repeats only when something actually changed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import streamlit as st

from backtests.backtester import Backtester, BacktestResult
from backtests.config import DEFAULT_CONFIG_PATH, BacktestConfig, ConfigError, load_config
from backtests.data_loader import DataLoadError, discover_files
from data_pipeline.logger import setup_logging
from strategies import StrategyError, create_strategy

OVERRIDES_KEY = "config_overrides"
CONFIG_PATH = DEFAULT_CONFIG_PATH

log = logging.getLogger("dashboard")


@st.cache_resource
def init_logging() -> None:
    """Log dashboard activity to logs/dashboard.log (once per server process)."""
    try:
        config = load_config(CONFIG_PATH)
        setup_logging(config.log_dir, "INFO", file_prefix="dashboard")
    except ConfigError:
        pass


def get_overrides() -> dict[str, Any]:
    """Unsaved settings from the Strategy page (dotted config keys)."""
    return dict(st.session_state.get(OVERRIDES_KEY, {}))


def set_overrides(overrides: dict[str, Any]) -> None:
    st.session_state[OVERRIDES_KEY] = dict(overrides)


def clear_overrides() -> None:
    st.session_state.pop(OVERRIDES_KEY, None)


def current_config() -> BacktestConfig:
    """config.yaml plus any unsaved overrides. Raises ConfigError."""
    return load_config(CONFIG_PATH, get_overrides())


def dataset_signature(config: BacktestConfig) -> str:
    """Changes whenever a data file is added, removed or rewritten."""
    if not config.dataset_dir.is_dir():
        return "missing"
    parts = []
    for path in discover_files(config.dataset_dir, config.symbol):
        stat = path.stat()
        parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    return "|".join(parts) or "empty"


@st.cache_data(show_spinner="Running backtest...", max_entries=16)
def _run_backtest(config_text: str, overrides_json: str, signature: str) -> BacktestResult:
    # config_text and signature are cache keys: a change to config.yaml or the data re-runs the backtest.
    config = load_config(CONFIG_PATH, json.loads(overrides_json))
    strategy = create_strategy(config.strategy_name, config.strategy_params)
    log.info("Dashboard backtest: %s on %s (%s)", strategy.describe(), config.symbol, config.dataset)
    return Backtester(config, strategy).run()


def get_result() -> BacktestResult | None:
    """Run (or fetch from cache) the backtest for the current settings; show errors in the page."""
    try:
        config = current_config()
    except ConfigError as exc:
        st.error(f"**Configuration error:** {exc}\n\nFix it on the Strategy Settings page or in `config.yaml`.")
        return None
    try:
        return _run_backtest(
            CONFIG_PATH.read_text(encoding="utf-8"),
            json.dumps(get_overrides(), sort_keys=True, default=str),
            dataset_signature(config),
        )
    except DataLoadError as exc:
        st.error(f"**No market data:** {exc}\n\nUse the Data Management page to download data.")
    except (StrategyError, ConfigError) as exc:
        st.error(f"**Backtest failed:** {exc}")
    return None


def require_result() -> BacktestResult:
    """Like :func:`get_result` but stops the page when no result is available."""
    result = get_result()
    if result is None:
        st.stop()
    return result  # type: ignore[return-value]


def rerun_backtest() -> None:
    """Force a fresh run (e.g. after editing config.yaml by hand)."""
    _run_backtest.clear()
