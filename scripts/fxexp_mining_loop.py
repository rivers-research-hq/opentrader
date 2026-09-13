#!/usr/bin/env python3
"""fxexp_mining_loop — operator-grammar mining over the exogenous space (#206/#208/#209/#210).

PRE-REGISTERED IN CODE (fixed before the run; amendments require a logged
human call, per the V32/equity-sketch discipline):

  Substrate   data/fx_expert/panel_v2.npz (289,467 pair-days, 57 pairs,
              2008-09-25..2026-09-10, 61 features; the #205 v2 exogenous
              joins). fwd1 = next-day return, cost = per-pair round-trip
              heuristic. fwd1 has no NaNs; rows with NaN operands score 0
              (mid-rank, ~flat) — deterministic, no row drops.

  Operands    17 EXOGENOUS-only base features: carry, carry_z, rate_diff,
              rate_diff_chg20, cot_z, events_5d, fred_{vix,hy,epu,wti,iron,
              ttf,dgs2,dgs10,curve,real10}_z, fred_wti_chg20. No price-volume
              operands — the probes established that null, and the dead-probe
              graveyard (V02/V03/V04/V33, price-volume families) is therefore
              structurally disjoint from this grammar (the similarity control;
              numeric check below still runs against in-universe proxies).

  Grammar     unary (6): identity, sign, rank_xs (per-day pct rank - 0.5),
              zscore_xs (per-day z), lag1, delta5 (per-pair shifts).
              binary (4): *, -, +, / (guarded: |denominator| < 1e-12 -> 0).
              depth <= 2: L1 = operand x unary (102); L2 = (L1 op base) +
              (base_i op base_j) i<j (7,480). Total family = 7,582 tests —
              the ~10^4 load the map pre-priced the bar for.

  Evaluation  ONE protocol, the live lanes' own book: fxexpert.gate's
              _positions_rank (cross-sectional rank-weighted, dollar-neutral,
              lev 1, rebal every 5 trading days) + _daily_pnl with the panel
              cost model. Walkforward: unique dates split into 4 quarters,
              test = quarters 2-4 (the trainer's protocol); fold PFs from the
              test spans only. No re-implementation of the book.

  Raised bar  (all must hold):
    1. Deflation: White's Reality Check in PF space (the #245 human-selected
       statistic; same stationary-block machinery as
       scripts/white_reality_check.py, calibrated by tests/test_wrc_calibration.py)
       over the JOINT family of daily test-span series, recentered to zero
       mean. Bar: candidate PF >= the 95th percentile of the joint null
       max-PF distribution (B=2000, block 20d).
    2. Coherence: mean bp/day > 0 AND fold PF > 1 in >= 2/3 folds.
    3. Similarity: |corr| of the candidate's daily series vs the in-universe
       dead-family proxies (mom20 sign book, RSI-14 MR book) <= 0.7.

  Outcome     survivors recorded with full stats; if none, the honest
              statement is recorded and the artifact carries the whole
              family's results (the map's bottom line accepts exactly this).

CPU-only (the 3070/GRE contract is untouched). Usage:
  .venv/bin/python3 scripts/fxexp_mining_loop.py [--limit N] [--B 2000]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from fxexpert.gate import _daily_pnl, _positions_rank  # noqa: E402

PANEL = PROJECT / "data" / "fx_expert" / "panel_v2.npz"
OUT = PROJECT / "data" / "fx_expert" / "mining_loop_result.json"

BASE = ["carry", "carry_z", "rate_diff", "rate_diff_chg20", "cot_z", "events_5d",
        "fred_vix_z", "fred_hy_z", "fred_epu_z", "fred_wti_z", "fred_iron_z",
        "fred_ttf_z", "fred_dgs2_z", "fred_dgs10_z", "fred_curve_z",
        "fred_real10_z", "fred_wti_chg20"]
UNARY = ["id", "sign", "rank_xs", "zscore_xs", "lag1", "delta5"]
BINARY = ["mul", "sub", "add", "div"]
GRAVEYARD_PROXY_CORR_MAX = 0.7


def unary_fn(name, x, dates, pair_idx):
    if name == "id":
        return x
    if name == "sign":
        return np.sign(np.nan_to_num(x, nan=0.0))
    s = pd.Series(np.nan_to_num(x, nan=0.0))
    if name == "rank_xs":
        return (s.groupby(dates).rank(pct=True).to_numpy() - 0.5).astype(np.float32)
    if name == "zscore_xs":
        g = s.groupby(dates)
        mu = g.transform("mean").to_numpy()
        sd = g.transform("std").to_numpy()
        return ((s.to_numpy() - mu) / np.where(sd < 1e-12, np.inf, sd)).astype(np.float32)
    if name == "lag1":
        return s.groupby(pair_idx).shift(1).to_numpy().astype(np.float32)
    if name == "delta5":
        return (x - s.groupby(pair_idx).shift(5).to_numpy()).astype(np.float32)
    raise ValueError(name)


def binary_fn(name, a, b):
    a = np.nan_to_num(a, nan=0.0).astype(np.float32)
    b = np.nan_to_num(b, nan=0.0).astype(np.float32)
    if name == "mul":
        return a * b
    if name == "sub":
        return a - b
    if name == "add":
        return a + b
    if name == "div":
        return np.where(np.abs(b) < 1e-12, 0.0, a / np.where(np.abs(b) < 1e-12, 1.0, b)).astype(np.float32)
    raise ValueError(name)


def pf_of(series):
    g = series[series > 0].sum()
    l = -series[series < 0].sum()
    return float(g / l) if l > 0 else float("inf")


PF_CAP = 1e6  # degenerate loss-free replicates; same cap on null and observed


class FastBook:
    """Vectorized equivalent of the gate's book (rank-weighted, rebal=5,
    _daily_pnl 'all' denominator), verified at startup against
    fxexpert.gate on sample candidates (atol 1e-5/day). The pandas path is
    ~1.1s/candidate; this one ~15ms — the 7.5k-candidate family needs it.
    Any mismatch aborts the run (no silent divergence)."""

    def __init__(self, dates, pair_idx, fwd1, cost, rebal=5):
        self.rebal = rebal
        order = np.lexsort((pair_idx, dates))
        self.order = order
        self.d_s, self.p_s = dates[order], pair_idx[order]
        self.fwd_s, self.cost_s = fwd1[order], cost[order]
        self.udays = np.unique(dates)
        D, self.day_of = len(self.udays), np.searchsorted(self.udays, self.d_s)
        P = int(pair_idx.max()) + 1
        self.D, self.P = D, P
        # per-row previous same-pair row (gate's prev-dict semantics),
        # -1 -> prev weight 0. Sorted space is day-ascending, so a pair's
        # rows appear in date order and groupby-shift gives the chronological
        # previous row.
        pr = pd.Series(np.arange(len(self.d_s), dtype=np.float64)) \
            .groupby(self.p_s).shift(1).to_numpy()
        self.prev_idx = np.where(np.isnan(pr), -1, pr).astype(np.int64)

    def daily(self, score):
        # EXACT gate semantics: pandas rank(pct, 'first') ranks only FINITE
        # scores (NaN rows get NaN weight, excluded from the day's denominator
        # and mean); a NaN weight poisons the pair's next row's cost term too;
        # reindex-miss pairs (absent on the period-start day) stay NaN through
        # the period; daily mean skips NaN pnl rows.
        s_raw = np.asarray(score, np.float32)[self.order]
        valid = np.isfinite(s_raw)
        s_key = np.where(valid, s_raw, -np.inf)
        n = len(s_key)
        # primary key = day (contiguous blocks), then score, tie -> pair
        o = np.lexsort((self.p_s, s_key, self.d_s))
        d_o = self.d_s[o]
        v_o = valid[o]
        new_day = np.empty(n, bool)
        new_day[0] = True
        new_day[1:] = d_o[1:] != d_o[:-1]
        day_id = np.cumsum(new_day) - 1
        day_start = np.maximum.accumulate(np.where(new_day, np.arange(n), 0))
        pos_within = np.arange(n) - day_start
        cum_inv = np.cumsum(~v_o)
        inv_before = cum_inv - (cum_inv[day_start] - (~v_o[day_start]))
        cnt_valid = np.bincount(day_id, weights=v_o.astype(np.float64))
        rank_pos = pos_within - inv_before
        pct = ((rank_pos + 1.0) / cnt_valid[day_id] - 0.5) * 2.0  # gate: (pct-0.5)*2*lev
        ranks_sorted = np.where(v_o, pct, np.nan).astype(np.float32)
        ranks = np.empty(n, np.float32)
        ranks[o] = ranks_sorted
        # (day, pair) grid of target weights; absent cells stay NaN
        tgt = np.full((self.D, self.P), np.nan, np.float32)
        tgt[self.day_of, self.p_s] = ranks
        # carry the period-start day's weights through the rebal period
        starts = np.arange(0, self.D, self.rebal)
        counts = np.diff(np.append(starts, self.D))
        carried = np.repeat(tgt[starts], counts, axis=0)
        w = carried[self.day_of, self.p_s]
        w_prev = np.where(self.prev_idx >= 0,
                          w[np.maximum(self.prev_idx, 0)], 0.0)
        chg = np.abs(w - w_prev)
        pnl = w * self.fwd_s - self.cost_s * chg
        finite = np.isfinite(pnl)
        sums = np.bincount(self.day_of[finite], weights=pnl[finite], minlength=self.D)
        cnts = np.bincount(self.day_of[finite], minlength=self.D)
        m = cnts > 0
        return pd.Series((sums[m] / cnts[m]).astype(np.float64),
                         index=self.udays[m]).sort_index()


def stationary_counts(T, L, rng, B):
    """Stationary bootstrap resample counts (Politis-Romano), identical math
    to scripts/white_reality_check.py (imported there via same parameters)."""
    p = 1.0 / L
    counts = np.empty((B, T), dtype=np.float64)
    ar = np.arange(T)
    for b in range(B):
        new = rng.random(T) < p
        new[0] = True
        starts = np.flatnonzero(new)
        base = rng.integers(0, T, size=starts.size)
        last_start = np.maximum.accumulate(np.where(new, ar, 0))
        base_of = np.zeros(T, dtype=np.int64)
        base_of[starts] = base
        idx = (base_of[last_start] + (ar - last_start)) % T
        counts[b] = np.bincount(idx, minlength=T)
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="smoke: cap candidates")
    ap.add_argument("--B", type=int, default=2000)
    ap.add_argument("--block", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    t0 = time.time()

    z = np.load(PANEL, allow_pickle=False)
    feats = {n: z["features"][:, i].astype(np.float32)
             for i, n in enumerate(z["feature_names"])}
    dates, pair_idx = z["date"], z["pair_idx"]
    fwd1, cost = z["fwd1"], z["cost"]
    dates_s = pd.Series(dates)
    n_rows = len(dates)

    # walkforward folds: unique dates -> 4 quarters, test = quarters 2-4
    udays = np.unique(dates)
    n = len(udays)
    folds = []
    for q in (1, 2, 3):
        lo, hi = udays[int(n * 0.25 * q)], udays[int(n * 0.25 * (q + 1)) - 1]
        folds.append((int(lo), int(hi)))
    fold_idx = np.zeros(n_rows, dtype=np.int8)
    for fi, (lo, hi) in enumerate(folds):
        fold_idx[(dates >= lo) & (dates <= hi)] = fi + 1

    # base operands + cached unary transforms
    cache = {}
    for f in BASE:
        x = feats[f]
        cache[(f, "id")] = np.nan_to_num(x, nan=0.0).astype(np.float32)
        for u in UNARY[1:]:
            cache[(f, u)] = unary_fn(u, x, dates, pair_idx)

    l1 = [(f"{f}|{u}", cache[(f, u)]) for f in BASE for u in UNARY]
    cands = [(nm, arr) for nm, arr in l1]
    for op in BINARY:
        for nm1, a1 in l1:
            for f2 in BASE:
                cands.append((f"({nm1}){op}{f2}", binary_fn(op, a1, cache[(f2, "id")])))
    for op in BINARY:
        for i in range(len(BASE)):
            for j in range(i + 1, len(BASE)):
                cands.append((f"{BASE[i]}{op}{BASE[j]}",
                              binary_fn(op, cache[(BASE[i], "id")], cache[(BASE[j], "id")])))
    if a.limit:
        cands = cands[:a.limit]
    print(f"[mining] family size {len(cands)} (pre-registered grammar), "
          f"rows {n_rows}, test days {int((fold_idx > 0).sum() and len(np.unique(dates[fold_idx > 0])))}")

    # graveyard proxies (dead price-volume families, in-universe incarnations)
    fast = FastBook(dates, pair_idx, fwd1, cost, rebal=5)
    # EQUIVALENCE GATE: the fast path must reproduce the gate's own book on
    # sample candidates before the family runs (no silent divergence).
    for nm, score in cands[:5] + cands[-3:]:
        raw = _positions_rank(dates, pair_idx, score, None, cost, 1.0, False, None, 5)
        g = _daily_pnl(dates, pair_idx, raw, fwd1, cost, "all")
        f = fast.daily(score).reindex(g.index)
        # all-NaN days: the gate emits NaN, the fast path omits them — the
        # agreed no-trade semantic is 0 contribution, so compare finite days
        m = g.notna().to_numpy()
        if not np.allclose(g.to_numpy()[m], f.to_numpy()[m], atol=1e-5):
            raise SystemExit(f"[mining] ABORT: fast-path divergence on {nm} "
                             f"(max diff {np.nanmax(np.abs(g.to_numpy()[m] - f.to_numpy()[m])):.2e})")
    print(f"[mining] fast path verified against fxexpert.gate on 8 candidates")

    proxy = {}
    mom_sig = np.where(np.nan_to_num(z["mom20"], nan=0.0) > 0, 1.0, -1.0).astype(np.float32)
    rsi_sig = np.zeros(n_rows, dtype=np.float32)
    rsi_sig[z["rsi_raw"] < 30] = 1.0
    rsi_sig[z["rsi_raw"] > 70] = -1.0
    for nm, sig in (("mom20_sign", mom_sig), ("rsi14_mr", rsi_sig)):
        proxy[nm] = fast.daily(sig).to_numpy()

    # evaluate the family
    test_days = np.sort(pd.unique(dates[fold_idx > 0]))
    day_pos = {d: i for i, d in enumerate(test_days)}
    K = len(cands)
    R = np.zeros((len(test_days), K), dtype=np.float32)
    results = []
    for k, (nm, score) in enumerate(cands):
        daily = fast.daily(score)
        dtest = daily[daily.index.isin(day_pos)]
        for d, v in dtest.items():
            R[day_pos[d], k] = v
        s = dtest.to_numpy()
        dts = dtest.index.to_numpy()
        fpf = [pf_of(s[(dts >= lo) & (dts <= hi)]) for lo, hi in folds]
        results.append({"name": nm, "pf": pf_of(s),
                        "mean_bps": round(float(s.mean() * 1e4), 3) if len(s) else 0.0,
                        "fold_pfs": [round(f, 4) if np.isfinite(f) else None for f in fpf],
                        "folds_positive": int(sum(1 for f in fpf if f > 1))})
        if (k + 1) % 500 == 0:
            print(f"[mining] {k + 1}/{K} evaluated ({time.time() - t0:.0f}s)")

    # joint White's Reality Check in PF space (the raised bar)
    rng = np.random.default_rng(a.seed)
    W = stationary_counts(len(test_days), a.block, rng, a.B) / len(test_days)
    mu = R.mean(axis=0, dtype=np.float64)
    Rc = R - mu
    Ppos, Pneg = np.maximum(Rc, 0.0), np.maximum(-Rc, 0.0)
    Sp, Sn = W @ Ppos, W @ Pneg
    with np.errstate(divide="ignore", invalid="ignore"):
        PF_null = np.where(Sn > 0, Sp / Sn, np.inf)
    # degenerate loss-free replicates: cap BOTH null and observed at PF_CAP so
    # np.quantile interpolation never sees inf (the smoke run's nan) and no
    # candidate beats the null via an inf artifact
    PF_null = np.minimum(PF_null, PF_CAP)
    pf_k = np.array([min(r["pf"], PF_CAP) if np.isfinite(r["pf"]) else PF_CAP
                     for r in results])
    pf_null_95 = float(np.quantile(PF_null.max(axis=1), 0.95))
    winner = int(pf_k.argmax())
    p_joint = float((PF_null.max(axis=1) >= pf_k[winner]).mean())
    print(f"[mining] WRC: null 95th-pct max PF {pf_null_95:.4f} | best family PF "
          f"{pf_k[winner]:.4f} ({cands[winner][0]}) joint p {p_joint:.4f}")

    # bar + graveyard similarity on survivors
    survivors = []
    for k, r in enumerate(results):
        if (pf_k[k] >= pf_null_95 and r["mean_bps"] > 0
                and r["folds_positive"] >= 2):
            series = R[:, k].astype(np.float64)
            corrs = {nm: round(float(abs(np.corrcoef(series, p)[0, 1])), 3)
                     for nm, p in proxy.items()
                     if np.std(series) > 0 and np.std(p) > 0}
            r["graveyard_corr"] = corrs
            if max(corrs.values(), default=0.0) <= GRAVEYARD_PROXY_CORR_MAX:
                survivors.append(r)

    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "pre_registration": Path(__file__).read_text().split('"""')[1][:2400],
        "substrate": {"panel": str(PANEL), "rows": n_rows,
                      "date_min": str(pd.Timestamp(int(udays[0]), unit='D').date()),
                      "date_max": str(pd.Timestamp(int(udays[-1]), unit='D').date()),
                      "folds": [[str(pd.Timestamp(lo, unit='D').date()),
                                 str(pd.Timestamp(hi, unit='D').date())] for lo, hi in folds]},
        "family": {"base": BASE, "unary": UNARY, "binary": BINARY,
                   "n_candidates": K},
        "bar": {"statistic": "White's Reality Check, PF space, joint family",
                "B": a.B, "block": a.block, "seed": a.seed,
                "pf_null_95": round(pf_null_95, 4),
                "best_family_pf": round(float(pf_k[winner]), 4),
                "best_family_name": cands[winner][0],
                "p_joint_winner": round(p_joint, 4),
                "coherence": "mean_bps>0 AND >=2/3 fold PF>1",
                "graveyard": "exogenous-only grammar (structural) + |corr|<=0.7 vs mom20_sign/rsi14_mr proxies"},
        "n_survivors": len(survivors),
        "survivors": survivors,
        "results": results,
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(f"[mining] survivors: {len(survivors)} | wrote {OUT} "
          f"({out['runtime_s']}s)")
    if not survivors:
        print("[mining] HONEST STATEMENT: no expression in the pre-registered "
              "exogenous family clears the deflated bar — the edge does not "
              "exist in this data at this frequency, at this family size.")


if __name__ == "__main__":
    main()
