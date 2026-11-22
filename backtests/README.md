# backtests/

Backtesting engine and stored test results.

- Engine code lives in this package (vectorised and/or event-driven).
- `results/` - git-ignored output (equity curves, trade lists, metrics JSON).

Backtests must account for spread, commission and slippage as configured in `config.yaml`.
