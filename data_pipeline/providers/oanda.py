"""OANDA v20 REST API provider.

Docs: https://developer.oanda.com/rest-live-v20/instrument-ep/
Requires a personal access token (``OANDA_API_KEY``) from a practice or live account.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pandas as pd
import requests

from data_pipeline.config import Settings, Timeframe
from data_pipeline.providers.base import OHLCV_COLUMNS, BaseProvider, Chunk, ProviderError


class OandaProvider(BaseProvider):
    name: ClassVar[str] = "oanda"
    display_name: ClassVar[str] = "OANDA"
    max_candles_per_request: ClassVar[int] = 5000
    min_request_interval: ClassVar[float] = 0.1

    _HOSTS: ClassVar[dict[str, str]] = {
        "practice": "https://api-fxpractice.oanda.com",
        "live": "https://api-fxtrade.oanda.com",
    }
    _GRANULARITY: ClassVar[dict[Timeframe, str]] = {Timeframe.DAILY: "D", Timeframe.HOURLY: "H1"}

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        super().__init__(settings, session)
        instrument = f"{settings.base_currency}_{settings.quote_currency}"
        self._url = f"{self._HOSTS[settings.oanda_environment]}/v3/instruments/{instrument}/candles"
        self._headers = {
            "Authorization": f"Bearer {settings.oanda_api_key}",
            "Accept-Datetime-Format": "RFC3339",
        }

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        params: dict[str, str | int] = {
            "price": "M",  # mid prices
            "granularity": self._GRANULARITY[self.settings.timeframe],
            "from": _rfc3339(chunk.start),
            "to": _rfc3339(chunk.end),
        }
        if self.settings.timeframe is Timeframe.DAILY:
            # Align daily candles to UTC midnight so dates match the other providers.
            params |= {"dailyAlignment": 0, "alignmentTimezone": "UTC"}

        response = self._request(self._url, params=params, headers=self._headers)
        assert response is not None  # allow_404 is False
        try:
            candles = response.json().get("candles", [])
            rows = [
                {
                    "Date": c["time"],
                    "Open": float(c["mid"]["o"]),
                    "High": float(c["mid"]["h"]),
                    "Low": float(c["mid"]["l"]),
                    "Close": float(c["mid"]["c"]),
                    "Volume": float(c.get("volume", 0)),  # tick volume
                }
                for c in candles
                if c.get("complete", False)  # skip the still-forming candle
            ]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"Unexpected OANDA response format: {exc}") from exc
        return pd.DataFrame(rows, columns=OHLCV_COLUMNS)


def _rfc3339(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
