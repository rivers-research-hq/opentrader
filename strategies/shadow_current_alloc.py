#!/usr/bin/env python3
"""Shadow prototype (option D): the verified experts' CURRENT target allocations.

This is a PAPER/SHADOW demonstration — no live orders. It computes, as of the
latest available daily bar, what the two strongest verified experts would hold
if the harness routed live order flow to them (the rule floor demoted to a
risk gate only):

  - multiasset on its 13-US-ETF basket (finnhub-feasible today)
  - laggard   on its 12-instrument intl universe (indices/FX/commodities)

The allocation math is a faithful extraction of the same logic the backtests
run at their rebalance step (prior-close signal, current-close fill, no
lookahead). It does NOT re-run the backtests and does NOT claim an edge — it
only answers "what would the expert hold today".

Usage:
  PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 \
      -m strategies.shadow_current_alloc [--asof auto] [--no-fetch]
"""

import argparse
import json
import math
import os
import pickle
import sys

import numpy as np
import pandas as pd

US_ETF = ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV",
          "USO", "DBC", "DBA", "UUP", "FXY", "FXE"]
INTL_TRADABLES = ["^N225", "^FTSE", "^GDAXI", "^HSI", "EEM", "EFA",
                  "EURUSD=X", "USDJPY=X", "GC=F", "CL=F"]

# Verified configs from /tmp/opentrader/swarm/results/*.json (2026-08-13).
# multiasset R1 (13 US ETF, Calmar 0.39): mom_gate=False, topk=10.
# multiasset OOS (10 intl, Calmar 1.289): mom_gate=False, topk=8.
#   NB: verify.py:52 and lanes.py:121 run mom_gate=False; the previous
#   "mom_gate=True (default)" here was wrong and silently reproduced the
#   wrong config (Calmar ~0.66, not 1.289).
MULTIASSET_R1_ETF = dict(rebal=63, vol_lb=120, mom_lb=180, mode="blend",
                         mom_gate=False, topk=10, eq_frac=0.4)
MULTIASSET_OOS_INTL = dict(rebal=63, vol_lb=120, mom_lb=180, mode="blend",
                           mom_gate=False, topk=8, eq_frac=0.4)
LAGGARD_CFG = dict(breadth_thr=0.7, mom_lb=60, k_mom=5, mom_expo=0.7,
                   con_lb=10, k_con=1, con_expo=0.4, breadth_win=100)


def _fetch(symbols, period="6y"):
    import yfinance as yf
    df = yf.download(symbols, period=period, interval="1d",
                     progress=False, auto_adjust=True, threads=True)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        closes = df["Close"].ffill()
    else:
        closes = df.ffill()
    return closes[symbols]


def _intl_from_cache():
    # intl_data.pkl was LOST to /tmp cleanup (2026-08-23, see data/MANIFEST.json)
    return None


def _etf_from_cache():
    # swarm_data.pkl was LOST to /tmp cleanup (2026-08-23, see data/MANIFEST.json)
    return None


def multiasset_target(closes: pd.DataFrame, cfg: dict) -> dict:
    """Current target weights: momentum-positive top-k, blend inv-vol + eq-weight."""
    names = list(closes.columns)
    P = closes[names].values.astype(float)
    n, k = P.shape
    mom = P[n - 2] / P[n - 2 - cfg["mom_lb"]] - 1.0
    logp = np.log(P)
    seg = logp[max(0, n - 2 - cfg["vol_lb"]):n - 1]
    vol = np.nanstd(seg[1:] - seg[:-1], axis=0) if len(seg) > 3 else np.full(k, np.nan)
    valid = np.isfinite(mom) & np.isfinite(vol) & (vol > 0)
    sel = valid & ((mom > 0) if cfg.get("mom_gate", True) else True)
    topk = cfg["topk"]
    if topk is not None and sel.sum() > topk:
        idx = np.where(sel)[0]
        keep = idx[np.argsort(-mom[idx])[:topk]]
        sel = np.zeros(k, dtype=bool)
        sel[keep] = True
    inv = np.zeros(k)
    inv[sel] = 1.0 / vol[sel]
    eq_frac = cfg["eq_frac"]
    tw = np.zeros(k)
    if inv.sum() > 0:
        rpw = inv / inv.sum()
        eqw = np.zeros(k)
        eqw[sel] = 1.0 / sel.sum()
        tw = (1.0 - eq_frac) * rpw + eq_frac * eqw
    out = {names[i]: float(tw[i]) for i in range(k) if tw[i] > 1e-6}
    return {"weights": out, "mom": {names[i]: float(mom[i]) for i in range(k)},
            "vol": {names[i]: (float(vol[i]) if math.isfinite(vol[i]) else None)
                    for i in range(k)}, "n_pos": int(sel.sum())}


def laggard_target(closes: pd.DataFrame) -> dict:
    """Current laggard book: momentum top-k_mom + worst-k_con catch-up, breadth-gated."""
    cfg = LAGGARD_CFG
    names = list(closes.columns)
    breadth = (closes[names] > closes[names].rolling(cfg["breadth_win"]).mean()).mean(axis=1)
    bull = bool(breadth.iloc[-2] > cfg["breadth_thr"])
    mom = {s: float(closes[s].iloc[-2] / closes[s].iloc[-2 - cfg["mom_lb"]] - 1.0)
           for s in names}
    sel = sorted(mom, key=mom.get, reverse=True)[:cfg["k_mom"]]
    con_mom = {s: float(closes[s].iloc[-2] / closes[s].iloc[-2 - cfg["con_lb"]] - 1.0)
               for s in names}
    lag = sorted(con_mom, key=con_mom.get)[:cfg["k_con"]]
    lag = [s for s in lag if s not in sel]
    out = {
        "breadth": float(breadth.iloc[-1]),
        "breadth_thr": cfg["breadth_thr"],
        "bull": bull,
        "momentum_book": [{s: round(mom[s], 4)} for s in sel],
        "laggard_book": [{s: round(con_mom[s], 4)} for s in lag],
        "exposure": {"momentum": cfg["mom_expo"], "laggard": cfg["con_expo"]},
    }
    if bull:
        out["target"] = (
            {s: round(cfg["mom_expo"] / len(sel), 4) for s in sel}
            | {s: round(cfg["con_expo"] / len(lag), 4) for s in lag}
        )
    else:
        out["target"] = {}
    return out


def _fmt_w(weights):
    if not weights:
        return "  (flat)"
    return "  " + "\n  ".join(f"{s:12s} {w*100:6.2f}%" for s, w in
                              sorted(weights.items(), key=lambda x: -x[1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    args = ap.parse_args()

    etf = intl = None
    if not args.no_fetch:
        try:
            etf = _fetch(US_ETF)
        except Exception as e:
            print(f"[fetch] US ETF fetch failed: {e}")
        try:
            intl = _fetch(INTL_TRADABLES)
        except Exception as e:
            print(f"[fetch] intl fetch failed: {e}")
    if etf is None:
        etf = _etf_from_cache()
        print("[fetch] US ETF from cache (swarm_data.pkl basket)")
    if intl is None:
        intl = _intl_from_cache()
        print("[fetch] intl from cache (intl_data.pkl)")

    report = {"asof": None, "multiasset_r1_etf": None,
              "multiasset_oos_intl": None, "laggard_intl": None}

    print("=" * 64)
    print("SHADOW — verified experts' CURRENT target allocation (paper only)")
    print("=" * 64)

    if etf is not None and etf.shape[1] >= 6:
        m = multiasset_target(etf, MULTIASSET_R1_ETF)
        report["asof"] = str(etf.index[-1].date())
        report["multiasset_r1_etf"] = m
        print(f"\n[multiasset R1] 13-US-ETF basket  asof {etf.index[-1].date()}"
              f"  (verified Calmar 0.39)")
        print(f"  n_pos={m['n_pos']}  (mom_gate=False, topk=10, "
              f"mom {MULTIASSET_R1_ETF['mom_lb']}d, vol {MULTIASSET_R1_ETF['vol_lb']}d)")
        print("  TARGET weights:")
        print(_fmt_w(m["weights"]))
    else:
        print("\n[multiasset R1] ETF data unavailable")

    if intl is not None and intl.shape[1] >= 6:
        mo = multiasset_target(intl, MULTIASSET_OOS_INTL)
        report["asof"] = report["asof"] or str(intl.index[-1].date())
        report["multiasset_oos_intl"] = mo
        print(f"\n[multiasset OOS] 10-intl universe  asof {intl.index[-1].date()}"
              f"  (verified Calmar 1.289)")
        print(f"  n_pos={mo['n_pos']}  (mom_gate=False, topk=8)")
        print("  TARGET weights:")
        print(_fmt_w(mo["weights"]))

        l = laggard_target(intl)
        report["laggard_intl"] = l
        print(f"\n[laggard] 10-intl universe  asof {intl.index[-1].date()}"
              f"  (verified Calmar 1.666)")
        print(f"  breadth={l['breadth']:.3f} thr={l['breadth_thr']} bull={l['bull']}")
        if l["bull"]:
            print("  TARGET weights (mom book + laggard book):")
            print(_fmt_w(l["target"]))
            print(f"  mom book top-{LAGGARD_CFG['k_mom']}:",
                  ", ".join(list(d)[0] for d in l["momentum_book"]))
            print(f"  laggard book worst-{LAGGARD_CFG['k_con']}:",
                  ", ".join(list(d)[0] for d in l["laggard_book"]))
        else:
            print("  flat — breadth below threshold (no entries, validated gate)")
    else:
        print("\n[multiasset OOS / laggard] intl data unavailable")

    out = os.path.join(os.path.dirname(__file__), "..", "data",
                       "shadow_current_alloc.json")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
