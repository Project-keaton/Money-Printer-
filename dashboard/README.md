# ForexBot Dashboard

A dark-themed web dashboard for backtest results, trade history, risk and data
quality. It runs locally in your browser and uses the project's backtesting
engine directly: change a setting and every page updates.

```powershell
streamlit run dashboard/app.py
```

## Pages

| Page | What it shows |
|------|---------------|
| **Overview** | KPI cards: starting/current balance, total profit, total return, trades, win/loss rate, profit factor, Sharpe ratio, maximum drawdown · equity curve · latest trades · results by exit type |
| **Backtest Results** | Equity and balance curve, account growth %, return by year, cumulative profit per trade, and a candlestick chart with the strategy's indicators and every entry/exit marked |
| **Trade History** | Every trade in a sortable table with search, trade-type, outcome, exit-reason and date filters, a filtered summary and CSV download |
| **Performance Analytics** | Win/loss rate, average and largest winner/loser, profit factor, expectancy, Sharpe, risk-reward · P/L per trade · win/loss distribution · duration vs P/L · long vs short · P/L by exit reason |
| **Risk Analysis** | Maximum and current drawdown, longest drawdown, recovery factor, losing streaks · underwater curve · largest drawdowns with recovery times · worst months |
| **Monthly Analytics** | Best/worst/average month, % positive months · monthly-return heatmap · monthly win-rate heatmap · monthly returns over time · seasonality by calendar month |
| **Strategy Settings** | Edit starting balance, risk per trade, EMA, RSI, ATR stop/target and spread/commission/slippage; **Run backtest** (try it without saving) or **Run and save to config.yaml** |
| **Data Management** | Rows, available years, missing values, duplicates, invalid OHLC rows and missing trading days per file · candles per year · price chart · latest download summary · buttons to download data or rebuild the Monday-Friday dataset |

All charts are interactive (Plotly): hover for exact values, drag to zoom,
double-click to reset, and use the 6M / 1Y / 3Y / 5Y / All buttons on time charts.

## Structure

```
dashboard/
├── app.py              # entry point: page config, theme CSS, navigation, sidebar
├── views/              # one file per page (see note below)
├── charts/             # Plotly figure builders + the dark theme (theme.py)
├── components/         # KPI cards, page headers, sidebar
├── utils/              # cached backtest runs (state.py), analytics, formatting,
│                       # config.yaml editing (config_io.py), data-quality scan
└── assets/             # style.css, logo.svg
```

The page scripts live in `views/` rather than `pages/`: Streamlit treats a folder
named `pages/` next to `app.py` as its older file-based page system, which breaks
refreshing or bookmarking a page (the page then loads without the app around it).

**How results stay in sync.** `utils/state.py` runs the backtest with the
existing `backtests` engine and caches the result keyed on the contents of
`config.yaml`, any unsaved settings from the Strategy page, and the data files'
timestamps. Switching pages is instant; a run repeats only when something
changed. Use **Re-run backtest** in the sidebar after editing `config.yaml` by hand.

---

## Setup guide

### 1. Install

From the `ForexBot` folder:

```powershell
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r dashboard/requirements.txt
```

`dashboard/requirements.txt` includes the backtesting and data-pipeline
dependencies, so this one command is enough on a fresh environment.

### 2. Make sure data exists

The dashboard reads `data/weekday/EURUSD_<YEAR>.csv` (or `data/` for the raw
dataset). If there is none, open **Data Management** and click
**Download / update data**, or run `python -m data_pipeline`.

### 3. Run

```powershell
streamlit run dashboard/app.py
```

Run it **from the project root** so Streamlit picks up the dark theme in
`.streamlit/config.toml`. Your browser opens at http://localhost:8501.
Stop the server with `Ctrl+C` in the terminal.

The very first time, Streamlit asks for an optional email address in the
terminal - just press **Enter** to skip it. It never asks again.

Options:

```powershell
streamlit run dashboard/app.py --server.port 8600        # another port
streamlit run dashboard/app.py --server.headless true    # don't open a browser
```

### 4. Typical workflow

1. **Overview** - check the headline numbers.
2. **Strategy Settings** - change, for example, the EMA periods or the spread, then
   **Run backtest**. A yellow *Unsaved settings* badge appears in the sidebar;
   every page now shows the new run. **Reset to config.yaml** returns to the saved settings.
3. When you like a configuration, click **Run and save to config.yaml** - it is
   validated first, then written with all comments kept. `python -m backtests`
   then uses the same settings.
4. **Export reports** in the sidebar writes the text report, CSVs and PNG charts
   to `reports/`, exactly like `python -m backtests`.

### 5. Tests

```powershell
pytest tests/unit/test_dashboard.py
```

Includes a headless run of every page (Streamlit `AppTest`) when the EUR/USD data is present.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Light theme instead of dark | Start Streamlit from the `ForexBot` folder (where `.streamlit/` is) |
| `No market data` message | Data Management → Download / update data |
| `Configuration error` | Fix the named setting on Strategy Settings or in `config.yaml` |
| Results don't reflect a manual `config.yaml` edit | Sidebar → **Re-run backtest** (or refresh the page) |
| Port 8501 already in use | `streamlit run dashboard/app.py --server.port 8600` |
