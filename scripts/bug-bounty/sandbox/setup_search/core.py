#!/usr/bin/env python3
"""Config space bounds, default setup, and the scalar objective for the
setup-search loop.

The objective is tuned for a small ($500) account where fixed fees dominate:
it rewards annualized Sharpe and net return, and penalizes max drawdown,
fee bleed (total fees / starting equity) and churn (trade count).
"""

from dataclasses import dataclass, field
from typing import Any, Dict

CONFIG_BOUNDS: Dict[str, tuple] = {
    "mom_lb": (5, 60),
    "w_mom": (-2.0, 4.0),
    "rev_lb": (5, 60),
    "w_rev": (-2.0, 4.0),
    "rsi_period": (5, 30),
    "w_rsi": (-2.0, 4.0),
    "breakout_lb": (10, 120),
    "w_brk": (-2.0, 4.0),
    "z_period": (5, 60),
    "w_z": (-2.0, 4.0),
    "rank_on": (0, 1),
    "w_rank": (0.0, 3.0),
    "buy_thresh": (0.0, 1.5),
    "sell_thresh": (-1.0, 3.0),
    "regime_filter": (0, 1),
    "regime_window": (20, 200),
    "risk_pct": (0.01, 0.15),
    "max_positions": (1, 12),
    "max_exposure": (0.20, 0.95),
    "min_notional": (5.0, 60.0),
    "sl": (0.01, 0.15),
    "tp": (0.02, 0.50),
    "max_hold": (1, 60),
    "trailing_pct": (0.0, 0.05),
    # ── Research-feature gates (0/off by default) ──
    "ma_reject_n": (0, 120),       # 0=off; reject if close > MA(n)*(1+pct)
    "ma_reject_pct": (0.0, 0.5),
    "vol_spike_n": (0, 120),       # 0=off; reject if volume > mult*avg_vol(n)
    "vol_spike_mult": (0.0, 10.0),
    "vol_reduce_n": (0, 120),      # 0=off; scale size by frac when vol>thr
    "vol_reduce_thr": (0.0, 0.2),
    "vol_reduce_frac": (0.0, 1.0),
    "impact_cap_pct": (0.0, 0.5),  # 0=off; cap order notional to pct of equity
    "rsi_filter_n": (0, 30),       # 0=off; reject entry if RSI > hi or < lo
    "rsi_filter_hi": (0.0, 100.0),
    "rsi_filter_lo": (0.0, 100.0),
    "mom_filter_n": (0, 120),      # 0=off; reject entry if N-d ret > max or < min
    "mom_filter_max": (0.0, 10.0),
    "mom_filter_min": (0.0, 10.0),
    "rsi_exit_hi": (0.0, 100.0),   # 0=off; exit when RSI > hi
    "rsi_exit_lo": (0.0, 100.0),   # 0=off; exit when RSI < lo
}

DEFAULT_CONFIG: Dict[str, float] = {
    "mom_lb": 20,
    "w_mom": 1.0,
    "rev_lb": 10,
    "w_rev": -0.2,
    "rsi_period": 14,
    "w_rsi": 0.3,
    "breakout_lb": 55,
    "w_brk": 0.2,
    "z_period": 20,
    "w_z": 0.1,
    "rank_on": 0,
    "w_rank": 0.0,
    "buy_thresh": 0.2,
    "sell_thresh": -0.2,
    "regime_filter": 0,
    "regime_window": 50,
    "risk_pct": 0.05,
    "max_positions": 6,
    "max_exposure": 0.60,
    "min_notional": 10.0,
    "sl": 0.05,
    "tp": 0.10,
    "max_hold": 20,
    "trailing_pct": 0.0,
    "ma_reject_n": 0,
    "ma_reject_pct": 0.0,
    "vol_spike_n": 0,
    "vol_spike_mult": 0.0,
    "vol_reduce_n": 0,
    "vol_reduce_thr": 0.0,
    "vol_reduce_frac": 0.0,
    "impact_cap_pct": 0.0,
    "rsi_filter_n": 0,
    "rsi_filter_hi": 0.0,
    "rsi_filter_lo": 0.0,
    "mom_filter_n": 0,
    "mom_filter_max": 0.0,
    "mom_filter_min": 0.0,
    "rsi_exit_hi": 0.0,
    "rsi_exit_lo": 0.0,
}

INT_KEYS = {
    "mom_lb", "rev_lb", "rsi_period", "breakout_lb", "z_period",
    "rank_on", "regime_filter", "regime_window", "max_positions", "max_hold",
    "ma_reject_n", "vol_spike_n", "vol_reduce_n", "rsi_filter_n", "mom_filter_n",
}

FEE_PER_SIDE = 0.35
START_EQUITY = 500.0


def clamp_config(cfg: Dict[str, Any]) -> Dict[str, float]:
    out = dict(DEFAULT_CONFIG)
    for k, lo, hi in ((k, *v) for k, v in CONFIG_BOUNDS.items()):
        if k in cfg:
            try:
                v = float(cfg[k])
            except (TypeError, ValueError):
                continue
            out[k] = min(hi, max(lo, v))
            if k in INT_KEYS:
                out[k] = int(round(out[k]))
    if "sl" in out and "tp" in out and out["tp"] <= out["sl"]:
        out["tp"] = round(min(out["sl"] + 0.05, CONFIG_BOUNDS["tp"][1]), 3)
    if "_start_equity" in cfg:
        out["_start_equity"] = float(cfg["_start_equity"])
    if "_fee_pct" in cfg:
        out["_fee_pct"] = float(cfg["_fee_pct"])
    return out


def objective(metrics: Dict[str, float]) -> float:
    sharpe = float(metrics.get("ann_sharpe", 0.0))
    net_return = float(metrics.get("net_return", 0.0))
    max_dd = float(metrics.get("max_drawdown", 0.0))
    fee_ratio = float(metrics.get("fee_ratio", 0.0))
    n_trades = int(metrics.get("n_trades", 0))

    score = (
        0.6 * sharpe
        + 1.0 * min(max(net_return, 0.0), 0.6)
        - 2.0 * max_dd
        - 3.0 * fee_ratio
        - 0.3 * min(n_trades, 300) / 300.0
    )
    return round(score, 5)


def summary_bundle(metrics: Dict[str, float]) -> str:
    return (
        f"ret={metrics.get('net_return', 0):+.2%} "
        f"sharpe={metrics.get('ann_sharpe', 0):.2f} "
        f"maxdd={metrics.get('max_drawdown', 0):.1%} "
        f"wins={metrics.get('win_rate', 0):.0%} "
        f"trades={metrics.get('n_trades', 0)} "
        f"fees=${metrics.get('total_fees', 0):.2f} "
        f"fee%={metrics.get('fee_ratio', 0):.1%} "
        f"pf={metrics.get('profit_factor', 0):.2f}"
    )
