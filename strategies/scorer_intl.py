#!/usr/bin/env python3
"""OOS (international) scorer — mirrors strategies/scorer.py but on the intl
data. OOS pass = beat the intl basket BH on Calmar AND Sharpe."""

import math
import os
import pickle

import pandas as pd

_DATA_PATHS = [
    # intl_data.pkl (authoritative /tmp copy) was LOST to cleanup 2026-08-23;
    # durable restoration target per data/MANIFEST.json is the evidence tier.
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "evidence", "swarm", "intl_data.pkl"),
]


def _load():
    for p in _DATA_PATHS:
        if os.path.exists(p):
            DATA = pickle.load(open(p, "rb"))
            return DATA
    raise FileNotFoundError("intl_data.pkl not found in " + " | ".join(_DATA_PATHS))


# Lazy (#155): import must not require the lost pkl; score_equity loads on
# first use and raises FileNotFoundError with the honest lost-data message.
DATA = None
MASTER = None
BENCH_BASKET = None
BENCH_SPY = None
FOLDS = None
_loaded = False


def _ensure():
    global DATA, MASTER, BENCH_BASKET, BENCH_SPY, FOLDS, _loaded
    if _loaded:
        return
    DATA = _load()
    MASTER = DATA["master"]
    BENCH_BASKET = DATA["bench_basket_bh"]
    BENCH_SPY = DATA["bench_spy_bh"]
    FOLDS = DATA["FOLDS"]
    _loaded = True


def score_equity(eq: pd.Series) -> dict:
    _ensure()
    eq = eq.reindex(MASTER).ffill().dropna()
    if len(eq) < 100:
        return {"error": "equity too short"}
    r = eq.pct_change().dropna()
    ann = float(eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1
    sharpe = float(r.mean() / r.std() * math.sqrt(252)) if r.std() > 0 else 0.0
    dd = float((eq / eq.cummax() - 1.0).min())
    calmar = ann / abs(dd) if dd < 0 else float("inf")

    bench = BENCH_BASKET.reindex(MASTER).ffill()
    br = bench.pct_change().dropna()
    b_ann = float(bench.iloc[-1] / bench.iloc[0]) ** (252 / len(bench)) - 1
    b_dd = float((bench / bench.cummax() - 1.0).min())
    b_cal = b_ann / abs(b_dd) if b_dd < 0 else float("inf")
    b_sharpe = float(br.mean() / br.std() * math.sqrt(252)) if br.std() > 0 else 0.0

    spy = BENCH_SPY.reindex(MASTER).ffill()
    sr = spy.pct_change().dropna()
    s_ann = float(spy.iloc[-1] / spy.iloc[0]) ** (252 / len(spy)) - 1
    s_dd = float((spy / spy.cummax() - 1.0).min())
    s_cal = s_ann / abs(s_dd) if s_dd < 0 else float("inf")
    s_sharpe = float(sr.mean() / sr.std() * math.sqrt(252)) if sr.std() > 0 else 0.0

    fold_rows = []
    beats = 0
    for a, b in FOLDS:
        i0 = int(MASTER.searchsorted(pd.Timestamp(a)))
        i1 = int(MASTER.searchsorted(pd.Timestamp(b))) + 1
        seg, sb = eq.iloc[i0:i1], bench.iloc[i0:i1]
        if len(seg) < 30 or len(sb) < 30:
            continue
        sn = seg.iloc[-1] / seg.iloc[0] - 1
        bn = sb.iloc[-1] / sb.iloc[0] - 1
        ok = sn > bn
        beats += int(ok)
        fold_rows.append({"fold": f"{a[:4]}-{b[:4]}", "strategy": round(sn, 4),
                          "basket_bh": round(bn, 4), "beat_basket": ok})

    return {
        "ann": round(ann, 4), "sharpe": round(sharpe, 4),
        "maxdd": round(dd, 4), "calmar": round(calmar, 4),
        "folds_beat_basket": beats, "folds": fold_rows,
        "beats_basket_calmar": bool(calmar > b_cal),
        "beats_basket_sharpe": bool(sharpe > b_sharpe),
        "beats_spy_calmar": bool(calmar > s_cal),
        "bench_basket": {"ann": round(b_ann, 4), "calmar": round(b_cal, 4),
                         "sharpe": round(b_sharpe, 4)},
        "bench_spy": {"ann": round(s_ann, 4), "calmar": round(s_cal, 4),
                      "sharpe": round(s_sharpe, 4)},
    }


def oos_pass(s: dict) -> bool:
    if "error" in s:
        return False
    return s["beats_basket_calmar"] and s["beats_basket_sharpe"]


def bull_participation_oos(s: dict) -> bool:
    """Round 1d bar (international): the missing piece — BEAT the equal-weight
    basket in the broad-bull fold (2023-26) while still beating it risk-
    adjusted. All 8 verified experts trail the basket there (+64.5% vs
    ~50-57%); they win drawdown but not participation."""
    if "error" in s:
        return False
    folds = {f["fold"]: f for f in s.get("folds", [])}
    f = folds.get("2023-2026")
    if f is None or not f.get("beat_basket"):
        return False
    return s["beats_basket_calmar"] and s["beats_basket_sharpe"] and s["maxdd"] > -0.20
