"""Configuration for the historical data pipeline.

All settings come from environment variables, which are normally supplied by a
git-ignored ``.env`` file in the project root (see ``.env.example``). API keys
are only ever read from there and are never logged or written to reports.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from enum import StrEnum
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE: Path = PROJECT_ROOT / ".env"

#: Number of years the pipeline is expected to cover by default.
DEFAULT_HISTORY_YEARS: int = 10

#: Provider id -> environment variable holding its API key (``None`` = no key needed).
PROVIDER_API_KEY_ENV: dict[str, str | None] = {
    "oanda": "OANDA_API_KEY",
    "twelvedata": "TWELVE_DATA_API_KEY",
    "alphavantage": "ALPHA_VANTAGE_API_KEY",
    "dukascopy": None,
}

OANDA_ENVIRONMENTS: frozenset[str] = frozenset({"practice", "live"})
DUKASCOPY_DEFAULT_BASE_URL: str = "https://datafeed.dukascopy.com/datafeed"
DUKASCOPY_PRICE_SIDES: frozenset[str] = frozenset({"BID", "ASK"})
LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigError(ValueError):
    """Raised when the configuration is missing or invalid."""


class Timeframe(StrEnum):
    """Candle timeframes supported by the pipeline."""

    DAILY = "1d"
    HOURLY = "1h"

    @property
    def step(self) -> timedelta:
        """Duration of one candle."""
        return timedelta(days=1) if self is Timeframe.DAILY else timedelta(hours=1)

    @property
    def pandas_freq(self) -> str:
        """Equivalent pandas frequency string."""
        return "1D" if self is Timeframe.DAILY else "1h"

    @property
    def date_format(self) -> str:
        """``strftime`` format used for the ``Date`` column in CSV output."""
        return "%Y-%m-%d" if self is Timeframe.DAILY else "%Y-%m-%d %H:%M:%S"

    @property
    def unit(self) -> str:
        return "day" if self is Timeframe.DAILY else "hour"


def normalise_provider_name(name: str) -> str:
    """Map user input such as ``"Twelve Data"`` or ``"alpha_vantage"`` to a provider id."""
    return "".join(ch for ch in name.strip().lower() if ch.isalnum())


@dataclass(frozen=True)
class Settings:
    """Validated, immutable pipeline settings."""

    provider: str
    symbol: str
    timeframe: Timeframe
    start_date: date
    end_date: date
    data_dir: Path
    log_dir: Path
    report_dir: Path
    log_level: str = "INFO"
    request_timeout: float = 30.0
    max_retries: int = 5
    oanda_environment: str = "practice"
    #: Also build a Monday-Friday daily dataset with Sunday candles folded into Monday.
    build_weekday_dataset: bool = True
    weekday_data_dir: Path = PROJECT_ROOT / "data" / "weekday"
    dukascopy_base_url: str = DUKASCOPY_DEFAULT_BASE_URL
    dukascopy_price_side: str = "BID"
    dukascopy_request_interval: float = 1.0
    # Secrets are excluded from repr() so they never end up in logs or tracebacks.
    oanda_api_key: str = field(default="", repr=False)
    twelve_data_api_key: str = field(default="", repr=False)
    alpha_vantage_api_key: str = field(default="", repr=False)

    @property
    def base_currency(self) -> str:
        return self.symbol[:3]

    @property
    def quote_currency(self) -> str:
        return self.symbol[3:]

    @property
    def display_symbol(self) -> str:
        """Human-readable symbol, e.g. ``EUR/USD``."""
        return f"{self.base_currency}/{self.quote_currency}"

    @property
    def api_key(self) -> str:
        """API key for the selected provider (empty string if none is needed)."""
        return {
            "oanda": self.oanda_api_key,
            "twelvedata": self.twelve_data_api_key,
            "alphavantage": self.alpha_vantage_api_key,
        }.get(self.provider, "")

    def download_window(self, now: datetime | None = None) -> tuple[datetime, datetime]:
        """Return the UTC ``[start, end)`` interval to download.

        The end is clamped to the start of the current candle so that
        incomplete (still forming) candles are never saved.
        """
        now = now or datetime.now(timezone.utc)
        start = datetime.combine(self.start_date, dtime.min, tzinfo=timezone.utc)
        end = datetime.combine(self.end_date + timedelta(days=1), dtime.min, tzinfo=timezone.utc)

        if self.timeframe is Timeframe.DAILY:
            current_candle = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            current_candle = now.replace(minute=0, second=0, microsecond=0)
        end = min(end, current_candle)

        if end <= start:
            raise ConfigError(
                f"Nothing to download: start {start:%Y-%m-%d} is not before the "
                f"last complete candle ({end:%Y-%m-%d %H:%M} UTC)."
            )
        return start, end

    def expected_years(self, now: datetime | None = None) -> list[int]:
        """Calendar years covered by the download window."""
        start, end = self.download_window(now)
        last = end - timedelta(microseconds=1)
        return list(range(start.year, last.year + 1))


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_settings(
    env_file: Path | None = DEFAULT_ENV_FILE,
    overrides: dict[str, str | None] | None = None,
) -> Settings:
    """Build :class:`Settings` from the environment.

    Precedence: ``overrides`` (CLI flags) > real environment variables > ``.env`` file > defaults.

    Raises:
        ConfigError: if any value is missing or invalid.
    """
    if env_file is not None:
        if env_file.exists():
            # override=False keeps real environment variables ahead of the file.
            load_dotenv(env_file, override=False, encoding="utf-8")
        elif env_file != DEFAULT_ENV_FILE:
            raise ConfigError(f"Config file not found: {env_file}")

    overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}

    def get(name: str, default: str = "") -> str:
        if name in overrides:
            return str(overrides[name]).strip()
        return os.getenv(name, default).strip()

    today = datetime.now(timezone.utc).date()

    provider = normalise_provider_name(get("DATA_PROVIDER", "dukascopy"))
    if provider not in PROVIDER_API_KEY_ENV:
        raise ConfigError(
            f"Unknown DATA_PROVIDER '{provider}'. Choose one of: {', '.join(PROVIDER_API_KEY_ENV)}."
        )

    symbol = get("DATA_SYMBOL", "EURUSD").upper().replace("/", "").replace("_", "")
    if len(symbol) != 6 or not symbol.isalpha():
        raise ConfigError(f"DATA_SYMBOL must be a 6-letter currency pair such as EURUSD, got '{symbol}'.")

    try:
        timeframe = Timeframe(get("DATA_TIMEFRAME", Timeframe.DAILY.value).lower())
    except ValueError:
        raise ConfigError(
            f"DATA_TIMEFRAME must be one of: {', '.join(t.value for t in Timeframe)}."
        ) from None

    default_start = date(today.year - DEFAULT_HISTORY_YEARS, 1, 1)
    start_date = _parse_date("DATA_START_DATE", get("DATA_START_DATE"), default_start)
    end_date = _parse_date("DATA_END_DATE", get("DATA_END_DATE"), today)
    if end_date > today:
        logging.getLogger(__name__).info("DATA_END_DATE %s is in the future; using %s", end_date, today)
        end_date = today
    if start_date >= end_date:
        raise ConfigError(f"DATA_START_DATE ({start_date}) must be before DATA_END_DATE ({end_date}).")

    log_level = get("LOG_LEVEL", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(sorted(LOG_LEVELS))}.")

    oanda_environment = get("OANDA_ENVIRONMENT", "practice").lower()
    if oanda_environment not in OANDA_ENVIRONMENTS:
        raise ConfigError("OANDA_ENVIRONMENT must be 'practice' or 'live'.")

    dukascopy_price_side = get("DUKASCOPY_PRICE_SIDE", "BID").upper()
    if dukascopy_price_side not in DUKASCOPY_PRICE_SIDES:
        raise ConfigError("DUKASCOPY_PRICE_SIDE must be 'BID' or 'ASK'.")
    dukascopy_base_url = get("DUKASCOPY_BASE_URL", DUKASCOPY_DEFAULT_BASE_URL).rstrip("/")
    if not dukascopy_base_url.startswith(("https://", "http://")):
        raise ConfigError("DUKASCOPY_BASE_URL must start with https:// or http://.")
    dukascopy_request_interval = _parse_number(
        "DUKASCOPY_REQUEST_INTERVAL", get("DUKASCOPY_REQUEST_INTERVAL", "1.0"), float, minimum=0.0
    )

    build_weekday_dataset = _parse_bool("BUILD_WEEKDAY_DATASET", get("BUILD_WEEKDAY_DATASET", "true"))

    request_timeout = _parse_number("HTTP_TIMEOUT", get("HTTP_TIMEOUT", "30"), float, minimum=1)
    max_retries = _parse_number("HTTP_MAX_RETRIES", get("HTTP_MAX_RETRIES", "5"), int, minimum=0)

    settings = Settings(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        data_dir=_resolve_path(get("DATA_DIR", "data")),
        log_dir=_resolve_path(get("LOG_DIR", "logs")),
        report_dir=_resolve_path(get("REPORT_DIR", "reports")),
        log_level=log_level,
        request_timeout=request_timeout,
        max_retries=max_retries,
        oanda_environment=oanda_environment,
        build_weekday_dataset=build_weekday_dataset,
        weekday_data_dir=_resolve_path(get("WEEKDAY_DATA_DIR", "data/weekday")),
        dukascopy_base_url=dukascopy_base_url,
        dukascopy_price_side=dukascopy_price_side,
        dukascopy_request_interval=dukascopy_request_interval,
        oanda_api_key=get("OANDA_API_KEY"),
        twelve_data_api_key=get("TWELVE_DATA_API_KEY"),
        alpha_vantage_api_key=get("ALPHA_VANTAGE_API_KEY"),
    )

    key_env = PROVIDER_API_KEY_ENV[provider]
    if key_env and not settings.api_key:
        location = env_file if env_file is not None else "the environment"
        raise ConfigError(
            f"{key_env} is required for provider '{provider}'. "
            f"Add it to {location} (copy .env.example to .env first)."
        )
    return settings


def _parse_date(name: str, value: str, default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ConfigError(f"{name} must be a date in YYYY-MM-DD format, got '{value}'.") from None


def _parse_number[T: (int, float)](name: str, value: str, kind: type[T], *, minimum: T) -> T:
    try:
        number = kind(value)
    except ValueError:
        raise ConfigError(f"{name} must be a {kind.__name__}, got '{value}'.") from None
    if number < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {number}.")
    return number


def _parse_bool(name: str, value: str) -> bool:
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got '{value}'.")


def _resolve_path(value: str) -> Path:
    """Resolve a path relative to the project root (absolute paths are kept)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path
