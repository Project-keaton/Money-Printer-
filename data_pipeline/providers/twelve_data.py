"""Twelve Data REST API provider.

Docs: https://twelvedata.com/docs#time-series
Requires an API key (``TWELVE_DATA_API_KEY``). The free plan allows 8 requests
per minute, so requests are throttled to one every 8 seconds.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
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
    empty_ohlcv,
)

log = logging.getLogger(__name__)


class TwelveDataProvider(BaseProvider):
    name: ClassVar[str] = "twelvedata"
    display_name: ClassVar[str] = "Twelve Data"
    max_candles_per_request: ClassVar[int] = 5000
    min_request_interval: ClassVar[float] = 8.0

    _URL: ClassVar[str] = "https://api.twelvedata.com/time_series"
    _INTERVAL: ClassVar[dict[Timeframe, str]] = {Timeframe.DAILY: "1day", Timeframe.HOURLY: "1h"}
    _RATE_LIMIT_WAIT: ClassVar[float] = 61.0

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        params: dict[str, Any] = {
            "symbol": self.settings.display_symbol,
            "interval": self._INTERVAL[self.settings.timeframe],
            "start_date": chunk.start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": (chunk.end - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "UTC",
            "order": "ASC",
            "outputsize": self.max_candles_per_request,
            "format": "JSON",
            "apikey": self.settings.twelve_data_api_key,
        }

        payload: dict[str, Any] = {}
        for attempt in range(self.settings.max_retries + 1):
            response = self._request(self._URL, params=params)
            assert response is not None
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError("Twelve Data returned a non-JSON response") from exc

            if payload.get("status") != "error":
                break

            # Twelve Data reports most errors in the JSON body with HTTP 200.
            code = payload.get("code")
            message = str(payload.get("message", "unknown error"))
            if code in (401, 403):
                raise AuthenticationError(f"Twelve Data rejected the API key: {message}")
            if code == 429:
                if attempt >= self.settings.max_retries:
                    raise RateLimitError(f"Twelve Data rate limit exceeded: {message}")
                log.warning("Twelve Data rate limit hit; waiting %.0fs before retrying", self._RATE_LIMIT_WAIT)
                time.sleep(self._RATE_LIMIT_WAIT)
                continue
            if code == 400 and "no data" in message.lower():
                return empty_ohlcv()
            raise ProviderError(f"Twelve Data error {code}: {message}")

        try:
            rows = [
                {
                    "Date": v["datetime"],
                    "Open": float(v["open"]),
                    "High": float(v["high"]),
                    "Low": float(v["low"]),
                    "Close": float(v["close"]),
                    # Twelve Data does not publish volume for forex pairs.
                    "Volume": float(v.get("volume") or 0),
                }
                for v in payload.get("values", [])
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Unexpected Twelve Data response format: {exc}") from exc
        return pd.DataFrame(rows, columns=OHLCV_COLUMNS)
