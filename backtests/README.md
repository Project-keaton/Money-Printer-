# Backtesting Engine

Simulates a trading strategy on the historical EUR/USD data in `data/`,
including spread, commission, slippage, stop losses, take profits and
risk-based position sizing, then writes a full performance report with charts.

```
python -m backtests
```

## Architecture

```
config.yaml ──► config.py ─────────────── validated settings (costs, risk, strategy)
                   │
main.py ──► backtester.py ─────────────── orchestrates one run
              │
              ├─► data_loader.py ─────── data/weekday/EURUSD_<YEAR>.csv -> one validated frame
              ├─► strategies/ ───────── signals: 1 long, -1 short, 0 none (+ optional exits/stops)
              ├─► plan_order_distances ─ stop/target distances from config (pips, ATR, risk:reward)
              ├─► trade_engine.py ────── bar-by-bar fills, SL/TP, sizing, P&L, equity curve
              ├─► performance.py ─────── metrics, drawdown, monthly returns
              └─► report_generator.py ── performance_report.txt, CSVs, charts
```

| File | Responsibility |
|------|----------------|
| `main.py` | CLI entry point (`python -m backtests`), command-line overrides, exit codes |
| `config.py` | Loads and validates `config.yaml`; `Instrument` contract details |
| `data_loader.py` | Finds yearly files, skips corrupted ones, combines and validates them |
| `backtester.py` | `Backtester` class: data, signals, order planning, simulation, metrics |
| `trade_engine.py` | `TradeEngine`, `ExecutionModel` (spread/slippage/fills), `PositionSizer` |
| `performance.py` | `PerformanceMetrics`, trade log format, equity/drawdown, monthly returns |
| `report_generator.py` | Text report, CSV exports and charts |

Strategies live in `strategies/` (`EmaCrossoverStrategy`, `RsiReversalStrategy`,
`ModelSignalStrategy` for ML models) and share one interface (see *Writing a strategy*).

## How trades are simulated

| Rule | Behaviour |
|------|-----------|
| No look-ahead | A signal at a bar's **close** is executed at the **next bar's open** |
| Spread | `price_basis: mid` - half the spread is paid on every entry and every exit (a full spread per round trip). `bid` - buys fill at bid + spread |
| Slippage | Against you on market orders and stop-loss fills; take-profit limit orders fill at their price |
| Stop loss / take profit | Checked against every bar's high/low, including the entry bar. If a bar **opens** beyond a level (a gap), the fill is the open price |
| SL and TP in the same bar | `intrabar_priority` decides (default `stop_loss`, the conservative assumption) |
| Position size | `risk`: balance x `risk_per_trade` / stop distance, rounded **down** to `lot_step`, capped by `max_leverage` and `max_lots`; trades below `min_lot` are skipped. `fixed`: `fixed_lots` |
| Commission | `commission_per_lot` x lots, round turn, charged when the trade closes |
| Multiple trades | One at a time unless `allow_multiple_positions: true` (then up to `max_open_trades`) |
| Opposite signal | Closes open trades in the other direction before reversing (`close_on_opposite_signal`) |
| End of data | Open trades are closed at the last close (`close_open_trades_at_end`) |
| Equity | Balance + open-trade P&L marked at each bar's close, so drawdown includes open losses |

---

# Setup Guide

## 1. Prerequisites

* Python 3.12+
* The EUR/USD data already downloaded by the data pipeline:
  `data/EURUSD_<YEAR>.csv` and `data/weekday/EURUSD_<YEAR>.csv`.
  If they are missing, run `python -m data_pipeline` first (see `data_pipeline/README.md`).

## 2. Install dependencies

From the `ForexBot` folder:

```powershell
python -m venv .venv                      # skip if .venv already exists
.venv\Scripts\activate                    # macOS/Linux: source .venv/bin/activate
pip install -r data_pipeline/requirements.txt -r backtests/requirements.txt
```

## 3. Configure the backtest

Edit `config.yaml` in the project root. The main settings:

```yaml
backtest:
  dataset: weekday          # weekday = Mon-Fri candles (recommended), raw = includes Sunday candles
  start_date: null          # e.g. "2020-01-01"
  starting_balance: 10000
  allow_multiple_positions: false

execution:
  spread_pips: 1.0
  commission_per_lot: 7.0   # round turn per 100k lot
  slippage_pips: 0.2

risk:
  risk_per_trade: 0.01      # 1% of balance per trade
  stop_loss:
    mode: atr               # pips | atr | none
    pips: 30
    atr_multiplier: 2.0
  take_profit:
    mode: risk_reward       # pips | atr | risk_reward | none
    risk_reward: 2.0

strategy:
  active: ema_crossover     # ema_crossover | rsi_reversal
  ema_crossover:
    fast_period: 20
    slow_period: 50
```

Every value is validated when the backtest starts; a mistake produces a clear
`Configuration error: ...` message instead of a wrong result.

## 4. Run a backtest

```powershell
python -m backtests
```

Example output (numbers depend on your settings and data):

```
Backtesting ema_crossover on EURUSD (weekday dataset) ...
2016-01-04 -> 2026-11-20, 2,839 bars, 0.2s

Return -10.08% | Profit -$1,008.39 | Ending balance $8,991.61
Trades 55 | Win rate 27.27% | Profit factor 0.68 | Sharpe -0.32 | Max drawdown -15.32%

Report:       ...\ForexBot\reports\performance_report.txt
Trades:       ...\ForexBot\reports\trades.csv
Equity curve: ...\ForexBot\reports\equity_curve.csv
Charts:       ...\ForexBot\reports\charts (4 files)
```

Command-line options override `config.yaml` for one run:

```powershell
python -m backtests --strategy rsi_reversal
python -m backtests --start 2020-01-01 --end 2024-12-31
python -m backtests --spread 0.5 --commission 5 --slippage 0
python -m backtests --risk 0.5 --balance 25000        # risk 0.5% per trade
python -m backtests --dataset raw                     # include Sunday candles
python -m backtests --no-charts --log-level DEBUG     # DEBUG logs every order
python -m backtests --help
python main.py --mode backtest                        # same as python -m backtests
```

Exit codes: `0` success · `2` configuration error · `3` data or strategy error.

## 5. Read the results

Every run overwrites these files in `reports/`:

| File | Contents |
|------|----------|
| `performance_report.txt` | All metrics: balances, total return, profit, trade counts, win/loss rate, average/largest win and loss, profit factor, Sharpe ratio, maximum drawdown, average duration, expectancy, risk-reward ratio, costs and the settings used |
| `trades.csv` | One row per trade: Trade ID, Entry/Exit Date, Position Type, Entry/Exit Price, Stop Loss, Take Profit, Position Size (units), Lots, Profit/Loss, Return Percentage, Trade Duration, Pips, Commission, Exit Reason, Balance After, Cumulative P/L |
| `equity_curve.csv` | Per bar: Balance, Equity, CumulativeProfit, RealizedProfit, Drawdown, DrawdownPct, OpenTrades |
| `monthly_returns.csv` | Return per month and per year (%) |
| `charts/equity_curve.png` | Account equity over time |
| `charts/drawdown.png` | Drawdown from the running peak |
| `charts/monthly_returns.png` | Year x month heatmap (blue = gain, red = loss) |
| `charts/win_loss_distribution.png` | Histogram of profit/loss per trade |

Logs: `logs/backtest.log` (every trade at INFO level) and `logs/backtest_errors.log`.

**Metric definitions**

| Metric | Definition |
|--------|------------|
| Win / Loss Rate | Winning or losing trades / total trades (break-even trades count as neither) |
| Profit Factor | Gross profit / absolute gross loss |
| Expectancy Per Trade | Average net P/L per trade |
| Risk-Reward Ratio | Average win / absolute average loss |
| Sharpe Ratio | Mean per-bar equity return minus the risk-free rate, divided by its standard deviation, annualised by bars per year |
| Maximum Drawdown | Largest fall of mark-to-market equity from its running peak |
| Trade Duration | Time between the entry bar and exit bar; a trade opened and closed in the same bar shows `0h` |

## 6. Writing a strategy

Create a class in `strategies/` that returns signals; the engine handles
everything else.

```python
# strategies/atr_breakout.py
import pandas as pd
from strategies.base import LONG, SHORT, Strategy
from strategies.indicators import atr

class AtrBreakoutStrategy(Strategy):
    name = "atr_breakout"

    def __init__(self, lookback: int = 20, atr_period: int = 14, stop_atr: float = 1.5) -> None:
        super().__init__(lookback=lookback, atr_period=atr_period, stop_atr=stop_atr)
        self.lookback, self.atr_period, self.stop_atr = lookback, atr_period, stop_atr

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        high = data["High"].rolling(self.lookback).max().shift(1)   # shift(1): previous bars only
        low = data["Low"].rolling(self.lookback).min().shift(1)
        signals = pd.DataFrame({"signal": 0}, index=data.index)
        signals.loc[data["Close"] > high, "signal"] = LONG
        signals.loc[data["Close"] < low, "signal"] = SHORT
        signals["stop_distance"] = atr(data, self.atr_period) * self.stop_atr   # optional per-signal stop
        return signals
```

Register it in `strategies/__init__.py` (`STRATEGIES`), add its parameters under
`strategy:` in `config.yaml`, and run `python -m backtests --strategy atr_breakout`.

Optional signal columns: `exit_long`, `exit_short` (bool) and
`stop_distance`, `target_distance` (price units; override `config.yaml`).
A signal at bar *t* may only use data up to bar *t*'s close.

**Machine-learning models** use `strategies.ml_model.ModelSignalStrategy`,
which wraps any fitted classifier with `predict_proba` (scikit-learn, XGBoost):

```python
from backtests.backtester import Backtester
from backtests.config import load_config
from backtests.report_generator import ReportGenerator
from strategies.ml_model import ModelSignalStrategy

config = load_config()
strategy = ModelSignalStrategy(model, feature_builder, long_threshold=0.55, short_threshold=0.45)
result = Backtester(config, strategy).run()
ReportGenerator(config.reports_dir, config.charts_dir).generate(result)
```

Train the model on data **before** the backtest period (set
`backtest.start_date` after the training window) to avoid look-ahead bias.

## 7. Run the tests

```powershell
pytest
```

The engine tests use small synthetic price series with hand-calculated
expected fills and P&L, so they need no data files.

## Troubleshooting

| Message | Fix |
|---------|-----|
| `No EURUSD_<YEAR>.csv files in ...` | Run `python -m data_pipeline`, or check `backtest.data_dir` / `dataset` |
| `Skipped EURUSD_20xx.csv: ...` in the notes | That file is corrupted; re-download it with `python -m data_pipeline` |
| `N entry signal(s) skipped: position below minimum lot` | Stop too wide for the risk amount; raise `risk_per_trade` or lower `min_lot` |
| `... skipped: no stop distance (indicator warm-up)` | Normal for the first ATR-period bars |
| `Configuration error: ...` | Fix the named key in `config.yaml` |
