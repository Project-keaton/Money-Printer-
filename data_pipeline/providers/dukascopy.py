"""Dukascopy historical datafeed provider - the pipeline's primary source (no API key).

Endpoint structure (relative to ``DUKASCOPY_BASE_URL``, default
``https://datafeed.dukascopy.com/datafeed``)::

    {SYMBOL}/{YYYY}/{SIDE}_candles_day_1.bi5              daily candles for one year
    {SYMBOL}/{YYYY}/{MM}/{SIDE}_candles_hour_1.bi5        hourly candles for one month
    {SYMBOL}/{YYYY}/{MM}/{DD}/{SIDE}_candles_min_1.bi5    minute candles for one day

``SIDE`` is ``BID`` or ``ASK`` (``DUKASCOPY_PRICE_SIDE``) and months are
zero-based (January = ``00``). Files are LZMA-compressed; each record is 24
bytes, big-endian: seconds offset from the period start, open, close, low,
high (integers in points: 1e5 for most pairs, 1e3 for JPY pairs) and volume (float).

Files for the current year/month are only published once that period ends, so
those periods are rebuilt from the next finer timeframe (day <- hour <- minute).

Dukascopy throttles clients that request too quickly. Requests are spaced by
``DUKASCOPY_REQUEST_INTERVAL`` seconds; HTTP 429/503 responses are retried with
exponential backoff, and a rate limit that survives every retry stops the run
early while keeping the data already downloaded.
"""

from __future__ import annotations

import calendar
import logging
import lzma
import struct
from datetime import datetime, timedelta, timezone
from typing import ClassVar

import pandas as pd
import requests

from data_pipeline.config import Settings, Timeframe
from data_pipeline.providers.base import OHLCV_COLUMNS, BaseProvider, Chunk, ProviderError, empty_ohlcv

log = logging.getLogger(__name__)

_RECORD = struct.Struct(">5if")
_RAW_COLUMNS = ["Offset", "Open", "Close", "Low", "High", "Volume"]


class DukascopyProvider(BaseProvider):
    name: ClassVar[str] = "dukascopy"
    display_name: ClassVar[str] = "Dukascopy"
    # The datafeed throttles aggressive clients, so stay polite and back off generously.
    min_request_interval: ClassVar[float] = 1.0
    retry_backoff_base: ClassVar[float] = 5.0

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        super().__init__(settings, session)
        self._point = 1_000.0 if settings.quote_currency == "JPY" else 100_000.0
        self._base_url = settings.dukascopy_base_url
        self._side = settings.dukascopy_price_side
        self.request_interval = settings.dukascopy_request_interval
        self._now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------ API

    def plan_chunks(self, start: datetime, end: datetime) -> list[Chunk]:
        """One chunk per year for daily data, one per month for hourly data."""
        chunks: list[Chunk] = []
        cursor = start
        while cursor < end:
            if self.settings.timeframe is Timeframe.DAILY:
                boundary = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                boundary = _add_month(datetime(cursor.year, cursor.month, 1, tzinfo=timezone.utc))
            chunk_end = min(boundary, end)
            chunks.append(Chunk(cursor, chunk_end))
            cursor = chunk_end
        return chunks

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        if self.settings.timeframe is Timeframe.DAILY:
            frame = self._daily_for_year(chunk.start.year)
        else:
            frame = self._hourly_for_month(chunk.start.year, chunk.start.month)
        return _drop_closed_market_candles(frame)

    # ------------------------------------------------------------ internals

    def _daily_for_year(self, year: int) -> pd.DataFrame:
        frame = self._download(f"{year}/{self._side}_candles_day_1.bi5", datetime(year, 1, 1, tzinfo=timezone.utc))
        if frame is not None:
            return frame

        log.info("Dukascopy daily file for %d not published yet; building it from hourly candles", year)
        last_month = self._now.month if year == self._now.year else 12
        months = [self._hourly_for_month(year, m) for m in range(1, last_month + 1)]
        return resample_ohlcv(_concat(months), Timeframe.DAILY)

    def _hourly_for_month(self, year: int, month: int) -> pd.DataFrame:
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        frame = self._download(f"{year}/{month - 1:02d}/{self._side}_candles_hour_1.bi5", month_start)
        if frame is not None:
            return frame

        if (year, month) != (self._now.year, self._now.month):
            log.warning("Dukascopy has no hourly file for %d-%02d", year, month)
            return empty_ohlcv()

        log.info("Dukascopy hourly file for %d-%02d not published yet; building it from minute candles", year, month)
        days = []
        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            day_start = datetime(year, month, day, tzinfo=timezone.utc)
            if day_start + timedelta(days=1) > self._now:
                break  # today and later are incomplete or in the future
            minute = self._download(f"{year}/{month - 1:02d}/{day:02d}/{self._side}_candles_min_1.bi5", day_start)
            if minute is not None:
                days.append(minute)
        return resample_ohlcv(_concat(days), Timeframe.HOURLY)

    def _download(self, path: str, period_start: datetime) -> pd.DataFrame | None:
        """Fetch and decode one bi5 file. Returns ``None`` if it does not exist."""
        url = f"{self._base_url}/{self.settings.symbol}/{path}"
        response = self._request(url, allow_404=True)
        if response is None:
            return None
        log.debug("Fetched %s (%d bytes)", url, len(response.content))
        return decode_bi5_candles(response.content, period_start, self._point)


def decode_bi5_candles(content: bytes, period_start: datetime, point: float) -> pd.DataFrame:
    """Decode a Dukascopy bi5 candle file into an OHLCV frame."""
    if not content:
        return empty_ohlcv()
    try:
        raw = lzma.decompress(content)
    except lzma.LZMAError as exc:
        raise ProviderError(f"Corrupt Dukascopy file for period starting {period_start:%Y-%m-%d}") from exc

    usable = len(raw) - len(raw) % _RECORD.size
    records = list(_RECORD.iter_unpack(raw[:usable]))
    if not records:
        return empty_ohlcv()

    frame = pd.DataFrame(records, columns=_RAW_COLUMNS)
    frame["Date"] = pd.Timestamp(period_start) + pd.to_timedelta(frame["Offset"], unit="s")
    for column in ("Open", "High", "Low", "Close"):
        frame[column] = frame[column] / point
    frame["Volume"] = frame["Volume"].astype(float)
    return frame[OHLCV_COLUMNS]


def resample_ohlcv(frame: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """Aggregate finer candles into ``timeframe`` candles (UTC, left-labelled)."""
    if frame.empty:
        return empty_ohlcv()
    frame = _drop_closed_market_candles(frame)
    resampled = (
        frame.set_index("Date")
        .resample(timeframe.pandas_freq, label="left", closed="left")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Open"])
        .reset_index()
    )
    return resampled[OHLCV_COLUMNS]


def _drop_closed_market_candles(frame: pd.DataFrame) -> pd.DataFrame:
    """Dukascopy emits flat, zero-volume candles while the market is closed (weekends)."""
    if frame.empty:
        return frame
    flat = (
        (frame["Volume"] == 0)
        & (frame["Open"] == frame["High"])
        & (frame["High"] == frame["Low"])
        & (frame["Low"] == frame["Close"])
    )
    return frame.loc[~flat].reset_index(drop=True)


def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else empty_ohlcv()


def _add_month(value: datetime) -> datetime:
    return value.replace(year=value.year + 1, month=1) if value.month == 12 else value.replace(month=value.month + 1)
