# data/

Historical and downloaded market data (OHLCV CSV/Parquet files).

- `raw/` - untouched downloads from data providers
- `processed/` - cleaned, resampled, feature-ready datasets

Yearly candle files produced by the data pipeline (`python -m data_pipeline`)
are written directly here as `EURUSD_<YEAR>.csv` with columns
`Date,Open,High,Low,Close,Volume`. See `data_pipeline/README.md`.

`weekday/` holds the same daily data with each Sunday candle folded into the
following Monday (clean Monday-Friday candles), with the same file names.

Data files are git-ignored; only READMEs and `.gitkeep` files are tracked.
Suggested naming: `<SYMBOL>_<TIMEFRAME>_<START>_<END>.csv`
(e.g. `EURUSD_H1_2020-01-01_2024-12-31.csv`).
