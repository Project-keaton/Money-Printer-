# strategies/

Trading strategy implementations (EMA crossover, RSI, ML-driven, etc.).

Each strategy should subclass a common `BaseStrategy` interface and expose:

- `generate_signals(df: pd.DataFrame) -> pd.Series` returning `1` (long), `-1` (short) or `0` (flat)
- parameters loaded from the `strategy` section of `config.yaml`

Keep strategies pure (no I/O, no broker calls) so the same code is unit-tested,
backtested and run live.
