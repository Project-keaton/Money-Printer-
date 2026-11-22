# data/

Historical and downloaded market data (OHLCV CSV/Parquet files).

- `raw/` - untouched downloads from data providers
- `processed/` - cleaned, resampled, feature-ready datasets

Data files are git-ignored; only READMEs and `.gitkeep` files are tracked.
Suggested naming: `<SYMBOL>_<TIMEFRAME>_<START>_<END>.csv`
(e.g. `EURUSD_H1_2020-01-01_2024-12-31.csv`).
