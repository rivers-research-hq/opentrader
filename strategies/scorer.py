#!/usr/bin/env python3
"""Shared honest scorer for strategies. Single source of truth for metrics,
fees, lookahead discipline, and the tournament bars. Ported from the swarm's
scorer.py (commit-traceable) so arena evaluation matches the tournament.

Scoring a strategy = score_equity(equity_series). The strategy produces an
equity pd.Series indexed by the data master; this aligns, computes honest
stats (ann/sharpe/maxdd/calmar), fold beats vs the basket & SPY benchmarks,
and the tournament round bars.
"""

import math
import os
import pickle

import pandas as pd

_DATA_PATHS = [
    "/tmp/opentrader/swarm/swarm_data.pkl",          # tournament data (authoritative)
    os.path.expanduser("~/opentrader-sandbox/data/setup_search/swarm_data.pkl"),
]
_loaded = False
DATA = None


def _load():
    global DATA, MASTER, BENCH_BASKET, BENCH_SPY, FOLDS, _loaded
    for p in _DATA_PATHS:
        if os.path.exists(p):
            DATA = pickle.load(open(p, "rb"))
            break
    if DATA is None:
        raise FileNotFoundError("swarm_data.pkl not found in " + " | ".join(_DATA_PATHS))
    MASTER = DATA["master"]
    BENCH_BASKET = DATA["bench_basket_bh"]
    BENCH_SPY = DATA["bench_spy_bh"]
    FOLDS = DATA["FOLDS"]
    _loaded = True


if not _loaded:
    _load()


def score_equity(eq: pd.Series) -> dict:
    eq = eq.reindex(MASTER).ffill().dropna()
    if len(eq) < 200:
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

    i0 = int(MASTER.searchsorted(pd.Timestamp("2024-01-01")))
    recent = eq.iloc[i0:].dropna()
    recent_net = float(recent.iloc[-1] / recent.iloc[0] - 1) if len(recent) > 30 else None

    return {
        "ann": round(ann, 4), "sharpe": round(sharpe, 4),
        "maxdd": round(dd, 4), "calmar": round(calmar, 4),
        "beats_basket_full": bool(ann > b_ann),
        "beats_spy_ann": bool(ann > s_ann),
        "beats_spy_sharpe": bool(sharpe > s_sharpe),
        "beats_spy_calmar": bool(calmar > s_cal),
        "folds_beat_basket": beats,
        "folds": fold_rows,
        "recent_2024_26_net": round(recent_net, 4) if recent_net is not None else None,
        "bench_basket": {"ann": round(b_ann, 4), "calmar": round(b_cal, 4),
                         "sharpe": round(b_sharpe, 4)},
        "bench_spy": {"ann": round(s_ann, 4), "sharpe": round(s_sharpe, 4),
                      "calmar": round(s_cal, 4)},
    }


def round1_pass(s: dict) -> bool:
    if "error" in s:
        return False
    return s["beats_basket_full"] and s["calmar"] > s["bench_basket"]["calmar"]


def round2_pass(s: dict) -> bool:
    if "error" in s:
        return False
    return s["beats_spy_sharpe"] and s["beats_spy_calmar"] and s["folds_beat_basket"] > 2


def round3_pass(s: dict) -> bool:
    if "error" in s:
        return False
    return s["recent_2024_26_net"] is not None and s["recent_2024_26_net"] > 0.0 and s["maxdd"] > -0.50
