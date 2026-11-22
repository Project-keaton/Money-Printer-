# strategies/

Trading strategies. Each one subclasses `strategies.base.Strategy` and only
turns market data into signals; the backtest engine (and later the live
trader) handles orders, sizing and costs.

| Module | Contents |
|--------|----------|
| `base.py` | `Strategy` interface, signal contract, `normalise_signals` validation |
| `indicators.py` | `sma`, `ema`, `rsi`, `atr`, `true_range`, `crossed_above`, `crossed_below` |
| `ema_crossover.py` | `EmaCrossoverStrategy` - fast/slow EMA cross (`ema_crossover`) |
| `rsi_reversal.py` | `RsiReversalStrategy` - RSI oversold/overbought reversal (`rsi_reversal`) |
| `ml_model.py` | `ModelSignalStrategy` - wraps any trained classifier with `predict_proba` |
| `__init__.py` | `STRATEGIES` registry and `create_strategy(name, params)` |

`generate_signals(data)` returns `1` (long), `-1` (short) or `0` per bar, or a
frame with a `signal` column plus optional `exit_long`, `exit_short`,
`stop_distance` and `target_distance`. A signal at bar *t* may only use data up
to bar *t*'s close; the engine executes it at the next bar's open.

Keep strategies pure (no I/O, no broker calls) so the same code is unit-tested,
backtested and run live. See `backtests/README.md` -> *Writing a strategy*.
