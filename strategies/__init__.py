"""Trading strategies and a registry to build them from configuration."""

from __future__ import annotations

from typing import Any

from strategies.base import Strategy, StrategyError, normalise_signals
from strategies.ema_crossover import EmaCrossoverStrategy
from strategies.ml_model import ModelSignalStrategy
from strategies.rsi_reversal import RsiReversalStrategy

#: Strategies that can be selected by name in config.yaml (``strategy.active``).
#: ModelSignalStrategy needs a trained model object, so it is created in code instead.
STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (EmaCrossoverStrategy, RsiReversalStrategy)
}


def create_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """Instantiate a registered strategy with parameters from the config file.

    Raises:
        StrategyError: for an unknown name or invalid parameters.
    """
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise StrategyError(f"Unknown strategy '{name}'. Available: {', '.join(sorted(STRATEGIES))}") from None
    try:
        return cls(**(params or {}))
    except TypeError as exc:
        raise StrategyError(f"Invalid parameters for strategy '{name}': {exc}") from exc


__all__ = [
    "STRATEGIES",
    "EmaCrossoverStrategy",
    "ModelSignalStrategy",
    "RsiReversalStrategy",
    "Strategy",
    "StrategyError",
    "create_strategy",
    "normalise_signals",
]
