#!/usr/bin/env python3
"""trailing_ab — backtest A/B: does a pseudo trailing stop or TP improve the
rank book over hold-to-rebalance? Same OOS folds, same scores, same costs.
Adopt into the live lane ONLY if a variant beats the no-stop baseline OOS
(the live↔measured contract — human directive 2026-09-09)."""

import json
import sys
from pathlib import Path

import duckdb
import numpy as np

STORE = "/home/mrc/opentrader-data/store.duckdb"
SCORES = Path(__file__).resolve().parent.parent / "data" / "fx_expert" / "oos_scores_gab1.npz"
PERIOD = 5  # trading days per rank-book period (mirrors the lane)


def load():
    meta = json.loads((Path(__file__).resolve().parent.parent / "data" / "fx_expert" / "panel_meta.json").read_text())
    idx2sym = {m["idx"]: m["pair"] for m in meta["pairs"]}
    z = np.load(SCORES)
    day, pi, score = z["day"], z["pair_idx"], z["score"]
    atr, cost, fold = z["atr_pct"], z["cost"], z["fold"]
    con = duckdb.connect(STORE, read_only=True)
    closes = {}
    for sym, bday, c in con.execute(
            "SELECT symbol, CAST(epoch(ts)/86400 AS BIGINT) AS day, close FROM bars WHERE timeframe='1d' ORDER BY ts").fetchall():
        closes.setdefault(sym, {})[int(bday)] = float(c)
    con.close()
    return day, pi, score, atr, cost, fold, closes, idx2sym


def sim(day, pi, score, atr, cost, fold, closes, idx2sym,
        trail_k=None, tp_k=None):
    """Rank book in 5-day periods; per-leg trailing stop / TP in ATR units;
    daily mark-to-market in weight space; round-trip cost on exit."""
    daily = {}
    exits = {"trail": 0, "tp": 0, "period": 0}
    for f in np.unique(fold):
        fm = fold == f
        d_f, pi_f, s_f, a_f, c_f = day[fm], pi[fm], score[fm], atr[fm], cost[fm]
        udays = np.unique(d_f)
        udays.sort()
        close_of = {}  # (pair_idx, day) -> px
        for k in range(len(d_f)):
            sym = idx2sym[int(pi_f[k])]
            px = closes.get(sym, {}).get(int(d_f[k]))
            if px is not None:
                close_of[(int(pi_f[k]), int(d_f[k]))] = px
        for p_start in range(0, len(udays), PERIOD):
            block = udays[p_start: p_start + PERIOD]
            entry_day = int(block[0])
            em = d_f == entry_day
            if not em.any():
                continue
            s_e = s_f[em]
            order = np.argsort(np.argsort(s_e)) + 1
            n = len(s_e)
            w_e = (order / n - 0.5) * 2.0
            legs = []
            for k in range(n):
                pidx = int(pi_f[em][k])
                sym = idx2sym[pidx]
                px = closes.get(sym, {}).get(entry_day)
                if px is None:
                    continue
                legs.append({"sym": sym, "w": float(w_e[k]), "entry": px,
                             "peak": px, "trough": px, "prev": px,
                             "atr_pct": float(a_f[em][k]), "cost": float(c_f[em][k]),
                             "open": True})
            for d in block:
                day_pnl = 0.0
                for leg in legs:
                    if not leg["open"]:
                        continue
                    px = closes.get(leg["sym"], {}).get(int(d))
                    if px is None:
                        continue
                    a = leg["atr_pct"] * px
                    ret_day = px / leg["prev"] - 1.0
                    day_pnl += leg["w"] * ret_day
                    if leg["w"] > 0:
                        leg["peak"] = max(leg["peak"], px)
                    else:
                        leg["trough"] = min(leg["trough"], px)
                    hit = False
                    if trail_k:
                        if leg["w"] > 0 and px < leg["peak"] - trail_k * a:
                            hit = True; exits["trail"] += 1
                        if leg["w"] < 0 and px > leg["trough"] + trail_k * a:
                            hit = True; exits["trail"] += 1
                    if tp_k:
                        if leg["w"] > 0 and px >= leg["entry"] + tp_k * a:
                            hit = True; exits["tp"] += 1
                        if leg["w"] < 0 and px <= leg["entry"] - tp_k * a:
                            hit = True; exits["tp"] += 1
                    last = d == block[-1]
                    if hit or last:
                        if last and not hit:
                            exits["period"] += 1
                        day_pnl -= leg["cost"] * abs(leg["w"])
                        leg["open"] = False
                    leg["prev"] = px
                daily[int(d)] = daily.get(int(d), 0.0) + day_pnl
    return daily, exits


def metrics(daily):
    s = np.array([daily[d] for d in sorted(daily)])
    gains = s[s > 0].sum(); losses = -s[s < 0].sum()
    pf = gains / losses if losses > 0 else float("inf")
    sh = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else 0.0
    dd = (np.cumsum(s) - np.maximum.accumulate(np.cumsum(s))).min()
    return {"pf": round(float(pf), 3), "sharpe": round(float(sh), 2),
            "maxdd": round(float(dd), 4), "mean_bps": round(float(s.mean() * 1e4), 2)}


def main():
    day, pi, score, atr, cost, fold, closes, idx2sym = load()
    variants = [("baseline (hold to rebalance)", None, None),
                ("trail 1.0 ATR", 1.0, None), ("trail 1.5 ATR", 1.5, None),
                ("trail 2.0 ATR", 2.0, None), ("trail 3.0 ATR", 3.0, None),
                ("tp 2.0 ATR", None, 2.0), ("tp 3.0 ATR", None, 3.0),
                ("trail 1.5 + tp 3.0", 1.5, 3.0)]
    print(f"{'variant':30s} {'PF':>7s} {'Sharpe':>7s} {'maxDD':>9s} {'bp/day':>8s} exits")
    for name, tk, pk in variants:
        daily, exits = sim(day, pi, score, atr, cost, fold, closes, idx2sym, tk, pk)
        m = metrics(daily)
        ex_s = f"{exits['trail']}t/{exits['tp']}p/{exits['period']}r"
        print(f"{name:30s} {m['pf']:>7.3f} {m['sharpe']:>7.2f} {m['maxdd']:>9.4f} "
              f"{m['mean_bps']:>8.2f} {ex_s}")


if __name__ == "__main__":
    main()
