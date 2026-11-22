# Historical Data Pipeline

Downloads 10+ years of historical **EUR/USD** candles, validates and
de-duplicates them, and saves **one CSV file per year** in `data/`:

```
data/
├── EURUSD_2016.csv
├── EURUSD_2017.csv
├── ...
└── EURUSD_2026.csv
```

Each file has these columns (timestamps in UTC):

| Date | Open | High | Low | Close | Volume |
|------|------|------|-----|-------|--------|
| 2016-01-04 | 1.08743 | 1.09464 | 1.07104 | 1.08277 | 245813.94 |

Daily files use `YYYY-MM-DD`; hourly files use `YYYY-MM-DD HH:MM:SS`.

### Two daily datasets

| Folder | Contents | Rows per year |
|--------|----------|---------------|
| `data/` | Raw UTC-midnight daily candles, **including** a short Sunday-evening session candle | ~312 |
| `data/weekday/` | Same data with each Sunday candle **folded into the following Monday**: clean Monday-Friday candles | ~260 |

How a Sunday is folded into Monday:

| Field | Monday-Friday value |
|-------|---------------------|
| Date | Monday |
| Open | Sunday open (first price of the trading week) |
| High | max(Sunday high, Monday high) |
| Low | min(Sunday low, Monday low) |
| Close | Monday close |
| Volume | Sunday volume + Monday volume |

A Sunday with no Monday candle after it (for example when the data ends on a
Sunday) is dropped from the weekday dataset and listed in the report. The
weekday dataset is built automatically after every daily download
(`BUILD_WEEKDAY_DATASET=true`). It can be rebuilt from the existing CSVs
without downloading again:

```powershell
python -m data_pipeline --build-weekday
```

## Providers

| Provider | `DATA_PROVIDER` | API key | Timeframes | Volume |
|----------|-----------------|---------|------------|--------|
| **Dukascopy** (primary) | `dukascopy` | none | 1d, 1h | tick volume |
| OANDA | `oanda` | `OANDA_API_KEY` | 1d, 1h | tick volume |
| Twelve Data | `twelvedata` | `TWELVE_DATA_API_KEY` | 1d, 1h | not published (0) |
| Alpha Vantage | `alphavantage` | `ALPHA_VANTAGE_API_KEY` | 1d | not published (0) |

Forex has no central exchange, so "volume" is the provider's own tick or
traded volume. Providers that do not publish forex volume write `0`.

## Architecture

```
main.py ──► config.py ─────────── Settings from .env (+ CLI overrides)
   │
   ├──► providers/  ───────────── one class per data source, same interface
   │      base.py                 HTTP retries/backoff, throttling, error types
   │      dukascopy.py            bi5 candle files (day <- hour <- minute fallback)
   │      oanda.py / twelve_data.py / alpha_vantage.py
   │
   ├──► downloader.py ─────────── splits the range into batches, progress bar,
   │                              keeps going when one batch fails
   ├──► validator.py ──────────── cleaning, OHLC rules, duplicates, gap detection
   ├──► transforms.py ─────────── fold Sunday candles into Monday (Monday-Friday dataset)
   ├──► storage.py ────────────── atomic per-year CSV writes + verification
   ├──► report.py ─────────────── summary printed and saved to reports/
   └──► logger.py ─────────────── logs/data_download.log (+ errors-only log)
```

| Module | Responsibility |
|--------|----------------|
| `main.py` | CLI entry point, orchestrates the run, exit codes |
| `config.py` | Loads and validates settings from `.env`; secrets never logged |
| `providers/` | Provider-specific requests and parsing to a common OHLCV format |
| `downloader.py` | Runs a provider over the date range with progress display |
| `validator.py` | Removes bad, missing and duplicate rows; reports missing trading periods |
| `transforms.py` | Builds the Monday-Friday dataset by folding Sundays into Monday |
| `storage.py` | Splits by year, writes CSVs atomically, verifies files |
| `report.py` | Builds the summary report |
| `logger.py` | Rotating log files in `logs/` |
| `progress.py` | Dependency-free progress bar |

### How failures are handled

| Situation | Behaviour |
|-----------|-----------|
| Network error, timeout, HTTP 5xx | Retried up to `HTTP_MAX_RETRIES` times with exponential backoff |
| HTTP 429 (rate limit) | Retried with backoff (honours `Retry-After`); if it persists, the run stops early and **saves what was already downloaded** |
| One batch fails for another reason | Logged, listed in the report, and the remaining batches still download |
| Invalid API key (HTTP 401/403) | Run stops immediately with a clear message, no retries |
| Missing config or API key | Error before any request is made (exit code 2) |
| Missing/invalid rows | Dropped and counted in the report |
| Gaps in trading days/hours | Reported as *Missing Data Warnings* (weekends, 1 Jan and 25 Dec are expected closures) |
| Interrupted with Ctrl+C | Files already written are complete (writes are atomic) |

---

# Setup Guide

## 1. Install dependencies

Requires **Python 3.12 or newer** (`python --version`).

```powershell
cd C:\Users\<you>\ForexBot
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r data_pipeline/requirements.txt
```

`logging` and `pathlib` are part of the standard library; nothing extra is needed for them.

## 2. Configure the provider and API keys

```powershell
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

Open `.env` and set the provider:

```ini
DATA_PROVIDER=dukascopy
DATA_SYMBOL=EURUSD
DATA_TIMEFRAME=1d
DATA_START_DATE=2016-01-01
DATA_END_DATE=
```

**Dukascopy (primary): no key needed.** Optional tuning:

```ini
DUKASCOPY_BASE_URL=https://datafeed.dukascopy.com/datafeed
DUKASCOPY_PRICE_SIDE=BID          # or ASK
DUKASCOPY_REQUEST_INTERVAL=1.0    # raise to 2-5 if you see HTTP 429
```

**Other providers:** set `DATA_PROVIDER` and the matching key:

| Provider | Where to get the key | `.env` entries |
|----------|----------------------|----------------|
| OANDA | Practice or live account → *Manage API Access* → generate token | `OANDA_API_KEY=...`, `OANDA_ENVIRONMENT=practice` |
| Twelve Data | twelvedata.com → Dashboard → API Keys | `TWELVE_DATA_API_KEY=...` |
| Alpha Vantage | alphavantage.co → *Get free API key* | `ALPHA_VANTAGE_API_KEY=...` |

Keys stay in `.env`, which is git-ignored. They are never written to logs or reports.

## 3. Run the application

From the **project root** (`ForexBot/`), with the virtual environment active:

```powershell
python -m data_pipeline
```

Useful options (these override `.env` for one run):

```powershell
python -m data_pipeline --provider oanda           # switch provider
python -m data_pipeline --timeframe 1h             # hourly candles
python -m data_pipeline --start 2016-01-01 --end 2026-11-20
python -m data_pipeline --log-level DEBUG          # log every file/URL fetched
python -m data_pipeline --no-progress              # for scheduled jobs / services
python -m data_pipeline --build-weekday            # rebuild data/weekday/ from existing CSVs
python -m data_pipeline --help
```

While it runs you will see a progress bar (example output):

```
Dukascopy EUR/USD [###############---------------] 6/11  55% | elapsed 00:09 | ETA 00:07 | 2021-01-01 -> 2021-12-31 | 1,553 records
```

At the end a summary is printed and saved to `reports/EURUSD_download_summary_<timestamp>.txt` (example; your numbers will differ):

```
========================================================================
 EURUSD HISTORICAL DATA DOWNLOAD SUMMARY
========================================================================
 Status                    : COMPLETE WITH WARNINGS
 Provider                  : Dukascopy
 Timeframe                 : 1d
 Requested range           : 2016-01-01 -> 2026-11-22
 Start Date                : 2016-01-04
 End Date                  : 2026-11-20
 Total Records Downloaded  : 2,846
 Records Saved             : 2,846
 Duplicates Removed        : 0
 Invalid Rows Removed      : 0
 Total Files Created       : 11
 Failed Requests           : 0
 Missing Data Warnings     : 2
 ...
```

Exit codes: `0` success · `1` finished but some requests failed · `2` configuration error ·
`3` download failed (authentication, provider unavailable, no data) · `130` interrupted.

Re-running is safe: each yearly file is rewritten with the latest data.

## 4. Verify the yearly CSV files

**Built-in check:**

```powershell
python -m data_pipeline --verify
```

Example output:

```
Verifying 11 yearly file(s) in C:\...\ForexBot\data

  File               Status    Rows  First               Last                Problems
  EURUSD_2016.csv    OK         260  2016-01-04          2016-12-30
  ...
  EURUSD_2026.csv    OK         233  2026-01-02          2026-11-20

11/11 files OK, 2,846 records in total.
```

For every expected year it checks that the file exists and is readable, has
the exact columns `Date,Open,High,Low,Close,Volume`, is not empty, has
parseable dates from that year only, has no duplicates, is in ascending order,
and has no missing prices. For daily data it checks `data/weekday/` too and also confirms it has no
Saturday/Sunday rows. It exits with `1` if any file fails.

**Manual checks:**

```powershell
dir data\EURUSD_*.csv                                # macOS/Linux: ls data/EURUSD_*.csv
Get-Content data\EURUSD_2016.csv -TotalCount 5       # macOS/Linux: head -5 data/EURUSD_2016.csv
```

```python
import pandas as pd
df = pd.read_csv("data/EURUSD_2020.csv", parse_dates=["Date"])
print(len(df), df["Date"].min(), df["Date"].max())
```

Rough row counts for a full year: ~312 raw daily rows (Monday-Friday plus a short
Sunday-evening session, because days are cut at UTC midnight), ~260 rows in
`data/weekday/`, or ~6,200 hourly rows.

**Logs:** `logs/data_download.log` lists every batch downloaded, every retry and
warning; `logs/data_download_errors.log` contains errors only.

## 5. Run the tests

```powershell
pip install -r data_pipeline/requirements.txt   # includes pytest
pytest
```

The tests use simulated provider responses, so they need no network access or API keys.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Configuration error: OANDA_API_KEY is required ...` | Add the key to `.env`, or switch `DATA_PROVIDER` |
| `HTTP 429 Too Many Requests` (Dukascopy) | Raise `DUKASCOPY_REQUEST_INTERVAL` (e.g. `3`), wait a while, then re-run |
| `Authentication failed` | Key is wrong/expired; for OANDA also check `OANDA_ENVIRONMENT` matches the account type |
| `Alpha Vantage did not return data: ... premium ...` | Full FX history needs a premium plan; use another provider |
| Missing data warnings | Usually real market closures or provider gaps; see the log for exact dates |
| `ModuleNotFoundError: No module named 'data_pipeline'` | Run the command from the `ForexBot/` folder |
