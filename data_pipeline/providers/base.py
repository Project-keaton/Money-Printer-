"""Common provider interface, HTTP handling with retries, and error types."""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import pandas as pd
import requests

from data_pipeline.config import Settings, Timeframe

#: Columns every provider must return (``Date`` as UTC timestamps or ISO strings).
OHLCV_COLUMNS: list[str] = ["Date", "Open", "High", "Low", "Close", "Volume"]

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """A request to a data provider failed or returned unusable data."""


class AuthenticationError(ProviderError):
    """The provider rejected the API credentials. Retrying will not help."""


class RateLimitError(ProviderError):
    """The provider's rate limit was exceeded and retries were exhausted."""


def empty_ohlcv() -> pd.DataFrame:
    """An empty frame with the standard OHLCV columns."""
    return pd.DataFrame(columns=OHLCV_COLUMNS)


@dataclass(frozen=True, slots=True)
class Chunk:
    """One unit of work for a provider: the UTC interval ``[start, end)``."""

    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        last = self.end - timedelta(seconds=1)
        if self.start.date() == last.date():
            return f"{self.start:%Y-%m-%d}"
        return f"{self.start:%Y-%m-%d} -> {last:%Y-%m-%d}"


class BaseProvider(ABC):
    """Base class for historical forex data providers.

    Subclasses implement :meth:`fetch_chunk` and may override :meth:`plan_chunks`
    and the class-level tuning attributes below.
    """

    #: Provider id used in configuration (``DATA_PROVIDER``).
    name: ClassVar[str]
    #: Human-readable provider name used in logs and reports.
    display_name: ClassVar[str]
    supported_timeframes: ClassVar[frozenset[Timeframe]] = frozenset(Timeframe)
    #: Maximum number of candles a single request may return.
    max_candles_per_request: ClassVar[int] = 5000
    #: Minimum delay between consecutive requests, in seconds (client-side throttling).
    min_request_interval: ClassVar[float] = 0.0
    #: First retry delay in seconds; doubles on each further retry (capped at 60 s).
    retry_backoff_base: ClassVar[float] = 2.0

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        if settings.timeframe not in self.supported_timeframes:
            supported = ", ".join(sorted(t.value for t in self.supported_timeframes))
            raise ProviderError(
                f"{self.display_name} does not support timeframe '{settings.timeframe}' "
                f"for long histories (supported: {supported})."
            )
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "ForexBot-DataPipeline/1.0")
        #: Effective throttle for this instance (subclasses may set it from configuration).
        self.request_interval: float = self.min_request_interval
        self._last_request_at = 0.0

    # ------------------------------------------------------------------ API

    def plan_chunks(self, start: datetime, end: datetime) -> list[Chunk]:
        """Split ``[start, end)`` into requests no larger than the provider's limit.

        Chunks never cross a calendar-year boundary, which keeps progress output
        and log messages easy to follow.
        """
        window = self.settings.timeframe.step * int(self.max_candles_per_request * 0.95)
        chunks: list[Chunk] = []
        for year in range(start.year, end.year + 1):
            year_start = max(start, datetime(year, 1, 1, tzinfo=timezone.utc))
            year_end = min(end, datetime(year + 1, 1, 1, tzinfo=timezone.utc))
            cursor = year_start
            while cursor < year_end:
                chunk_end = min(cursor + window, year_end)
                chunks.append(Chunk(cursor, chunk_end))
                cursor = chunk_end
        return chunks

    @abstractmethod
    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        """Download candles for ``chunk`` and return them with :data:`OHLCV_COLUMNS`.

        Raises:
            AuthenticationError: credentials were rejected (the run is aborted).
            ProviderError: the chunk could not be downloaded (the run continues).
        """

    def close(self) -> None:
        self.session.close()

    # ------------------------------------------------------------- helpers

    def _request(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> requests.Response | None:
        """GET ``url`` with throttling and retries on network errors, HTTP 429 and 5xx.

        Query parameters are never logged, because some providers pass the API key there.

        Returns:
            The response, or ``None`` for a 404 when ``allow_404`` is true.
        """
        attempts = self.settings.max_retries + 1
        last_error = "unknown error"
        rate_limited = False

        for attempt in range(1, attempts + 1):
            self._throttle()
            delay: float
            rate_limited = False
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.settings.request_timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                delay = self._backoff(attempt)
            else:
                status = response.status_code
                if status < 400:
                    return response
                if status in (401, 403):
                    raise AuthenticationError(
                        f"{self.display_name} rejected the request (HTTP {status}): {_snippet(response)}"
                    )
                if status == 404 and allow_404:
                    return None
                if status == 429 or status >= 500:
                    rate_limited = status == 429
                    last_error = f"HTTP {status}: {_snippet(response, 120)}"
                    delay = _retry_after(response) or self._backoff(attempt)
                else:
                    raise ProviderError(
                        f"{self.display_name} request failed (HTTP {status}): {_snippet(response)}"
                    )

            if attempt < attempts:
                log.warning(
                    "%s request failed (%s); retry %d/%d in %.1fs",
                    self.display_name, last_error, attempt, attempts - 1, delay,
                )
                time.sleep(delay)

        message = f"{self.display_name} request failed after {attempts} attempt(s): {last_error}"
        if rate_limited:
            raise RateLimitError(message)
        raise ProviderError(message)

    def _throttle(self) -> None:
        wait = self.request_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        return min(60.0, self.retry_backoff_base * 2 ** (attempt - 1)) + random.uniform(0, 1)


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    try:
        return min(float(value), 300.0)
    except ValueError:
        return None


def _snippet(response: requests.Response, limit: int = 200) -> str:
    text = " ".join(response.text.split())
    return text[:limit] + ("..." if len(text) > limit else "")
