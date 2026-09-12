#!/usr/bin/env python3
"""gate_stat_study2 — ensemble done right, and year-to-year persistence.

Study 1 left two questions open and one methodological bug:
  - the ensemble was simulated on a (date, pair) subset, which re-derives the
    weekly rebalancing periods and the per-pair position changes, so both the
    ensemble AND the g185 control were different books than their real ones.
    Here everything is simulated on ONE row set (g185's full OOS rows), with
    missing generation scores excluded per-row from the mean.
  - does any cross-generation difference persist? Study 1 found the first/second
    half correlation negative; here it is measured per calendar year.

Read-only. Usage: .venv/bin/python3 scripts/gate_stat_study2.py
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
HISTORY = OUT / "history.jsonl"
REF = "185"          # reference row set = the newest 58-pair generation


def era_gens(n_pairs=58):
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    gens = []
    for r in rows:
        tag = str(r.get("tag", ""))
        if not tag.isdigit() or int(tag) < 36:
            continue
        p = OUT / f"preds_g{tag}.npz"
        if p.exists() and np.unique(np.load(p)["pair_idx"]).size == n_pairs:
            gens.append(tag)
    return gens


def stat_block(daily):
    mu = float(daily.mean())
    sd = float(daily.std(ddof=1))
    n = len(daily)
    g, l = daily[daily > 0].sum(), -daily[daily < 0].sum()
    return {"pf": float(g / l) if l > 0 else float("inf"),
            "mu_bps": mu * 1e4, "sd_bps": sd * 1e4,
            "t": mu / (sd / np.sqrt(n)) if sd > 0 else 0.0}


def main():
    base = np.load(OUT / f"preds_g{REF}.npz")
    d, pi = base["date"], base["pair_idx"]
    idx = pd.MultiIndex.from_arrays([d, pi])
    cost, fwd1, vol20 = base["cost"], base["fwd1"], base["vol20"]
    print(f"[s2] reference row set g{REF}: {len(d)} rows, "
          f"{len(np.unique(d))} days, {len(np.unique(pi))} pairs")

    # ---- scores of every generation reindexed onto the reference rows ----
    gens = era_gens()
    cols = {}
    for t in gens:
        P = np.load(OUT / f"preds_g{t}.npz")
        s = pd.Series(P["score"], index=pd.MultiIndex.from_arrays(
            [P["date"], P["pair_idx"]]))
        s = s[~s.index.duplicated()]
        cols[t] = s.reindex(idx)
    S = pd.DataFrame(cols, index=idx)
    cover = S.notna().mean()
    print(f"[s2] {len(gens)} generations reindexed; median row coverage "
          f"{cover.median():.3f} (min {cover.min():.3f} g{cover.idxmin()})")

    Z = S.groupby(level=0).transform(lambda x: (x - x.mean()) / (x.std() + 1e-12))

    def book(score, rule="rank", **kw):
        raw = fxgate._positions_rank(d, pi, np.nan_to_num(score.to_numpy()),
                                     vol20, cost, lev=1.0, rebal=5, **kw)
        return fxgate._daily_pnl(d, pi, raw, fwd1, cost, "all")

    print("\n== ensembles on the SAME rows / same rebalancing ==")
    print(f"  {'score':<26}{'PF':>7}{'mu bps':>9}{'sd bps':>8}{'t':>7}{'sharpe':>8}")
    variants = {
        f"single g{REF}": S[REF],
        "mean z (all 101)": Z.mean(axis=1),
        "median z (all 101)": Z.median(axis=1),
        "mean z (v2 round only)": Z[[c for c in Z.columns if c in
                                     ("201", "202", "203", "204", "205", "206",
                                      "207", "208")]].mean(axis=1),
        "mean z (g163-g188 round)": Z[[c for c in Z.columns
                                       if c.isdigit() and 163 <= int(c) <= 188]].mean(axis=1),
    }
    out = {}
    for label, sc in variants.items():
        ds = book(sc)
        st = stat_block(ds)
        out[label] = st
        print(f"  {label:<26}{st['pf']:>7.4f}{st['mu_bps']:>+9.3f}"
              f"{st['sd_bps']:>8.2f}{st['t']:>+7.2f}"
              f"{st['t'] / np.sqrt(len(ds)) * np.sqrt(252):>+8.3f}")

    # ---- year-to-year persistence of the per-generation statistic ----
    print("\n== persistence of the per-generation t across calendar years ==")
    daily = {t: fxgate.daily_pnl_series(t) for t in gens}
    df = pd.DataFrame(daily)
    yrs = pd.DatetimeIndex(pd.to_datetime(df.index, unit="D")).year
    Y = {}
    for y in sorted(set(yrs)):
        m = yrs == y
        if m.sum() < 120:
            continue
        Y[y] = {t: stat_block(df[t][m])["t"] for t in df.columns}
    Yd = pd.DataFrame(Y)
    print(f"  years: {list(Yd.columns)}")
    cm = Yd.corr(method="spearman")
    tri = cm.where(np.triu(np.ones(cm.shape), 1).astype(bool)).stack()
    print(f"  mean pairwise year-to-year Spearman: {tri.mean():+.3f} "
          f"(n={len(tri)} pairs)")
    print(f"  per-year top-5 overlap with the full-sample top-5: ", end="")
    full_top = set(df.apply(lambda c: stat_block(c)["t"]).sort_values(
        ascending=False).head(5).index)
    ov = []
    for y in Yd.columns:
        top = set(Yd[y].sort_values(ascending=False).head(5).index)
        ov.append(len(top & full_top))
    print(f"{ov} (of 5, per year {list(Yd.columns)})")


if __name__ == "__main__":
    main()