#!/usr/bin/env python3
"""FTMO-US instrument universe — the prop leg's data + shadow validation.

The FTMO US challenge (via OANDA, ADR-0005) trades FX, metals and indices —
NOT the US equities the validated rule was fit on. Momentum (TSM) is
transferable across asset classes (MOP 2012, Hurst 2017) but must be
RE-VALIDATED on the actual instruments before the end-of-August purchase.

Instruments (OANDA-style, mapped to yfinance daily):
  FX:   EUR_USD USD_JPY GBP_USD USD_CHF AUD_USD USD_CAD NZD_USD
  Metals: XAU_USD (gold) XAG_USD (silver)
  Indices: US30 SPX500 NAS100 GER30
Regime anchor: DXY (the USD index) as the FX/indices market clock — the
research's per-class regime anchor (SPY is equities-specific and decoupled
from FX).

Shadow: the same arena feature pipeline + RegimeRouter over this universe,
so the rule floor and the 11-dim value heads can be scored head-to-head on
FTMO's instruments before any money is spent.
"""
from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

CACHE = PROJECT / "data" / "setup_search" / "ftmo_ohlcv_5y.pkl"

# OANDA-style name -> yfinance ticker
INSTRUMENTS = {
    "EUR_USD": "EURUSD=X", "USD_JPY": "USDJPY=X", "GBP_USD": "GBPUSD=X",
    "USD_CHF": "USDCHF=X", "AUD_USD": "AUDUSD=X", "USD_CAD": "USDCAD=X",
    "NZD_USD": "NZDUSD=X", "XAU_USD": "GC=F", "XAG_USD": "SI=F",
    "US30": "^DJI", "SPX500": "^GSPC", "NAS100": "^IXIC", "GER30": "^GDAXI",
    "DXY": "DX-Y.NYB",  # regime anchor
}


def load_ftmo(fresh=False) -> dict:
    """{OANDA name: OHLCV DataFrame}; DXY included as the regime anchor."""
    if not fresh and CACHE.exists():
        try:
            return pickle.load(open(CACHE, "rb"))
        except Exception:
            pass
    import yfinance as yf

    tickers = list(dict.fromkeys(INSTRUMENTS.values()))
    raw = yf.download(tickers, period="5y", interval="1d",
                      auto_adjust=True, progress=False, group_by="ticker")
    out = {}
    for oanda, tk in INSTRUMENTS.items():
        try:
            df = raw[tk].dropna(how="all")
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.columns = ["open", "high", "low", "close", "volume"]
            if len(df) > 250:
                out[oanda] = df
        except Exception:
            continue
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(out, open(CACHE, "wb"))
    print(f"[ftmo] cached {len(out)} instruments")
    return out


def DXY_AS_SPY(data: dict) -> dict:
    """Rename the DXY regime anchor to SPY so the war's REGIME_SYM works.
    Returns a copy; tradeables unchanged."""
    out = {k: v for k, v in data.items() if k != "DXY"}
    if "DXY" in data:
        out["SPY"] = data["DXY"]
    return out


def collect(period="5y", n_symbols=None, seed=7) -> tuple:
    """Arena candidate rows over the FTMO universe (SPY = DXY regime anchor),
    in the full arena contract. The war's fidelity replay uses the same data."""
    from arena.candidates import collect_from_data
    from setup_search.core import clamp_config

    cfg = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ftmo(fresh=False)
    tradeable = {k: v for k, v in data.items() if k != "DXY"}
    if "DXY" not in data:
        print("[ftmo] WARNING: DXY missing; regime proxy = cross-sectional mean")
        mkt = pd.concat([d["close"] for d in tradeable.values()], axis=1).mean(axis=1)
        tradeable["SPY"] = pd.DataFrame({"open": mkt, "high": mkt, "low": mkt,
                                         "close": mkt, "volume": 0.0})
    else:
        tradeable["SPY"] = data["DXY"]
    return collect_from_data(tradeable, cfg)


def shadow_ftmo(period="5y", n_symbols=None, seed=7) -> dict:
    """Run the rule floor + 11-dim value heads over the FTMO universe through
    the RegimeRouter, with DXY as the regime anchor. Returns the router state
    and per-expert per-regime impacts."""
    from arena.candidates import collect_from_data
    from mot.mixture import RegimeRouter
    from arena import agent as agent_mod
    from mot.experts import ValueHeadExpert

    rows, base = collect(period)
    print(f"[ftmo] {len(rows)} candidates over the FTMO universe")

    router = RegimeRouter(rule_floor="rule", min_evidence=5)
    # the 11-dim value heads (same feature space) can score FX/indices
    for name in ("international", "us", "momentum"):
        ck = PROJECT / "data" / "arena" / f"arena_{name}_value_head.pt"
        if not ck.exists():
            continue
        exp = ValueHeadExpert.from_checkpoint(ck, name=name)
        if exp.art is None:
            continue
        xs = [r["x"] for r in rows]
        vs = agent_mod.predict_batch(exp.art, xs)
        theta = exp.art["theta"]
        for i, r in enumerate(rows):
            regime = "up" if r["regime_up"] else "down"
            if r["regime_up"]:
                router.record(regime, "rule", float(r["fwd"]))
            if vs[i] >= theta:
                router.record(regime, exp.name, float(r["fwd"]))
    return {
        "n_candidates": len(rows),
        "picks": {r: router.pick(r) for r in ("up", "down")},
        "evidence": {r: {e: {"n": t["n"], "mean_impact": round(t["sum"] / t["n"], 5)}
                         for e, t in es.items()} for r, es in router.track.items()},
    }


if __name__ == "__main__":
    t0 = time.time()
    data = load_ftmo(fresh=False)
    print(f"[ftmo] {len(data)} instruments cached ({time.time()-t0:.0f}s)")
    rep = shadow_ftmo()
    print(f"[ftmo] candidates: {rep['n_candidates']} | picks: {rep['picks']}")
    for reg, ev in rep["evidence"].items():
        print(f"  {reg}: " + "  ".join(f"{e}:n={t['n']},m={t['mean_impact']:+.3%}"
                                       for e, t in ev.items()))
