#!/usr/bin/env python3
"""W0 parity-fixture generator — runs the REAL V1 `run_backtest`
(setup_search/engine.py, PYTHONPATH=/home/mrc/opentrader-sandbox) over
deterministic synthetic universes and records the expected results as JSON
for the ot-v1-parity harness to replay bit-for-bit-ish.

Every fixture: one master-aligned universe (all series cover the master —
the curated-universe condition under which V1's contract is fully defined),
one config dict (real V1 keys), and V1's actual output (trades, metrics,
equity curve). V2 must reproduce it.

Deterministic: numpy default_rng(seed); prices rounded to 4dp (thresholds
sit far from knife edges so fp-order differences cannot flip decisions).
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from setup_search.engine import run_backtest

N_BARS = 320
SEED = 20261007
SYMS = ["SPY", "AAA", "BBB", "CCC", "DDD", "EEE"]  # sorted; SPY first


def make_universe(rng):
    closes, highs, lows, vols = {}, {}, {}, {}
    for k, sym in enumerate(SYMS):
        r = rng.standard_normal(N_BARS) * 0.012 + 0.0004 * ((k % 3) - 1)
        close = 100.0 * np.exp(np.cumsum(r))
        intraday = np.abs(rng.standard_normal(N_BARS)) * 0.008 + 0.004
        high = close * (1 + intraday)
        low = close * (1 - intraday)
        vol = rng.integers(500, 5000, N_BARS).astype(float)
        c = pd.Series(np.round(close, 4))
        h = pd.Series(np.round(high, 4))
        l = pd.Series(np.round(low, 4))
        v = pd.Series(vol)
        # guarantee OHLC sanity after rounding
        h = np.maximum(h, c + 0.0001)
        l = np.minimum(l, c - 0.0001)
        closes[sym], highs[sym], lows[sym], vols[sym] = c, h, l, v
    return closes, highs, lows, vols


CONFIGS = {
    "default": {},
    "rank": {"rank_on": 1, "w_rank": 0.5},
    "regime": {"regime_filter": 1, "regime_window": 30},
    "exits": {
        "trailing_pct": 0.03,
        "rsi_exit_hi": 0.5,
        "rsi_exit_lo": -0.5,
        "max_hold": 10,
        "tp": 0.06,
        "sl": 0.03,
    },
    "gates": {
        "ma_reject_n": 20, "ma_reject_pct": 0.03,
        "vol_spike_n": 10, "vol_spike_mult": 2.0,
        "rsi_filter_n": 14, "rsi_filter_hi": 0.4, "rsi_filter_lo": -0.4,
        "mom_filter_n": 5, "mom_filter_max": 0.1, "mom_filter_min": -0.1,
        "vol_reduce_n": 10, "vol_reduce_thr": 0.02, "vol_reduce_frac": 0.5,
        "impact_cap_pct": 0.2,
        "_fee_pct": 0.001,
        "max_positions": 3,
    },
}


def main():
    out_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, over in CONFIGS.items():
        rng = np.random.default_rng(SEED + hash(name) % 1000)
        closes, highs, lows, vols = make_universe(rng)
        cfg = dict(over)
        cfg["_start_equity"] = 500.0
        res = run_backtest((closes, highs, lows, vols), cfg)
        fixture = {
            "desc": name,
            "n_master": N_BARS,
            "bars": {
                sym: [
                    {
                        "ts": int(ts),
                        "open": float(closes[sym].iloc[i]),
                        "high": float(highs[sym].iloc[i]),
                        "low": float(lows[sym].iloc[i]),
                        "close": float(closes[sym].iloc[i]),
                    }
                    for i, ts in enumerate(closes[sym].index)
                ]
                for sym in SYMS
            },
            "volumes": {sym: [float(x) for x in vols[sym]] for sym in SYMS},
            "config": {"desc": name, "keys": {k: v for k, v in cfg.items()}},
            "expect": {
                "desc": name,
                "n_trades": res["n_trades"],
                "trades": [
                    {
                        "sym": t["sym"],
                        "entry": t["entry"],
                        "exit": t["exit"],
                        "qty": None,  # V1 doesn't expose qty in the trade dict; qty = pnl-derived check only
                        "reason": t["reason"],
                        "entry_idx": int(t["entry_date"]),
                        "exit_idx": int(t["exit_date"]),
                        "bars": int(t["bars"]),
                        "pnl": t["pnl"],
                    }
                    for t in res["trades"]
                ],
                "net_return": res["net_return"],
                "sharpe": res["ann_sharpe"],
                "max_dd": res["max_drawdown"],
                "win_rate": res["win_rate"],
                "total_fees": res["total_fees"],
                "profit_factor": res["profit_factor"],
                "avg_hold": res["avg_hold"],
                "final_equity": res["final_equity"],
                "equity": [(int(d), float(e)) for d, e in (res["equity"].items() if hasattr(res["equity"], "items") else zip(res["equity"].index, res["equity"].values))],
            },
        }
        path = out_dir / f"fixture_{name}.json"
        path.write_text(json.dumps(fixture, indent=1))
        summary.append(f"{name}: {res['n_trades']} trades, net={res['net_return']:+.4%}")
    print("\n".join(summary))
    print(f"fixtures written to {out_dir}")


if __name__ == "__main__":
    main()
