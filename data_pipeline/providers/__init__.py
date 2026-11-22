"""Historical forex data providers and a factory to build the configured one."""

from __future__ import annotations

import requests

from data_pipeline.config import Settings
from data_pipeline.providers.alpha_vantage import AlphaVantageProvider
from data_pipeline.providers.base import (
    OHLCV_COLUMNS,
    AuthenticationError,
    BaseProvider,
    Chunk,
    ProviderError,
    RateLimitError,
)
from data_pipeline.providers.dukascopy import DukascopyProvider
from data_pipeline.providers.oanda import OandaProvider
from data_pipeline.providers.twelve_data import TwelveDataProvider

PROVIDERS: dict[str, type[BaseProvider]] = {
    cls.name: cls
    for cls in (OandaProvider, TwelveDataProvider, AlphaVantageProvider, DukascopyProvider)
}


def create_provider(settings: Settings, session: requests.Session | None = None) -> BaseProvider:
    """Instantiate the provider selected by ``settings.provider``."""
    try:
        provider_cls = PROVIDERS[settings.provider]
    except KeyError:
        raise ProviderError(f"No provider registered under '{settings.provider}'") from None
    return provider_cls(settings, session)


__all__ = [
    "OHLCV_COLUMNS",
    "PROVIDERS",
    "AlphaVantageProvider",
    "AuthenticationError",
    "BaseProvider",
    "Chunk",
    "DukascopyProvider",
    "OandaProvider",
    "ProviderError",
    "RateLimitError",
    "TwelveDataProvider",
    "create_provider",
]
