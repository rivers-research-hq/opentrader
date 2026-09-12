#!/usr/bin/env python3
"""panel_v2_probe — did the new exogenous information actually arrive, and
does it carry cross-sectional signal?

Three questions, in order:
  1. coverage — is the block live? (v1's rate_diff/events_5d were 0.0%)
  2. information — cross-sectional Spearman IC vs the 10-day forward return,
     per walkforward fold (the same 3 folds the gate uses)
  3. tradability — the gate's own rank-book simulation on the raw feature as
     the score (no model): PF / bps-per-day net of the panel's cost model.

Read-only. Usage: .venv/bin/python3 scripts/panel_v2_probe.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402

OUT = REPO / "data" / "fx_expert"
WATCH = ["pv_carry", "pv_carry_z", "pv_carry_chg20", "pv_carry_xs", "pv_carry_mask",
         "pv_tot_diff", "pv_tot_chg20", "pv_tot_xs", "pv_tot_mask",
         "rate_diff", "rate_diff_chg20", "rate_mask", "events_5d",
         "carry", "carry_z", "carry_mask", "cot_z", "cot_mask",
         "fred_dgs2_z", "fred_dgs10_z", "fred_curve_z", "fred_real10_z"]


def folds_for(days):
    """The gate's walkforward folds (quarters 2-4 of the unique panel dates)."""
    udays = np.unique(days)
    n = len(udays)
    return [(udays[int(n * 0.25 * q)], udays[int(n * 0.25 * (q + 1)) - 1])
            for q in (1, 2, 3)]


def main():
    P = dict(np.load(OUT / "panel_v2.npz"))
    names = [str(x) for x in P["feature_names"]]
    X, day, pi = P["features"], P["date"], P["pair_idx"]
    fwd10, cost, vol20 = P["fwd10"], P["cost"], P["vol20"]
    folds = folds_for(day)

    print(f"panel_v2: {X.shape[0]} rows x {X.shape[1]} features, "
          f"{len(np.unique(pi))} pairs, folds {[(int(a), int(b)) for a, b in folds]}")
    print("\n== coverage (fraction of rows non-zero) ==")
    for f in WATCH:
        if f not in names:
            print(f"  {f:<16} MISSING")
            continue
        col = X[:, names.index(f)]
        print(f"  {f:<16} {float((col != 0).mean()):.3f}")

    # cross-sectional IC per fold: rank correlation of the feature against the
    # 10-day forward return WITHIN each date, averaged over dates.
    print("\n== cross-sectional IC vs fwd10 (mean over dates, by fold) ==")
    df = pd.DataFrame({"d": day, "p": pi, "fwd": fwd10})
    for f in ("pv_carry", "pv_carry_z", "pv_carry_chg20", "pv_tot_diff",
              "pv_tot_chg20", "rate_diff", "cot_z", "mom_20d", "fred_dgs2_z"):
        if f not in names:
            continue
        df["s"] = X[:, names.index(f)]
        ics = []
        for lo, hi in folds:
            sub = df[(df.d >= lo) & (df.d <= hi)]
            per_day = sub.groupby("d").apply(
                lambda g: g["s"].corr(g["fwd"], method="spearman")
                if g["s"].nunique() > 3 else np.nan)
            ics.append(float(per_day.mean(skipna=True)))
        print(f"  {f:<16} folds " + "  ".join(f"{x:+.4f}" for x in ics) +
              f"   mean {np.mean(ics):+.4f}")

    # tradability: gate's rank book on the raw feature as score (net of cost)
    print("\n== standalone rank-book simulation (gate's own path, net) ==")
    keep = ~(np.isnan(fwd10) | np.isnan(vol20) | (vol20 <= 0))
    for f in ("pv_carry", "pv_carry_z", "pv_tot_diff", "rate_diff", "cot_z"):
        if f not in names:
            continue
        score = np.nan_to_num(X[:, names.index(f)])
        raw = fxgate._positions_rank(day, pi, score, vol20, cost, lev=1.0,
                                     vol_target=False, cost_cap=None, rebal=5)
        m = fxgate._simulate(day, pi, raw, P["fwd1"], cost, denom="all")
        # per-fold PF
        pfs = []
        for lo, hi in folds:
            msk = (day >= lo) & (day <= hi)
            mf = fxgate._simulate(day[msk], pi[msk], raw[msk], P["fwd1"][msk],
                                  cost[msk], denom="all")
            pfs.append(mf["pf"])
        print(f"  {f:<16} PF {m['pf']}  {m['daily_mean_bps']:+.3f} bps/day  "
              f"Sharpe {m['sharpe']}  folds " +
              "  ".join(f"{p:.3f}" for p in pfs))

    print("\n(recorded g185 for scale: PF 1.2862, +1.096 bps/day, Sharpe 0.473)")


if __name__ == "__main__":
    main()