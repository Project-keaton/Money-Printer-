# models/

Machine learning models and training scripts.

- Training and feature-engineering code lives in this package.
- `artifacts/` - serialised trained models (`.pkl`, `.joblib`, `.json`), git-ignored.

Always use time-series-aware validation (walk-forward / `TimeSeriesSplit`)
to avoid look-ahead bias.
