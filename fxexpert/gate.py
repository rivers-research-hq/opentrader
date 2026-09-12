#!/usr/bin/env python3
"""fxexpert.gate — OOS evaluation of a generation's predictions.

Two position rules, chosen per config (hp["rule"]), both simulated on the
same OOS predictions and the same per-pair round-trip cost heuristic:

  thr  — per pair-day: enter long/short when the score crosses that fold's
         TRAIN entry quantile (hp["q"], default 0.80); hysteresis exit: the
         position holds until the score decays back through the TRAIN median.
         Cuts churn vs one-threshold in/out; daily PnL averaged over ALL
         pairs present (flat pairs contribute 0).

  xs   — dollar-neutral cross-sectional: each day long the top-k and short
         the bottom-k pairs by score (hp["k"], default 3). Daily PnL averaged
         over the 2k deployed positions.

Baselines use the identical protocol and cost model: buy-and-hold, classic
RSI(14) mean-reversion, 20d momentum sign, and a random sign draw matched to
the model's position frequencies.

Gate (re-specified 2026-09-12, human-delegated decision on #257): the old
`PF >= 1.05` promotion bar was measured to be noise-dominated and is retired
as a promotion criterion. Evidence (scripts/gate_stat_study.py,
scripts/gate_stat_study2.py, 101-generation 58-pair population):

  - PF, Sharpe, mean return and their t-stat are the SAME statistic
    (Spearman >= 0.985 across generations) — swapping PF for t/Sharpe would
    have changed nothing;
  - the cross-generation ranking does not persist: year-to-year Spearman
    +0.02, first-half vs second-half -0.23, even/odd weeks +0.50. A backtest
    winner is a regime fit, not a durable property;
  - corr(IC, PF) = 0.168, and PF spans 0.76-1.29 within one IC quartile.

This gate therefore certifies only that a candidate is COHERENT (signal
positive and folds, net return positive, sane book, beats the random-matched
control) — eligibility to accrue, not promotion. Promotion evidence is the
forward shadow accrual ledger (ADR-0009 §3-4); any *claim* of backtest edge
must still clear the deflated bar (scripts/white_reality_check.py, ToC V-WRC).
Live order flow stays human-gated.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "fx_expert"
# Eligibility criteria (2026-09-12). These are COHERENCE checks, deliberately
# low-variance and not a performance bar: a candidate that fails them is
# broken (negative signal, losing book, unhedged or untraded book), not merely
# unimpressive. PF >= 1.05 is retained in the report for continuity but no
# longer decides anything.
GATE = {"ic_min": 0.0, "folds_positive_min": 2, "min_pairdays": 2000,
        "net_exposure_max": 0.2, "mean_bps_min": 0.0,
        "pf_reported_only": 1.05}
# Backwards-compatible alias: older callers import GATE["pf_min"].
GATE["pf_min"] = GATE["pf_reported_only"]


def _daily_pnl(dates, pair_idx, raw_pos, fwd1, cost, denom="all"):
    """Daily portfolio P&L series (the raw return series behind every gate
    metric). Kept separate from _simulate so multiple-testing corrections can
    bootstrap the same series the gate scored."""
    order = np.lexsort((dates, pair_idx))
    pnl = np.zeros(len(dates), dtype=np.float64)
    prev = {}
    for i in order:
        p = int(pair_idx[i])
        pos = float(raw_pos[i])
        chg = abs(pos - prev.get(p, 0.0))
        pnl[i] = pos * fwd1[i] - chg * cost[i]
        prev[p] = pos
    if denom == "all":
        return pd.Series(pnl).groupby(dates).mean().sort_index()
    # "pos": mean over deployed positions only (no flat dilution)
    mask = np.asarray(raw_pos) != 0
    if not mask.any():
        return pd.Series(dtype=np.float64)
    return pd.Series(pnl[mask]).groupby(dates[mask]).mean().sort_index()


def _simulate(dates, pair_idx, raw_pos, fwd1, cost, denom="all"):
    daily = _daily_pnl(dates, pair_idx, raw_pos, fwd1, cost, denom)
    gains = daily[daily > 0].sum()
    losses = -daily[daily < 0].sum()
    pf = float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else None)
    sh = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 2 and daily.std() > 0 else 0.0
    cum = daily.cumsum()
    maxdd = float((cum - cum.cummax()).min()) if len(daily) else 0.0
    return {"pf": None if pf is None else round(pf, 4), "sharpe": round(sh, 3),
            "maxdd": round(maxdd, 5), "days": int(len(daily)),
            "daily_mean_bps": round(float(daily.mean() * 1e4), 3) if len(daily) else 0.0}


def _positions_thr(dates, pair_idx, score, q_long, q_short, q_mid):
    """Threshold entry + hysteresis exit per pair, chronological."""
    order = np.lexsort((dates, pair_idx))
    pos = np.zeros(len(score), dtype=np.float32)
    cur = {}
    for i in order:
        p = int(pair_idx[i])
        s = float(score[i])
        c = cur.get(p, 0.0)
        if c >= 0 and s >= q_long[i]:
            c = 1.0
        elif c <= 0 and s <= q_short[i]:
            c = -1.0
        elif c > 0 and s < q_mid[i]:
            c = 0.0
        elif c < 0 and s > q_mid[i]:
            c = 0.0
        cur[p] = c
        pos[i] = c
    return pos


def _positions_xs(dates, pair_idx, score, k=3):
    """Dollar-neutral cross-sectional: long top-k, short bottom-k per day."""
    df = pd.DataFrame({"d": dates, "p": pair_idx, "s": score})
    hi = df.groupby("d")["s"].rank(ascending=False, method="first")
    lo = df.groupby("d")["s"].rank(ascending=True, method="first")
    pos = np.where(hi.to_numpy() <= k, 1.0,
                   np.where(lo.to_numpy() <= k, -1.0, 0.0))
    return pos.astype(np.float32)


def _positions_thr_cont(dates, pair_idx, score, q_long, q_short, q_mid,
                        size_cap=2.0):
    """Hysteresis entry/exit, CONTINUOUS sizing sized ONCE AT ENTRY
    (magnitude = |score| / entry-quantile, clipped at size_cap) and held
    until the hysteresis exit. Daily re-sizing was tried first (g124-129)
    and churns round-trip cost every bar — entry-only sizing is the fix."""
    order = np.lexsort((dates, pair_idx))
    pos = np.zeros(len(score), dtype=np.float32)
    cur = {}
    for i in order:
        p = int(pair_idx[i])
        s = float(score[i])
        c = cur.get(p, 0.0)
        if c == 0.0:
            if s >= q_long[i]:
                c = min(s / max(q_long[i], 1e-9), size_cap)
            elif s <= q_short[i]:
                c = -min(s / min(q_short[i], -1e-9), size_cap)
        elif c > 0 and s < q_mid[i]:
            c = 0.0
        elif c < 0 and s > q_mid[i]:
            c = 0.0
        cur[p] = c
        pos[i] = c
    return pos


def _positions_rank(dates, pair_idx, score, vol20=None, cost=None,
                    lev=1.0, vol_target=False, cost_cap=None, rebal=1):
    """Cross-sectional rank-weighted portfolio: weight ∝ (pct_rank − 0.5) × 2
    × lev — dollar-neutral by construction. Weights refresh every `rebal`
    trading days (daily refresh churns rank flips into cost; weekly is the
    FX-factor standard). Optional vol targeting (cross-pair median vol /
    pair vol, clipped 0.5-2.0) and cost gating (zero legs above cost_cap)."""
    df = pd.DataFrame({"d": dates, "p": pair_idx, "s": score})
    r = df.groupby("d")["s"].rank(pct=True, method="first").to_numpy() - 0.5
    tgt = (r * 2.0 * lev).astype(np.float32)
    if vol_target and vol20 is not None:
        v = pd.Series(vol20)
        med = v.groupby(dates).transform("median")
        tgt = tgt * np.clip((med / np.maximum(v, 1e-9)).to_numpy(), 0.5, 2.0)
    if cost_cap is not None and cost is not None:
        tgt = np.where(np.asarray(cost) <= cost_cap, tgt, 0.0).astype(np.float32)
    if rebal <= 1:
        return tgt
    df2 = pd.DataFrame({"d": dates, "p": pair_idx, "tgt": tgt})
    udays = np.sort(pd.unique(df2["d"]))
    period_of = {d: i // rebal for i, d in enumerate(udays)}
    df2["per"] = df2["d"].map(period_of)
    start_d = df2.groupby("per")["d"].min()
    df2["src_d"] = df2["per"].map(start_d)
    idx = pd.MultiIndex.from_frame(df2[["d", "p"]])
    pos = pd.Series(df2["tgt"].to_numpy(), index=idx).reindex(
        pd.MultiIndex.from_frame(df2[["src_d", "p"]])).to_numpy()
    return pos.astype(np.float32)


def _vol_scale(raw, dates, vol20):
    """Vol targeting for an existing position vector: scale by cross-pair
    median vol / pair vol, clipped 0.5-2.0."""
    if vol20 is None:
        return raw
    v = pd.Series(vol20, dtype=float)
    med = v.groupby(dates).transform("median")
    return (raw * np.clip((med / np.maximum(v, 1e-9)).to_numpy(), 0.5, 2.0)
            ).astype(np.float32)


def build_positions(hp, P):
    """Raw position vector for config `hp` on its own OOS predictions, plus
    the _simulate denominator that pairs with it. The single construction path
    shared by evaluate() and the return-series deflation."""
    rule = hp.get("rule", "thr")
    dates, pi = P["date"], P["pair_idx"]
    if rule == "xs":
        return _positions_xs(dates, pi, P["score"], k=int(hp.get("k", 3))), "pos"
    if rule == "thr_cont":
        raw = _positions_thr_cont(dates, pi, P["score"], P["q_long"],
                                  P["q_short"], P["q_mid"],
                                  size_cap=float(hp.get("size_cap", 2.0)))
        if hp.get("vol_target"):
            raw = _vol_scale(raw, dates, P.get("vol20"))
        if hp.get("cost_cap") is not None:
            raw = np.where(np.asarray(P["cost"]) <= float(hp["cost_cap"]),
                           raw, 0.0).astype(np.float32)
        return raw, "all"
    if rule == "rank":
        raw = _positions_rank(dates, pi, P["score"], P.get("vol20"),
                              P["cost"], lev=float(hp.get("lev", 1.0)),
                              vol_target=bool(hp.get("vol_target")),
                              cost_cap=hp.get("cost_cap"),
                              rebal=int(hp.get("rebal", 1)))
        return raw, "all"
    return _positions_thr(dates, pi, P["score"], P["q_long"],
                          P["q_short"], P["q_mid"]), "all"


def daily_pnl_series(tag, out_dir=OUT_DIR):
    """Daily OOS portfolio P&L series for a generation, computed through the
    gate's own position construction and cost model (no re-implementation)."""
    P = dict(np.load(out_dir / f"preds_g{tag}.npz"))
    g = json.loads((out_dir / f"train_g{tag}.json").read_text())
    raw, denom = build_positions(g["hp"], P)
    return _daily_pnl(P["date"], P["pair_idx"], raw, P["fwd1"], P["cost"], denom)


def evaluate(tag, out_dir=OUT_DIR, write=True):
    """Score one generation. `write=False` audits without touching the
    recorded gate_g*.json (those files record what the gate said at run time;
    re-judging an old generation must not rewrite that history)."""
    P = dict(np.load(out_dir / f"preds_g{tag}.npz"))
    g = json.loads((out_dir / f"train_g{tag}.json").read_text())
    hp = g["hp"]
    rule = hp.get("rule", "thr")
    dates, pi = P["date"], P["pair_idx"]
    res = {"rule": rule}

    def sim_for(r):
        raw, denom = build_positions({**hp, "rule": r}, P)
        return raw, _simulate(dates, pi, raw, P["fwd1"], P["cost"], denom=denom)

    raw, m = sim_for(rule)
    raw = np.nan_to_num(np.asarray(raw), nan=0.0, posinf=0.0, neginf=0.0)
    res["model"] = m
    m["n_pairdays"] = int((raw != 0).sum())
    m["long_frac"] = round(float((raw > 0).mean()), 3)
    m["short_frac"] = round(float((raw < 0).mean()), 3)
    _, alt = sim_for("xs" if rule == "thr" else "thr")
    res["model_alt_rule"] = alt  # reported for the record, not gated

    ones = np.ones(len(dates), dtype=np.float32)
    res["buy_hold"] = _simulate(dates, pi, ones, P["fwd1"], P["cost"])
    rsi_pos = np.zeros(len(dates), dtype=np.float32)
    rsi_pos[P["rsi_raw"] < 30] = 1.0
    rsi_pos[P["rsi_raw"] > 70] = -1.0
    res["rsi_mr_14"] = _simulate(dates, pi, rsi_pos, P["fwd1"], P["cost"])
    mom_pos = np.where(np.nan_to_num(P["mom20"]) > 0, 1.0, -1.0).astype(np.float32)
    res["mom20_sign"] = _simulate(dates, pi, mom_pos, P["fwd1"], P["cost"])
    rng = np.random.default_rng(7)
    fracs = [m["long_frac"], m["short_frac"],
             max(0.0, 1 - m["long_frac"] - m["short_frac"])]
    tot = sum(fracs)
    rnd = rng.choice([1.0, -1.0, 0.0], size=len(dates),
                     p=[f / tot for f in fracs]).astype(np.float32)
    res["random_matched"] = _simulate(dates, pi, rnd, P["fwd1"], P["cost"])

    xgb_ref = None
    ref_path = Path(__file__).resolve().parent.parent / "data" / "training" / "walkforward_ml_results.json"
    if ref_path.exists():
        xgb_ref = json.loads(ref_path.read_text()).get("aggregate", {}).get("pf")

    # ---- eligibility: coherence checks, NOT a performance bar -------------
    reasons = []
    gross = float(np.abs(raw).sum())
    net_ratio = float(np.abs(raw.sum()) / gross) if gross > 0 else 1.0
    m["net_exposure_ratio"] = round(net_ratio, 4)
    dollar_neutral = net_ratio <= GATE["net_exposure_max"]
    m["dollar_neutral"] = dollar_neutral
    res["gate_amendment"] = {"beat_buy_hold": not dollar_neutral,
                             "net_exposure_max": GATE["net_exposure_max"]}
    agg = g["aggregate"]
    if agg.get("ic_mean") is None or agg["ic_mean"] <= GATE["ic_min"]:
        reasons.append(f"OOS IC {agg.get('ic_mean')} not positive")
    if agg["folds_positive"] < GATE["folds_positive_min"]:
        reasons.append(f"positive-IC folds {agg['folds_positive']}/{agg['n_folds']}")
    if m["daily_mean_bps"] <= GATE["mean_bps_min"]:
        reasons.append(f"net mean {m['daily_mean_bps']} bps/day not positive")
    if m["n_pairdays"] < GATE["min_pairdays"]:
        reasons.append(f"n_pairdays {m['n_pairdays']} < {GATE['min_pairdays']}")
    if not dollar_neutral:
        reasons.append(f"net exposure ratio {net_ratio:.3f} > "
                       f"{GATE['net_exposure_max']} (directional book)")
        bh = res.get("buy_hold", {}).get("pf")
        if bh is not None and (m["pf"] is None or m["pf"] <= bh):
            reasons.append(f"directional book does not beat buy-and-hold "
                           f"({m['pf']} <= {bh})")
    rnd = res.get("random_matched", {}).get("pf")
    if rnd is not None and (m["pf"] is None or m["pf"] <= rnd):
        reasons.append(f"does not beat the random-matched control ({m['pf']} <= {rnd})")
    res["gate"] = {"verdict": "ELIGIBLE" if not reasons else "NOT ELIGIBLE",
                   "reasons": reasons, "criteria": GATE,
                   "promotion": "forward shadow accrual only (ADR-0009 §3-4)",
                   "backtest_claims": "require the deflated bar "
                                      "(scripts/white_reality_check.py, ToC V-WRC)",
                   "pf_reported_only": m["pf"], "xgb_reference_pf": xgb_ref}

    if write:
        (out_dir / f"gate_g{tag}.json").write_text(json.dumps(res, indent=1))
    print(f"[gate g{tag}] rule={rule} model PF {m['pf']} Sharpe {m['sharpe']} "
          f"maxDD {m['maxdd']} pairdays {m['n_pairdays']} | alt-rule PF "
          f"{res['model_alt_rule']['pf']} | baselines " +
          " ".join(f"{k}={v['pf']}" for k, v in res.items()
                   if k in ("buy_hold", "rsi_mr_14", "mom20_sign", "random_matched")) +
          f" | xgb_ref={xgb_ref} | {res['gate']['verdict']}")
    if reasons:
        for r in reasons:
            print(f"  - {r}")
    return res


if __name__ == "__main__":
    import sys
    evaluate(sys.argv[1] if len(sys.argv) > 1 else "00")
