# ForexBot

A modular, Python-based Forex trading bot for researching, backtesting and running
rule-based and machine-learning trading strategies.

> **Disclaimer:** This software is for research and educational purposes. Trading
> foreign exchange on margin carries a high level of risk. Test thoroughly in
> backtest and paper modes before risking real capital.

## Features

- Historical data pipeline: 10+ years of EUR/USD from Dukascopy, OANDA, Twelve Data or Alpha Vantage, saved as yearly CSVs
- Technical-indicator strategies (EMA crossover, RSI) using `ta`
- Machine-learning strategies (`scikit-learn`, `xgboost`)
- Backtesting engine with spread, commission, slippage, SL/TP, risk-based sizing, full metrics and charts
- SQLite persistence through SQLAlchemy
- Dark-themed Streamlit + Plotly dashboard: KPIs, equity, trades, risk, monthly analytics, settings and data quality
- Three run modes: `backtest`, `paper`, `live`

## Architecture

```
            +-------------+     +--------------+     +--------------+
 market --> |    data/    | --> | strategies/  | --> |  backtests/  | --> reports/
 data       | ingestion & |     | signal       |     |  engine &    |
            | storage     |     | generation   |     |  metrics     |
            +-------------+     +------+-------+     +------+-------+
                                       ^                    |
                                       |                    v
                                +------+-------+     +--------------+
                                |   models/    |     |  database/   | --> dashboard/
                                | ML training  |     |  SQLite      |
                                +--------------+     +--------------+

   config.yaml + .env  -->  main.py (orchestrator)  -->  logs/
```

**Design principles**

- **Separation of concerns** - data, signals, execution, persistence and
  presentation live in separate packages.
- **Pure strategies** - strategies take a DataFrame and return signals with no
  side effects, so the same code runs in backtests and live.
- **Configuration over code** - all tunable parameters are in `config.yaml`;
  secrets are in `.env` (never committed).
- **Reproducibility** - generated data, models, results and reports are
  git-ignored and can be rebuilt from code + config.

## Project structure

```
ForexBot/
├── data/            # Historical market data (EURUSD_<YEAR>.csv, raw/, processed/)
├── data_pipeline/   # Historical data downloader (Dukascopy, OANDA, Twelve Data, Alpha Vantage)
├── strategies/      # Trading strategies (EMA, RSI, ML strategies)
├── backtests/       # Backtesting engine (python -m backtests)
├── models/          # Machine learning models and training scripts
├── logs/            # Application logs and trade logs
├── dashboard/       # Streamlit dashboard (streamlit run dashboard/app.py)
├── database/        # SQLite database files and data-access layer
├── reports/         # Performance reports and exports
├── notebooks/       # Research and experimentation notebooks
├── config/          # Additional configuration and settings loaders
├── tests/           # Unit and integration tests
├── docs/            # Project documentation
├── scripts/         # Utility and automation scripts
├── deployment/      # VPS deployment files and service configs
├── main.py          # Main application entry point
├── requirements.txt # Python dependencies
├── config.yaml      # Main configuration file
├── .env.example     # Template for secrets / environment variables
├── .gitignore
└── README.md
```

Each folder has its own `README.md` describing its purpose and conventions.

## Getting started

### Prerequisites

- Python 3.10+

### Installation

```bash
cd ForexBot
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env    # then fill in your credentials
```

### Usage

```bash
# Run with the mode defined in config.yaml
python main.py

# Override the mode
python main.py --mode backtest
python main.py --mode paper

# Use an alternative config file
python main.py --config config/config.dev.yaml

# Launch the dashboard
streamlit run dashboard/app.py
```

### Testing

```bash
pytest
```

## Historical data pipeline

`data_pipeline/` downloads 10+ years of EUR/USD candles (Dukascopy by default;
OANDA, Twelve Data and Alpha Vantage also supported), validates them and saves
one CSV per year to `data/`:

```bash
cp .env.example .env
python -m data_pipeline            # download
python -m data_pipeline --verify   # check data/EURUSD_<YEAR>.csv files
```

Full setup guide: [`data_pipeline/README.md`](data_pipeline/README.md).

## Backtesting

`backtests/` runs a strategy over the downloaded data with realistic costs and
writes `reports/performance_report.txt`, `trades.csv`, `equity_curve.csv` and
charts in `reports/charts/`:

```bash
python -m backtests                         # strategy and costs from config.yaml
python -m backtests --strategy rsi_reversal
```

Full setup guide: [`backtests/README.md`](backtests/README.md).

## Dashboard

```bash
streamlit run dashboard/app.py
```

Opens a local web dashboard (http://localhost:8501) with eight pages: Overview,
Backtest Results, Trade History, Performance Analytics, Risk Analysis, Monthly
Analytics, Strategy Settings and Data Management. Settings changed in the
dashboard re-run the backtest instantly and can be saved to `config.yaml`.
Guide: [`dashboard/README.md`](dashboard/README.md).

## Configuration

`config.yaml` contains sections for `app`, `logging`, `data`, `database`,
`strategy`, `risk`, `backtest` and `reports`. Credentials such as broker API
keys go in `.env`.

## Deployment

See `deployment/` for VPS deployment assets (systemd service, provisioning
scripts, optional Docker setup).

## Roadmap

- [x] Historical data downloader and cleaning pipeline
- [x] `Strategy` interface with EMA and RSI implementations and an ML model adapter
- [x] Backtest engine, performance metrics, reports and charts
- [ ] ML feature pipeline and walk-forward training
- [x] Streamlit dashboard
- [ ] Paper-trading broker integration
- [ ] Live trading with risk controls
