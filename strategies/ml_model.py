"""Adapter that turns a trained machine-learning model into a strategy.

Example::

    from xgboost import XGBClassifier
    from strategies.ml_model import ModelSignalStrategy

    def features(data):                      # must use only past/current bars
        out = pd.DataFrame(index=data.index)
        out["ret_1"] = data["Close"].pct_change()
        out["ret_5"] = data["Close"].pct_change(5)
        out["rsi"] = rsi(data["Close"], 14)
        return out

    model = XGBClassifier().fit(X_train, y_train)   # trained on data BEFORE the backtest window
    strategy = ModelSignalStrategy(model, features, long_threshold=0.55, short_threshold=0.45)
    result = Backtester(config, strategy).run()

Train and backtest on separate periods (walk-forward) to avoid look-ahead bias.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Protocol

import numpy as np
import pandas as pd

from strategies.base import LONG, SHORT, Strategy, StrategyError


class ProbabilisticModel(Protocol):
    def predict_proba(self, X: Any) -> Any: ...


class ModelSignalStrategy(Strategy):
    """Long when P(up) >= ``long_threshold``, short when P(up) <= ``short_threshold``.

    Args:
        model: any fitted classifier with ``predict_proba`` (scikit-learn, XGBoost, ...).
            Column 1 of the output is read as the probability of an up move.
        feature_builder: builds the model's feature matrix from OHLCV data.
        long_threshold / short_threshold: probability cut-offs.
        long_only: never open shorts.
    """

    name: ClassVar[str] = "ml_model"

    def __init__(
        self,
        model: ProbabilisticModel,
        feature_builder: Callable[[pd.DataFrame], pd.DataFrame],
        long_threshold: float = 0.55,
        short_threshold: float = 0.45,
        long_only: bool = False,
    ) -> None:
        if not hasattr(model, "predict_proba"):
            raise StrategyError("model must implement predict_proba()")
        if not 0 <= short_threshold < long_threshold <= 1:
            raise StrategyError("Thresholds must satisfy 0 <= short_threshold < long_threshold <= 1")
        super().__init__(
            model=type(model).__name__, long_threshold=long_threshold,
            short_threshold=short_threshold, long_only=long_only,
        )
        self.model = model
        self.feature_builder = feature_builder
        self.long_threshold = long_threshold
        self.short_threshold = short_threshold
        self.long_only = long_only

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        features = self.feature_builder(data)
        if not features.index.equals(data.index):
            raise StrategyError("feature_builder must return a frame with the same index as the data")

        signals = pd.DataFrame({"signal": 0}, index=data.index)
        usable = features.notna().all(axis=1)
        if usable.any():
            proba = np.asarray(self.model.predict_proba(features.loc[usable]))[:, 1]
            p_up = pd.Series(proba, index=features.index[usable])
            signals.loc[p_up.index[p_up >= self.long_threshold], "signal"] = LONG
            if not self.long_only:
                signals.loc[p_up.index[p_up <= self.short_threshold], "signal"] = SHORT
        return signals
