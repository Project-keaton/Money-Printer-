"""Alpha Vantage FX_DAILY provider.

Docs: https://www.alphavantage.co/documentation/#fx-daily
Requires an API key (``ALPHA_VANTAGE_API_KEY``). Only daily candles are supported:
intraday FX history is limited to recent data. Alpha Vantage may restrict
``outputsize=full`` to premium plans; in that case the API's message is reported.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, ClassVar

import pandas as pd

from data_pipeline.config import Timeframe
from data_pipeline.providers.base import (
    OHLCV_COLUMNS,
    AuthenticationError,
    BaseProvider,
    Chunk,
    ProviderError,
    RateLimitError,
)

log = logging.getLogger(__name__)

_SERIES_KEY = "Time Series FX (Daily)"


class AlphaVantageProvider(BaseProvider):
    name: ClassVar[str] = "alphavantage"
    display_name: ClassVar[str] = "Alpha Vantage"
    supported_timeframes: ClassVar[frozenset[Timeframe]] = frozenset({Timeframe.DAILY})
    min_request_interval: ClassVar[float] = 12.0

    _URL: ClassVar[str] = "https://www.alphavantage.co/query"
    _RATE_LIMIT_WAIT: ClassVar[float] = 61.0

    def plan_chunks(self, start: datetime, end: datetime) -> list[Chunk]:
        # A single request returns the full daily history; the downloader trims it to the window.
        return [Chunk(start, end)]

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        params = {
            "function": "FX_DAILY",
            "from_symbol": self.settings.base_currency,
            "to_symbol": self.settings.quote_currency,
            "outputsize": "full",
            "datatype": "json",
            "apikey": self.settings.alpha_vantage_api_key,
        }

        series: dict[str, dict[str, str]] = {}
        for attempt in range(self.settings.max_retries + 1):
            response = self._request(self._URL, params=params)
            assert response is not None
            try:
                payload: dict[str, Any] = response.json()
            except ValueError as exc:
                raise ProviderError("Alpha Vantage returned a non-JSON response") from exc

            if _SERIES_KEY in payload:
                series = payload[_SERIES_KEY]
                break

            # Alpha Vantage reports errors in the JSON body with HTTP 200.
            if error := payload.get("Error Message"):
                if "apikey" in error.lower():
                    raise AuthenticationError(f"Alpha Vantage rejected the API key: {error}")
                raise ProviderError(f"Alpha Vantage error: {error}")

            notice = str(payload.get("Note") or payload.get("Information") or "unexpected response")
            if "minute" in notice.lower() and attempt < self.settings.max_retries:
                log.warning("Alpha Vantage per-minute limit hit; waiting %.0fs", self._RATE_LIMIT_WAIT)
                time.sleep(self._RATE_LIMIT_WAIT)
                continue
            if "rate limit" in notice.lower():
                raise RateLimitError(f"Alpha Vantage: {notice}")
            raise ProviderError(f"Alpha Vantage did not return data: {notice}")

        try:
            rows = [
                {
                    "Date": day,
                    "Open": float(v["1. open"]),
                    "High": float(v["2. high"]),
                    "Low": float(v["3. low"]),
                    "Close": float(v["4. close"]),
                    "Volume": 0.0,  # Alpha Vantage does not publish forex volume.
                }
                for day, v in series.items()
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Unexpected Alpha Vantage response format: {exc}") from exc
        return pd.DataFrame(rows, columns=OHLCV_COLUMNS)
