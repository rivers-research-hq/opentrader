#!/usr/bin/env python3
"""Crypto leg: search + OOS-validate a rule config for crypto (wayfinder MoT).

Same pipeline as the US leg: data -> candidates -> CPU search on a train
window -> walk-forward holdout validation. BTC is the regime leader; fees are
%-based (0.16% taker per side, kraken). Saves the best crypto config + the
OOS validation. Regime symbol must be passable into the engine.
"""

import json
import pickle
import random
import statistics
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
DATA = Path("/tmp/opencode")
OUT = PROJECT / "data" / "research_gate"
REGIME_SYM = "BTC-USD"
FEE_PCT = 0.0016
TRAIN = (0, 1000)   # 2021 -> early 2025
TEST = (1000, 1826)  # 2025 -> 2026


def load():
    d = pickle.load(open(DATA / "crypto_ohlcv.pkl", "rb"))
    closes, highs, lows, vols = {}, {}, {}, {}
    master = None
    for s, df in d.items():
        df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
        closes[s] = df["close"]
        highs[s] = df["high"]
        lows[s] = df["low"]
        vols[s] = df["volume"]
        if master is None:
            master = df.index
    return closes, highs, lows, vols


def main():
    from setup_search.core import (CONFIG_BOUNDS, DEFAULT_CONFIG, clamp_config,
                                   objective, summary_bundle)
    from setup_search.engine import run_backtest
    from setup_search.loop import jitter, random_cfg

    closes, highs, lows, vols = load()
    master = next(iter(closes.values())).index

    def slc(i0, i1):
        lo, hi = master[i0], master[i1 - 1]
        return ({s: c.loc[(c.index >= lo) & (c.index <= hi)] for s, c in closes.items()},
                {s: h.loc[(h.index >= lo) & (h.index <= hi)] for s, h in highs.items()},
                {s: l.loc[(l.index >= lo) & (l.index <= hi)] for s, l in lows.items()},
                {s: v.loc[(v.index >= lo) & (v.index <= hi)] for s, v in vols.items()})

    # engine regime uses setup_search.data.REGIME_SYM (SPY) - patch to BTC for crypto
    import setup_search.engine as eng
    import setup_search.data as dat
    dat.REGIME_SYM = REGIME_SYM

    al = slc(*TRAIN)
    rng = random.Random(11)
    base = clamp_config({**DEFAULT_CONFIG, "_fee_pct": FEE_PCT})
    m = run_backtest(al, base)
    best_cfg, best_met = base, {k: v for k, v in m.items() if k != "equity"}
    best_score = objective(best_met)
    print(f"[crypto] baseline train: {summary_bundle(best_met)}", flush=True)

    for it in range(300):
        cand = jitter(best_cfg, rng, sigma=0.22) if rng.random() < 0.6 else random_cfg(rng)
        cand["_fee_pct"] = FEE_PCT
        mm = run_backtest(al, cand)
        met = {k: v for k, v in mm.items() if k != "equity"}
        sc = objective(met)
        if sc > best_score:
            best_score, best_cfg, best_met = sc, cand, met
            print(f"[crypto] iter {it}: best {sc:.3f} {summary_bundle(met)}", flush=True)

    # OOS validation on the held-out window
    al_te = slc(*TEST)
    m_te = run_backtest(al_te, best_cfg)
    te_met = {k: v for k, v in m_te.items() if k != "equity"}
    base_te = run_backtest(al_te, base)
    base_te_met = {k: v for k, v in base_te.items() if k != "equity"}
    print(f"\n[crypto] OOS best : {summary_bundle(te_met)}", flush=True)
    print(f"[crypto] OOS base : {summary_bundle(base_te_met)}", flush=True)

    def scalars(m):
        return {k: v for k, v in m.items() if k not in ("equity", "trades")}

    out = OUT / "crypto_leg.json"
    out.write_text(json.dumps({
        "regime": REGIME_SYM, "fee_pct": FEE_PCT, "universe": sorted(closes.keys()),
        "best_config": best_cfg, "train_score": best_score,
        "oos_best": scalars(te_met), "oos_base": scalars(base_te_met)}, indent=1))
    print(f"[crypto] -> {out}", flush=True)


if __name__ == "__main__":
    main()
