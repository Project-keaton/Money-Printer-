"""Backtest configuration loaded from ``config.yaml``.

Sections used: ``backtest``, ``execution``, ``risk``, ``strategy`` and ``logging``.
Every value is validated on load, so a typo fails fast with a clear message
instead of producing a silently wrong backtest.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config.yaml"

StopMode = Literal["pips", "atr", "none"]
TargetMode = Literal["pips", "atr", "risk_reward", "none"]


class ConfigError(ValueError):
    """The configuration file is missing or contains an invalid value."""


# --------------------------------------------------------------------------- #
# Settings objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Instrument:
    """Contract details of the traded currency pair."""

    symbol: str
    pip_size: float
    contract_size: int
    account_currency: str

    @property
    def base(self) -> str:
        return self.symbol[:3]

    @property
    def quote(self) -> str:
        return self.symbol[3:]

    def quote_to_account(self, price: float) -> float:
        """Factor converting an amount in the quote currency into the account currency.

        EUR/USD with a USD account -> 1. USD/JPY with a USD account -> 1 / price.
        """
        if self.quote == self.account_currency:
            return 1.0
        if self.base == self.account_currency:
            return 1.0 / price
        raise ConfigError(
            f"Cannot convert {self.quote} P&L to {self.account_currency} for {self.symbol}: "
            "cross pairs need a conversion rate series, which is not supported yet."
        )

    def to_pips(self, price_distance: float) -> float:
        return price_distance / self.pip_size


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    price_basis: Literal["mid", "bid"] = "mid"
    spread_pips: float = 1.0
    commission_per_lot: float = 7.0
    slippage_pips: float = 0.2
    intrabar_priority: Literal["stop_loss", "take_profit"] = "stop_loss"


@dataclass(frozen=True, slots=True)
class StopLossSettings:
    mode: StopMode = "atr"
    pips: float = 30.0
    atr_period: int = 14
    atr_multiplier: float = 2.0


@dataclass(frozen=True, slots=True)
class TakeProfitSettings:
    mode: TargetMode = "risk_reward"
    pips: float = 60.0
    atr_period: int = 14
    atr_multiplier: float = 3.0
    risk_reward: float = 2.0


@dataclass(frozen=True, slots=True)
class RiskSettings:
    position_sizing: Literal["risk", "fixed"] = "risk"
    risk_per_trade: float = 0.01
    fixed_lots: float = 0.10
    min_lot: float = 0.01
    lot_step: float = 0.01
    max_lots: float = 50.0
    max_leverage: float = 30.0
    stop_loss: StopLossSettings = field(default_factory=StopLossSettings)
    take_profit: TakeProfitSettings = field(default_factory=TakeProfitSettings)


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str = "EURUSD"
    data_dir: Path = PROJECT_ROOT / "data"
    dataset: Literal["weekday", "raw"] = "weekday"
    start_date: date | None = None
    end_date: date | None = None
    account_currency: str = "USD"
    starting_balance: float = 10_000.0
    allow_multiple_positions: bool = False
    max_open_trades: int = 3
    close_on_opposite_signal: bool = True
    close_open_trades_at_end: bool = True
    contract_size: int = 100_000
    pip_size: float | None = None
    risk_free_rate: float = 0.0
    reports_dir: Path = PROJECT_ROOT / "reports"
    charts_dir: Path = PROJECT_ROOT / "reports" / "charts"
    log_dir: Path = PROJECT_ROOT / "logs"
    log_level: str = "INFO"
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)
    risk: RiskSettings = field(default_factory=RiskSettings)
    strategy_name: str = "ema_crossover"
    strategy_params: dict[str, Any] = field(default_factory=dict)

    @property
    def dataset_dir(self) -> Path:
        """Folder holding the yearly CSV files for the selected dataset."""
        return self.data_dir / "weekday" if self.dataset == "weekday" else self.data_dir

    @property
    def instrument(self) -> Instrument:
        pip = self.pip_size or (0.01 if self.symbol.endswith("JPY") else 0.0001)
        return Instrument(self.symbol, pip, self.contract_size, self.account_currency)

    @property
    def max_positions(self) -> int:
        return self.max_open_trades if self.allow_multiple_positions else 1


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_config(path: Path = DEFAULT_CONFIG_PATH, overrides: dict[str, Any] | None = None) -> BacktestConfig:
    """Read and validate ``config.yaml``.

    Args:
        path: YAML file to read.
        overrides: dotted keys that replace file values, e.g.
            ``{"execution.spread_pips": 0.5, "strategy.active": "rsi_reversal"}``.
            ``None`` values are ignored.

    Raises:
        ConfigError: if the file is missing, unreadable or invalid.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")

    raw = copy.deepcopy(raw)
    for dotted, value in (overrides or {}).items():
        if value is not None:
            _set_dotted(raw, dotted, value)

    bt = _Section(raw, "backtest")
    ex = _Section(raw, "execution")
    rk = _Section(raw, "risk")
    sl = _Section(rk.data, "stop_loss", prefix="risk.")
    tp = _Section(rk.data, "take_profit", prefix="risk.")
    st = _Section(raw, "strategy")
    lg = _Section(raw, "logging")

    symbol = str(bt.get("symbol", "EURUSD")).upper().replace("/", "")
    if len(symbol) != 6 or not symbol.isalpha():
        raise ConfigError(f"backtest.symbol must be a 6-letter pair such as EURUSD, got '{symbol}'")

    execution = ExecutionSettings(
        price_basis=ex.choice("price_basis", ("mid", "bid"), "mid"),
        spread_pips=ex.number("spread_pips", 1.0, minimum=0),
        commission_per_lot=ex.number("commission_per_lot", 7.0, minimum=0),
        slippage_pips=ex.number("slippage_pips", 0.2, minimum=0),
        intrabar_priority=ex.choice("intrabar_priority", ("stop_loss", "take_profit"), "stop_loss"),
    )
    stop_loss = StopLossSettings(
        mode=sl.choice("mode", ("pips", "atr", "none"), "atr"),
        pips=sl.number("pips", 30.0, minimum=0, exclusive=True),
        atr_period=sl.integer("atr_period", 14, minimum=1),
        atr_multiplier=sl.number("atr_multiplier", 2.0, minimum=0, exclusive=True),
    )
    take_profit = TakeProfitSettings(
        mode=tp.choice("mode", ("pips", "atr", "risk_reward", "none"), "risk_reward"),
        pips=tp.number("pips", 60.0, minimum=0, exclusive=True),
        atr_period=tp.integer("atr_period", 14, minimum=1),
        atr_multiplier=tp.number("atr_multiplier", 3.0, minimum=0, exclusive=True),
        risk_reward=tp.number("risk_reward", 2.0, minimum=0, exclusive=True),
    )
    risk = RiskSettings(
        position_sizing=rk.choice("position_sizing", ("risk", "fixed"), "risk"),
        risk_per_trade=rk.number("risk_per_trade", 0.01, minimum=0, maximum=1, exclusive=True),
        fixed_lots=rk.number("fixed_lots", 0.10, minimum=0, exclusive=True),
        min_lot=rk.number("min_lot", 0.01, minimum=0, exclusive=True),
        lot_step=rk.number("lot_step", 0.01, minimum=0, exclusive=True),
        max_lots=rk.number("max_lots", 50.0, minimum=0, exclusive=True),
        max_leverage=rk.number("max_leverage", 30.0, minimum=0, exclusive=True),
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    if risk.position_sizing == "risk" and stop_loss.mode == "none":
        raise ConfigError("risk.position_sizing 'risk' needs a stop loss; set risk.stop_loss.mode or use 'fixed'")
    if take_profit.mode == "risk_reward" and stop_loss.mode == "none":
        raise ConfigError("risk.take_profit.mode 'risk_reward' needs a stop loss (risk.stop_loss.mode)")
    if risk.min_lot > risk.max_lots:
        raise ConfigError("risk.min_lot must not exceed risk.max_lots")

    start_date = bt.date("start_date")
    end_date = bt.date("end_date")
    if start_date and end_date and start_date >= end_date:
        raise ConfigError("backtest.start_date must be before backtest.end_date")

    strategy_name = str(st.get("active", "ema_crossover")).strip().lower()
    strategy_params = st.get(strategy_name, {}) or {}
    if not isinstance(strategy_params, dict):
        raise ConfigError(f"strategy.{strategy_name} must be a mapping of parameters")

    log_level = str(lg.get("level", "INFO")).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(f"logging.level is invalid: {log_level}")

    pip_size = bt.get("pip_size")
    return BacktestConfig(
        symbol=symbol,
        data_dir=_path(bt.get("data_dir", "data")),
        dataset=bt.choice("dataset", ("weekday", "raw"), "weekday"),
        start_date=start_date,
        end_date=end_date,
        account_currency=str(bt.get("account_currency", "USD")).upper(),
        starting_balance=bt.number("starting_balance", 10_000.0, minimum=0, exclusive=True),
        allow_multiple_positions=bt.boolean("allow_multiple_positions", False),
        max_open_trades=bt.integer("max_open_trades", 3, minimum=1),
        close_on_opposite_signal=bt.boolean("close_on_opposite_signal", True),
        close_open_trades_at_end=bt.boolean("close_open_trades_at_end", True),
        contract_size=bt.integer("contract_size", 100_000, minimum=1),
        pip_size=None if pip_size is None else bt.number("pip_size", 0.0001, minimum=0, exclusive=True),
        risk_free_rate=bt.number("risk_free_rate", 0.0, minimum=-1, maximum=1),
        reports_dir=_path(bt.get("reports_dir", "reports")),
        charts_dir=_path(bt.get("charts_dir", "reports/charts")),
        log_dir=_path(lg.get("log_dir", "logs")),
        log_level=log_level,
        execution=execution,
        risk=risk,
        strategy_name=strategy_name,
        strategy_params=dict(strategy_params),
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Section:
    """Typed, validated access to one mapping in the YAML file."""

    def __init__(self, parent: dict[str, Any], name: str, prefix: str = "") -> None:
        value = parent.get(name) or {}
        if not isinstance(value, dict):
            raise ConfigError(f"'{prefix}{name}' must be a mapping")
        self.data = value
        self.name = f"{prefix}{name}"

    def get(self, key: str, default: Any = None) -> Any:
        value = self.data.get(key, default)
        return default if value is None else value

    def number(
        self, key: str, default: float, *, minimum: float | None = None,
        maximum: float | None = None, exclusive: bool = False,
    ) -> float:
        value = self.get(key, default)
        if isinstance(value, bool):
            raise ConfigError(f"{self.name}.{key} must be a number, got {value!r}")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{self.name}.{key} must be a number, got {value!r}") from None
        if minimum is not None and (number < minimum or (exclusive and number == minimum)):
            raise ConfigError(f"{self.name}.{key} must be {'>' if exclusive else '>='} {minimum}, got {number}")
        if maximum is not None and number > maximum:
            raise ConfigError(f"{self.name}.{key} must be <= {maximum}, got {number}")
        return number

    def integer(self, key: str, default: int, *, minimum: int | None = None) -> int:
        number = self.number(key, default, minimum=minimum)
        if number != int(number):
            raise ConfigError(f"{self.name}.{key} must be a whole number, got {number}")
        return int(number)

    def boolean(self, key: str, default: bool) -> bool:
        value = self.get(key, default)
        if not isinstance(value, bool):
            raise ConfigError(f"{self.name}.{key} must be true or false, got {value!r}")
        return value

    def choice[T: str](self, key: str, choices: tuple[T, ...], default: T) -> T:
        value = str(self.get(key, default)).strip().lower()
        for option in choices:
            if value == option:
                return option
        raise ConfigError(f"{self.name}.{key} must be one of {', '.join(choices)}, got '{value}'")

    def date(self, key: str) -> date | None:
        value = self.get(key)
        if value is None or value == "":
            return None
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            raise ConfigError(f"{self.name}.{key} must be a date (YYYY-MM-DD), got {value!r}") from None


def _set_dotted(data: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    node = data
    for key in parents:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[leaf] = value


def _path(value: str) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path
