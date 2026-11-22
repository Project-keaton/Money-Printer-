"""Unit tests for the historical data pipeline (no network access needed)."""

from __future__ import annotations

import lzma
import struct
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from data_pipeline.config import ConfigError, Settings, Timeframe, load_settings
from data_pipeline.downloader import DownloadError, ForexDownloader
from data_pipeline.providers.alpha_vantage import AlphaVantageProvider
from data_pipeline.providers.base import AuthenticationError, BaseProvider, Chunk, ProviderError, RateLimitError
from data_pipeline.providers.dukascopy import DukascopyProvider, decode_bi5_candles, resample_ohlcv
from data_pipeline.providers.oanda import OandaProvider
from data_pipeline.providers.twelve_data import TwelveDataProvider
from data_pipeline.storage import verify_yearly_files, write_yearly_csv
from data_pipeline.transforms import fold_sundays_into_monday
from data_pipeline.validator import DataValidationError, find_gaps, validate_ohlcv


def make_settings(tmp_path: Path, **kwargs: object) -> Settings:
    defaults: dict[str, object] = dict(
        provider="dukascopy",
        symbol="EURUSD",
        timeframe=Timeframe.DAILY,
        start_date=date(2016, 1, 1),
        end_date=date(2017, 12, 31),
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        report_dir=tmp_path / "reports",
        max_retries=0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


def candles(dates: list[str], **overrides: list[float]) -> pd.DataFrame:
    n = len(dates)
    data = {
        "Date": dates,
        "Open": [1.10] * n,
        "High": [1.12] * n,
        "Low": [1.09] * n,
        "Close": [1.11] * n,
        "Volume": [100.0] * n,
    }
    data.update(overrides)
    return pd.DataFrame(data)


# ----------------------------------------------------------------- config


def test_load_settings_requires_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OANDA_API_KEY"):
        load_settings(None, {"DATA_PROVIDER": "oanda"})


def test_load_settings_normalises_provider_and_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "secret")
    settings = load_settings(None, {"DATA_PROVIDER": "Twelve_Data", "DATA_SYMBOL": "eur/usd"})
    assert settings.provider == "twelvedata"
    assert settings.symbol == "EURUSD"
    assert "secret" not in repr(settings)


def test_load_settings_rejects_bad_dates() -> None:
    with pytest.raises(ConfigError):
        load_settings(None, {"DATA_START_DATE": "2020-13-01"})
    with pytest.raises(ConfigError):
        load_settings(None, {"DATA_START_DATE": "2020-01-01", "DATA_END_DATE": "2019-01-01"})


def test_dukascopy_is_default_and_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATA_PROVIDER", "DUKASCOPY_PRICE_SIDE", "DUKASCOPY_BASE_URL", "DUKASCOPY_REQUEST_INTERVAL"):
        monkeypatch.delenv(name, raising=False)
    assert load_settings(None).provider == "dukascopy"

    settings = load_settings(None, {
        "DUKASCOPY_PRICE_SIDE": "ask",
        "DUKASCOPY_BASE_URL": "https://mirror.example/datafeed/",
        "DUKASCOPY_REQUEST_INTERVAL": "2.5",
    })
    assert settings.dukascopy_price_side == "ASK"
    assert settings.dukascopy_base_url == "https://mirror.example/datafeed"
    assert settings.dukascopy_request_interval == 2.5
    with pytest.raises(ConfigError):
        load_settings(None, {"DUKASCOPY_PRICE_SIDE": "MID"})


def test_download_window_excludes_incomplete_candle(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, end_date=date(2026, 11, 22))
    now = datetime(2026, 11, 22, 15, 30, tzinfo=timezone.utc)
    _, end = settings.download_window(now)
    assert end == datetime(2026, 11, 22, tzinfo=timezone.utc)

    hourly = make_settings(tmp_path, end_date=date(2026, 11, 22), timeframe=Timeframe.HOURLY)
    _, end = hourly.download_window(now)
    assert end == datetime(2026, 11, 22, 15, tzinfo=timezone.utc)


# -------------------------------------------------------------- validator


def test_validator_removes_duplicates_nulls_and_invalid_rows() -> None:
    df = candles(
        ["2024-01-02", "2024-01-03", "2024-01-03", "2024-01-04", "bad-date", "2024-01-05"],
        High=[1.12, 1.12, 1.12, 1.08, 1.12, 1.12],  # 2024-01-04: High below Low -> invalid
    )
    clean, report = validate_ohlcv(df, Timeframe.DAILY)

    assert report.duplicates_removed == 1
    assert report.null_rows_removed == 1
    assert report.invalid_rows_removed == 1
    assert list(clean["Date"].dt.strftime("%Y-%m-%d")) == ["2024-01-02", "2024-01-03", "2024-01-05"]
    assert clean["Date"].is_monotonic_increasing


def test_validator_requires_columns() -> None:
    with pytest.raises(DataValidationError, match="Volume"):
        validate_ohlcv(pd.DataFrame({"Date": [], "Open": [], "High": [], "Low": [], "Close": []}), Timeframe.DAILY)


def test_find_gaps_ignores_weekends_and_holidays() -> None:
    # Fri 2023-12-22 -> Wed 2023-12-27: weekend and 25 Dec are expected closures, 26 Dec is missing.
    dates = pd.Series(pd.to_datetime(["2023-12-22", "2023-12-27"], utc=True))
    gaps = find_gaps(dates, Timeframe.DAILY)
    assert len(gaps) == 1
    assert gaps[0].missing_periods == 1
    assert gaps[0].start.strftime("%Y-%m-%d") == "2023-12-26"


def test_find_gaps_hourly_weekend_is_not_a_gap() -> None:
    dates = pd.Series(pd.to_datetime(["2024-01-05 20:00", "2024-01-07 22:00"], utc=True))
    assert find_gaps(dates, Timeframe.HOURLY) == []


# ------------------------------------------------------------- transforms


def test_fold_sundays_into_monday() -> None:
    df = pd.DataFrame(
        {
            # Fri, Sun, Mon, Tue, then a Sunday at the end with no Monday after it.
            "Date": pd.to_datetime(["2024-01-05", "2024-01-07", "2024-01-08", "2024-01-09", "2024-01-14"], utc=True),
            "Open": [1.090, 1.095, 1.096, 1.100, 1.110],
            "High": [1.095, 1.105, 1.099, 1.104, 1.112],  # Sunday high is the higher one
            "Low": [1.085, 1.094, 1.090, 1.098, 1.108],  # Monday low is the lower one
            "Close": [1.094, 1.096, 1.097, 1.101, 1.111],
            "Volume": [100.0, 5.0, 120.0, 110.0, 4.0],
        }
    )
    out, report = fold_sundays_into_monday(df)

    assert list(out["Date"].dt.strftime("%a")) == ["Fri", "Mon", "Tue"]
    monday = out.iloc[1]
    assert (monday.Open, monday.High, monday.Low, monday.Close, monday.Volume) == (1.095, 1.105, 1.090, 1.097, 125.0)
    assert out.iloc[0].Open == 1.090 and out.iloc[2].Volume == 110.0  # other days untouched
    assert report.sundays_folded == 1
    assert report.unmatched_sundays == ["2024-01-14"]
    assert (report.input_rows, report.output_rows) == (5, 3)
    assert df.iloc[2].Open == 1.096  # input not mutated


def test_fold_across_year_boundary() -> None:
    df = candles(["2023-12-29", "2023-12-31", "2024-01-01"], Volume=[1.0, 2.0, 3.0])
    clean, _ = validate_ohlcv(df, Timeframe.DAILY)
    out, report = fold_sundays_into_monday(clean)
    assert list(out["Date"].dt.strftime("%Y-%m-%d")) == ["2023-12-29", "2024-01-01"]
    assert out.iloc[1].Volume == 5.0 and report.sundays_folded == 1


# ---------------------------------------------------------------- storage


def test_write_and_verify_yearly_files(tmp_path: Path) -> None:
    df = candles(["2016-12-30", "2017-01-02", "2017-01-03"])
    clean, _ = validate_ohlcv(df, Timeframe.DAILY)
    data_dir = tmp_path / "nested" / "data"  # created automatically

    files = write_yearly_csv(clean, data_dir, "EURUSD", Timeframe.DAILY)

    assert [f.path.name for f in files] == ["EURUSD_2016.csv", "EURUSD_2017.csv"]
    assert [f.rows for f in files] == [1, 2]
    assert (data_dir / "EURUSD_2017.csv").read_text().splitlines()[0] == "Date,Open,High,Low,Close,Volume"

    checks = verify_yearly_files(data_dir, "EURUSD", [2016, 2017, 2018])
    assert [c.ok for c in checks] == [True, True, False]
    assert checks[2].problems == ["file not found"]


# -------------------------------------------------------------- dukascopy


def test_decode_bi5_candles() -> None:
    record = struct.Struct(">5if")
    raw = record.pack(0, 110000, 110500, 109800, 111000, 12.5) + record.pack(86400, 110500, 110200, 110000, 110700, 8.0)
    content = lzma.compress(raw, format=lzma.FORMAT_ALONE)

    df = decode_bi5_candles(content, datetime(2016, 1, 1, tzinfo=timezone.utc), 100_000.0)

    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert df.loc[1, "Date"] == pd.Timestamp("2016-01-02", tz="UTC")
    first = df.iloc[0]
    assert (first.Open, first.High, first.Low, first.Close, first.Volume) == (1.1, 1.11, 1.098, 1.105, 12.5)


def test_decode_empty_bi5_file() -> None:
    assert decode_bi5_candles(b"", datetime(2016, 1, 1, tzinfo=timezone.utc), 100_000.0).empty


def test_resample_hourly_to_daily() -> None:
    hourly = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-02 00:00", "2024-01-02 01:00", "2024-01-03 00:00"], utc=True),
            "Open": [1.0, 1.1, 1.2],
            "High": [1.2, 1.3, 1.25],
            "Low": [0.9, 1.0, 1.1],
            "Close": [1.1, 1.2, 1.15],
            "Volume": [1.0, 2.0, 3.0],
        }
    )
    daily = resample_ohlcv(hourly, Timeframe.DAILY)
    assert len(daily) == 2
    first = daily.iloc[0]
    assert (first.Open, first.High, first.Low, first.Close, first.Volume) == (1.0, 1.3, 0.9, 1.2, 3.0)


# ------------------------------------------------------------- downloader


class FakeProvider(BaseProvider):
    name = "fake"
    display_name = "Fake"

    def __init__(self, settings: Settings, fail_years: set[int]) -> None:
        super().__init__(settings)
        self.fail_years = fail_years

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        if chunk.start.year in self.fail_years:
            raise ProviderError("simulated outage")
        # Include one row outside the chunk; the downloader must clip it.
        return candles([f"{chunk.start.year}-03-01", f"{chunk.start.year + 5}-01-01"])


def test_downloader_continues_after_failed_chunk(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    result = ForexDownloader(FakeProvider(settings, fail_years={2016}), settings).run(show_progress=False)

    assert result.chunks_total == 2
    assert [f.chunk.start.year for f in result.failed_chunks] == [2016]
    assert result.records_downloaded == 1
    assert not result.complete


class RateLimitedProvider(FakeProvider):
    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        if chunk.start.year >= 2017:
            raise RateLimitError("HTTP 429")
        return super().fetch_chunk(chunk)


def test_downloader_stops_early_on_rate_limit_and_keeps_data(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, end_date=date(2019, 12, 31))
    result = ForexDownloader(RateLimitedProvider(settings, fail_years=set()), settings).run(show_progress=False)

    assert result.records_downloaded == 1  # 2016 was saved
    assert len(result.failed_chunks) == 3  # 2017 failed, 2018-2019 skipped
    assert "skipped" in result.failed_chunks[-1].reason


# ------------------------------------------------- provider response parsing


class FakeResponse:
    def __init__(self, payload: object = None, status_code: int = 200, content: bytes = b"") -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = content
        self.text = "" if payload is None else str(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)

    def close(self) -> None:
        pass


CHUNK_2024 = Chunk(datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, tzinfo=timezone.utc))


def test_oanda_parses_candles_and_skips_incomplete(tmp_path: Path) -> None:
    payload = {
        "candles": [
            {"time": "2024-01-02T00:00:00.000000000Z", "volume": 120, "complete": True,
             "mid": {"o": "1.10", "h": "1.12", "l": "1.09", "c": "1.11"}},
            {"time": "2024-01-03T00:00:00.000000000Z", "volume": 50, "complete": False,
             "mid": {"o": "1.11", "h": "1.12", "l": "1.10", "c": "1.11"}},
        ]
    }
    session = FakeSession(FakeResponse(payload))
    settings = make_settings(tmp_path, provider="oanda", oanda_api_key="token")
    df = OandaProvider(settings, session).fetch_chunk(CHUNK_2024)  # type: ignore[arg-type]

    assert len(df) == 1 and df.iloc[0]["Close"] == 1.11 and df.iloc[0]["Volume"] == 120
    call = session.calls[0]
    assert str(call["url"]).endswith("/v3/instruments/EUR_USD/candles")
    assert call["params"]["granularity"] == "D"  # type: ignore[index]
    assert call["headers"]["Authorization"] == "Bearer token"  # type: ignore[index]


def test_oanda_auth_error_is_not_retried(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse({"errorMessage": "Insufficient authorization"}, status_code=401))
    settings = make_settings(tmp_path, provider="oanda", oanda_api_key="bad", max_retries=3)
    with pytest.raises(AuthenticationError):
        OandaProvider(settings, session).fetch_chunk(CHUNK_2024)  # type: ignore[arg-type]
    assert len(session.calls) == 1


def test_twelve_data_parses_values(tmp_path: Path) -> None:
    payload = {"status": "ok", "values": [
        {"datetime": "2024-01-02", "open": "1.10", "high": "1.12", "low": "1.09", "close": "1.11"},
    ]}
    settings = make_settings(tmp_path, provider="twelvedata", twelve_data_api_key="k")
    provider = TwelveDataProvider(settings, FakeSession(FakeResponse(payload)))  # type: ignore[arg-type]
    provider.request_interval = 0
    df = provider.fetch_chunk(CHUNK_2024)
    assert df.iloc[0]["Open"] == 1.10 and df.iloc[0]["Volume"] == 0


def test_twelve_data_body_error_raises(tmp_path: Path) -> None:
    payload = {"status": "error", "code": 401, "message": "**apikey** parameter is incorrect"}
    settings = make_settings(tmp_path, provider="twelvedata", twelve_data_api_key="k")
    provider = TwelveDataProvider(settings, FakeSession(FakeResponse(payload)))  # type: ignore[arg-type]
    provider.request_interval = 0
    with pytest.raises(AuthenticationError):
        provider.fetch_chunk(CHUNK_2024)


def test_alpha_vantage_parses_series_and_reports_notices(tmp_path: Path) -> None:
    payload = {"Time Series FX (Daily)": {
        "2024-01-02": {"1. open": "1.10", "2. high": "1.12", "3. low": "1.09", "4. close": "1.11"},
    }}
    settings = make_settings(tmp_path, provider="alphavantage", alpha_vantage_api_key="k")
    provider = AlphaVantageProvider(settings, FakeSession(FakeResponse(payload)))  # type: ignore[arg-type]
    provider.request_interval = 0
    assert provider.fetch_chunk(CHUNK_2024).iloc[0]["High"] == 1.12

    notice = {"Information": "This is a premium endpoint."}
    provider = AlphaVantageProvider(settings, FakeSession(FakeResponse(notice)))  # type: ignore[arg-type]
    provider.request_interval = 0
    with pytest.raises(ProviderError, match="premium"):
        provider.fetch_chunk(CHUNK_2024)


def test_dukascopy_builds_current_year_from_hourly_files(tmp_path: Path) -> None:
    record = struct.Struct(">5if")
    hourly = lzma.compress(
        record.pack(24 * 3600, 110000, 110500, 109800, 111000, 1.0)  # 2 Jan 00:00
        + record.pack(25 * 3600, 110500, 110200, 110000, 110700, 2.0),  # 2 Jan 01:00
        format=lzma.FORMAT_ALONE,
    )
    settings = make_settings(tmp_path)
    session = FakeSession(FakeResponse(status_code=404), FakeResponse(content=hourly))
    provider = DukascopyProvider(settings, session)  # type: ignore[arg-type]
    provider.request_interval = 0
    provider._now = datetime(2024, 1, 15, tzinfo=timezone.utc)

    df = provider.fetch_chunk(CHUNK_2024)

    assert len(df) == 1
    assert (df.iloc[0]["Open"], df.iloc[0]["Close"], df.iloc[0]["Volume"]) == (1.1, 1.102, 3.0)
    assert str(session.calls[1]["url"]).endswith("EURUSD/2024/00/BID_candles_hour_1.bi5")


def test_dukascopy_uses_configured_endpoint_side_and_monthly_chunks(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, timeframe=Timeframe.HOURLY, dukascopy_price_side="ASK",
        dukascopy_base_url="https://mirror.example/feed", dukascopy_request_interval=0.0,
    )
    session = FakeSession(FakeResponse(content=b""))
    provider = DukascopyProvider(settings, session)  # type: ignore[arg-type]

    chunks = provider.plan_chunks(*settings.download_window())
    assert len(chunks) == 24  # 2016-2017, one per month
    provider.fetch_chunk(chunks[1])
    assert session.calls[0]["url"] == "https://mirror.example/feed/EURUSD/2016/01/ASK_candles_hour_1.bi5"


def test_rate_limit_exhaustion_raises_rate_limit_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, provider="oanda", oanda_api_key="t", max_retries=0)
    session = FakeSession(FakeResponse({"error": "Too Many Requests"}, status_code=429))
    with pytest.raises(RateLimitError):
        OandaProvider(settings, session).fetch_chunk(CHUNK_2024)  # type: ignore[arg-type]


def test_downloader_raises_when_everything_fails(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with pytest.raises(DownloadError):
        ForexDownloader(FakeProvider(settings, fail_years={2016, 2017}), settings).run(show_progress=False)
