"""Strategy settings: edit balance, risk, EMA/RSI/ATR and cost settings, then re-run the backtest."""

from __future__ import annotations

from typing import Any

import streamlit as st

from backtests.config import ConfigError, load_config
from dashboard.components.kpi import KPI, render_kpis
from dashboard.components.layout import page_header, section
from dashboard.utils import formatting as fmt
from dashboard.utils.config_io import save_config_values
from dashboard.utils.state import CONFIG_PATH, clear_overrides, current_config, get_overrides, get_result, set_overrides
from strategies import STRATEGIES, StrategyError, create_strategy

page_header("Strategy Settings", "Change settings and re-run the backtest. Use 'Save' to write them to config.yaml.")



def strategy_params(name: str) -> dict[str, Any]:
    """Parameters of ``name`` from config.yaml plus unsaved overrides (works for inactive strategies too)."""
    return dict(load_config(CONFIG_PATH, {**get_overrides(), "strategy.active": name}).strategy_params)


try:
    cfg = current_config()
    ema_p, rsi_p = strategy_params("ema_crossover"), strategy_params("rsi_reversal")
except ConfigError as exc:
    st.error(f"config.yaml is invalid: {exc}")
    st.stop()

if get_overrides():
    st.warning("Unsaved settings are active: the results pages use them, but config.yaml is unchanged.",
               icon=":material/edit_note:")

with st.form("settings"):
    section("Account and risk")
    a1, a2, a3, a4 = st.columns(4)
    starting_balance = a1.number_input("Starting balance ($)", min_value=100.0, value=float(cfg.starting_balance),
                                       step=1000.0, format="%.2f")
    risk_pct = a2.number_input("Risk per trade (%)", min_value=0.01, max_value=100.0,
                               value=float(cfg.risk.risk_per_trade * 100), step=0.25, format="%.2f",
                               help="Share of the balance lost if the stop loss is hit")
    sizing = a3.selectbox("Position sizing", ["risk", "fixed"], index=["risk", "fixed"].index(cfg.risk.position_sizing),
                          help="risk: size from risk % and stop distance · fixed: always the fixed lot size")
    fixed_lots = a4.number_input("Fixed lots", min_value=0.01, value=float(cfg.risk.fixed_lots), step=0.01, format="%.2f")

    p1, p2, p3, p4 = st.columns(4)
    allow_multiple = p1.toggle("Allow multiple open trades", value=cfg.allow_multiple_positions)
    max_open = p2.number_input("Max open trades", min_value=1, max_value=50, value=int(cfg.max_open_trades), step=1)
    max_leverage = p3.number_input("Max leverage", min_value=1.0, value=float(cfg.risk.max_leverage), step=5.0)
    dataset = p4.selectbox("Dataset", ["weekday", "raw"], index=["weekday", "raw"].index(cfg.dataset),
                           help="weekday: Monday-Friday candles · raw: includes Sunday candles")

    section("Strategy")
    strategy_names = sorted(STRATEGIES)
    active = st.selectbox("Active strategy", strategy_names, index=strategy_names.index(cfg.strategy_name))
    e_col, r_col = st.columns(2, gap="large")
    with e_col:
        st.markdown("**EMA crossover**")
        e1, e2, e3 = st.columns(3)
        ema_fast = e1.number_input("Fast EMA", min_value=1, max_value=500, value=int(ema_p.get("fast_period", 20)))
        ema_slow = e2.number_input("Slow EMA", min_value=2, max_value=1000, value=int(ema_p.get("slow_period", 50)))
        ema_long_only = e3.toggle("Long only", value=bool(ema_p.get("long_only", False)), key="ema_long_only")
    with r_col:
        st.markdown("**RSI reversal**")
        r1, r2, r3, r4 = st.columns(4)
        rsi_period = r1.number_input("RSI period", min_value=2, max_value=200, value=int(rsi_p.get("period", 14)))
        rsi_oversold = r2.number_input("Oversold", min_value=1.0, max_value=99.0, value=float(rsi_p.get("oversold", 30)))
        rsi_overbought = r3.number_input("Overbought", min_value=1.0, max_value=99.0, value=float(rsi_p.get("overbought", 70)))
        rsi_exit = r4.number_input("Exit level", min_value=1.0, max_value=99.0, value=float(rsi_p.get("exit_level", 50)))
        rsi_long_only = st.toggle("Long only", value=bool(rsi_p.get("long_only", False)), key="rsi_long_only")

    section("Stop loss and take profit (ATR settings)")
    sl, tp = cfg.risk.stop_loss, cfg.risk.take_profit
    s1, s2, s3, s4 = st.columns(4)
    sl_mode = s1.selectbox("Stop-loss mode", ["atr", "pips", "none"], index=["atr", "pips", "none"].index(sl.mode))
    sl_atr_period = s2.number_input("ATR period", min_value=1, max_value=200, value=int(sl.atr_period))
    sl_atr_mult = s3.number_input("Stop = ATR x", min_value=0.1, value=float(sl.atr_multiplier), step=0.25)
    sl_pips = s4.number_input("Stop (pips)", min_value=1.0, value=float(sl.pips), step=5.0)
    t1, t2, t3, t4 = st.columns(4)
    tp_modes = ["risk_reward", "atr", "pips", "none"]
    tp_mode = t1.selectbox("Take-profit mode", tp_modes, index=tp_modes.index(tp.mode))
    tp_rr = t2.number_input("Target = stop x", min_value=0.1, value=float(tp.risk_reward), step=0.25,
                            help="Used when mode is risk_reward")
    tp_atr_mult = t3.number_input("Target = ATR x", min_value=0.1, value=float(tp.atr_multiplier), step=0.25)
    tp_pips = t4.number_input("Target (pips)", min_value=1.0, value=float(tp.pips), step=5.0)

    section("Spread and costs")
    ex = cfg.execution
    c1, c2, c3, c4 = st.columns(4)
    spread = c1.number_input("Spread (pips)", min_value=0.0, value=float(ex.spread_pips), step=0.1, format="%.2f")
    commission = c2.number_input("Commission per lot ($, round turn)", min_value=0.0, value=float(ex.commission_per_lot), step=0.5)
    slippage = c3.number_input("Slippage (pips)", min_value=0.0, value=float(ex.slippage_pips), step=0.1, format="%.2f")
    price_basis = c4.selectbox("Price basis", ["mid", "bid"], index=["mid", "bid"].index(ex.price_basis),
                               help="mid: half spread on every fill · bid: full spread on buys")

    b1, b2, _ = st.columns([1, 1, 3])
    run_clicked = b1.form_submit_button("Run backtest", type="primary", icon=":material/play_arrow:", width="stretch")
    save_clicked = b2.form_submit_button("Run and save to config.yaml", icon=":material/save:", width="stretch")

updates: dict[str, Any] = {
    "backtest.starting_balance": starting_balance,
    "backtest.allow_multiple_positions": allow_multiple,
    "backtest.max_open_trades": int(max_open),
    "backtest.dataset": dataset,
    "risk.risk_per_trade": round(risk_pct / 100.0, 6),
    "risk.position_sizing": sizing,
    "risk.fixed_lots": fixed_lots,
    "risk.max_leverage": max_leverage,
    "risk.stop_loss.mode": sl_mode,
    "risk.stop_loss.pips": sl_pips,
    "risk.stop_loss.atr_period": int(sl_atr_period),
    "risk.stop_loss.atr_multiplier": sl_atr_mult,
    "risk.take_profit.mode": tp_mode,
    "risk.take_profit.pips": tp_pips,
    "risk.take_profit.atr_period": int(sl_atr_period),
    "risk.take_profit.atr_multiplier": tp_atr_mult,
    "risk.take_profit.risk_reward": tp_rr,
    "execution.spread_pips": spread,
    "execution.commission_per_lot": commission,
    "execution.slippage_pips": slippage,
    "execution.price_basis": price_basis,
    "strategy.active": active,
    "strategy.ema_crossover.fast_period": int(ema_fast),
    "strategy.ema_crossover.slow_period": int(ema_slow),
    "strategy.ema_crossover.long_only": ema_long_only,
    "strategy.rsi_reversal.period": int(rsi_period),
    "strategy.rsi_reversal.oversold": rsi_oversold,
    "strategy.rsi_reversal.overbought": rsi_overbought,
    "strategy.rsi_reversal.exit_level": rsi_exit,
    "strategy.rsi_reversal.long_only": rsi_long_only,
}

if run_clicked or save_clicked:
    try:  # validate everything before applying anything
        candidate = load_config(CONFIG_PATH, updates)
        create_strategy(candidate.strategy_name, candidate.strategy_params)
    except (ConfigError, StrategyError) as exc:
        st.error(f"Settings not applied: {exc}")
    else:
        if save_clicked:
            try:
                save_config_values(CONFIG_PATH, updates)
                clear_overrides()
                st.toast("Saved to config.yaml", icon=":material/save:")
            except (KeyError, ConfigError, OSError) as exc:
                st.error(f"Could not save config.yaml: {exc}")
                set_overrides(updates)
        else:
            set_overrides(updates)

        result = get_result()
        if result is not None:
            m = result.metrics
            section("Result with these settings")
            render_kpis([
                KPI("Total Return", fmt.pct(m.total_return_pct, signed=True), tone=fmt.tone(m.total_return_pct)),
                KPI("Total Trades", fmt.integer(m.total_trades)),
                KPI("Win Rate", fmt.pct(m.win_rate_pct)),
                KPI("Profit Factor", fmt.ratio(m.profit_factor), tone=fmt.tone((m.profit_factor or 0) - 1)),
                KPI("Max Drawdown", fmt.pct(m.max_drawdown_pct), tone="negative"),
            ])
            st.page_link("views/overview.py", label="Open the overview", icon=":material/dashboard:")
