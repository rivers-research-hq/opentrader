#!/usr/bin/env python3
"""gate_stat_study — which gate statistic is reliable, and what moves it?

The 2026-09-12 finding (V-PANEL2): PF and IC disagree (corr 0.168) and PF
spans 0.76-1.29 within an IC quartile. Before choosing a replacement bar this
study measures, on the real 58-pair population:

  1. split-half reliability of each statistic (even/odd weeks): does the
     statistic measure a persistent model property or sampling noise?
  2. how each statistic ranks two models with the same signal quality
     (g185 IC 0.0298 vs g221 IC 0.0291);
  3. two candidate levers, tested on the same scores:
       - ENSEMBLE: the fixed equal-weight average of all era-matched
         generations' cross-sectional z-scores (one evaluation, no selection);
       - VOL-SCALED: the rank book weighted by 1/pair-vol (risk parity) —
         cuts book vol without touching the cross-sectional signal.
     A lever only matters if it raises t = mean/SE of the net daily return.

Read-only. Usage: .venv/bin/python3 scripts/gate_stat_study.py
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


def era_gens(n_pairs=58):
    """Clean-era generations whose stored predictions are on the n_pairs panel.
    The 16-pair (g36-g99) and 58-pair (g100+) universes are different books;
    mixing them makes the ensemble row sets non-comparable."""
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    gens = []
    for r in rows:
        tag = str(r.get("tag", ""))
        if not tag.isdigit() or int(tag) < 36:
            continue
        p = OUT / f"preds_g{tag}.npz"
        if not p.exists():
            continue
        if np.unique(np.load(p)["pair_idx"]).size != n_pairs:
            continue
        gens.append(tag)
    return gens


def stats(daily):
    mu = float(daily.mean())
    sd = float(daily.std(ddof=1))
    n = len(daily)
    t = mu / (sd / np.sqrt(n)) if sd > 0 else 0.0
    g = daily[daily > 0].sum()
    l = -daily[daily < 0].sum()
    return {"mu_bps": mu * 1e4, "sd_bps": sd * 1e4, "t": t,
            "pf": float(g / l) if l > 0 else float("inf"),
            "sharpe": t / np.sqrt(n) * np.sqrt(252)}


def half_agreement(daily, mask, stat="t"):
    """Spearman across generations between the statistic on the two halves."""
    a = pd.Series({k: stats(v[mask])[stat] for k, v in daily.items()})
    b = pd.Series({k: stats(v[~mask])[stat] for k, v in daily.items()})
    rho = float(a.corr(b, method="spearman"))
    sb = 2 * rho / (1 + rho) if rho > -1 else float("nan")
    return rho, sb


def ic_of(tag, mask=None):
    """Pooled Spearman IC (the gate's definition) on the stored OOS rows."""
    P = np.load(OUT / f"preds_g{tag}.npz")
    lab = "fwdh" if "fwdh" in P.files else ("fwd10" if "fwd10" in P.files else "fwd5")
    s, f = P["score"], P[lab]
    if mask is not None:
        d = P["date"]
        cut = np.median(d)
        m = (d <= cut) if mask == 0 else (d > cut)
        s, f = s[m], f[m]
    ok = np.isfinite(s) & np.isfinite(f)
    if ok.sum() < 100:
        return float("nan")
    return float(np.corrcoef(pd.Series(s[ok]).rank(), pd.Series(f[ok]).rank())[0, 1])


def main():
    gens = era_gens()
    print(f"[study] {len(gens)} clean-era generations with stored predictions")
    hist = {str(json.loads(l)["tag"]): json.loads(l)
            for l in HISTORY.read_text().splitlines() if l.strip()}

    series, ic = {}, {}
    for t in gens:
        series[t] = fxgate.daily_pnl_series(t)
        h = hist.get(t, {})
        ic[t] = h.get("ic_mean")

    # align on the common date index
    df = pd.DataFrame(series).dropna()
    print(f"[study] common window: {len(df)} days x {df.shape[1]} generations")
    daily = {c: df[c] for c in df.columns}

    # --- 1. statistic levels + agreement with IC -------------------------
    S = pd.DataFrame({t: stats(daily[t]) for t in df.columns}).T
    S["ic"] = pd.Series(ic)
    S["pf_hist"] = pd.Series({t: hist.get(t, {}).get("pf") for t in df.columns})
    print("\n== per-generation statistics (head by t) ==")
    print(S.sort_values("t", ascending=False).head(6).round(4).to_string())
    print("\n== agreement between statistics (Spearman across generations) ==")
    cols = ["t", "pf", "sharpe", "mu_bps", "ic"]
    print(S[cols].corr(method="spearman").round(3).to_string())

    print("\n== the same-signal pair (g185 vs g221/g222) ==")
    for t in ("185", "221", "222", "151", "211", "201"):
        if t in S.index:
            r = S.loc[t]
            print(f"  g{t}: IC {r['ic']:.4f} | t {r['t']:+.2f} | PF {r['pf']:.4f} "
                  f"| mu {r['mu_bps']:+.3f}bps | sd {r['sd_bps']:.2f}bps")

    # --- 2. split-half reliability ---------------------------------------
    print("\n== split-half reliability (Spearman across generations) ==")
    days_arr = df.index.to_numpy()
    weeks = pd.Series(days_arr).rank(method="dense").astype(int).to_numpy() // 5
    masks = {"even/odd weeks": (weeks % 2 == 0),
             "first/second half": days_arr > np.median(days_arr)}
    for name, mask in masks.items():
        rho, sb = half_agreement(daily, mask, "t")
        print(f"  P&L t   {name:<20} rho {rho:+.3f}  Spearman-Brown {sb:+.3f}")
        ica = pd.Series({t: ic_of(t, 0) for t in df.columns})
        icb = pd.Series({t: ic_of(t, 1) for t in df.columns})
        rho_i = float(ica.corr(icb, method="spearman"))
        sb_i = 2 * rho_i / (1 + rho_i) if rho_i > -1 else float("nan")
        print(f"  IC      {name:<20} rho {rho_i:+.3f}  Spearman-Brown {sb_i:+.3f}")
        pfa = pd.Series({t: stats(daily[t][mask])["pf"] for t in df.columns})
        pfb = pd.Series({t: stats(daily[t][~mask])["pf"] for t in df.columns})
        rho_p = float(pfa.corr(pfb, method="spearman"))
        sb_p = 2 * rho_p / (1 + rho_p) if rho_p > -1 else float("nan")
        print(f"  PF      {name:<20} rho {rho_p:+.3f}  Spearman-Brown {sb_p:+.3f}")
    # per-fold agreement of PF vs t
    days = df.index.to_numpy()
    q = np.quantile(days, [0, .25, .5, .75, 1.0])
    folds = [(q[1], q[2]), (q[2], q[3]), (q[3], q[4])]
    for stat in ("t", "pf"):
        vals = []
        for lo, hi in folds:
            vals.append({t: stats(daily[t][(daily[t].index >= lo) & (daily[t].index <= hi)])[stat]
                         for t in df.columns})
        V = pd.DataFrame(vals)
        rho = V.corr(method="spearman").to_numpy()
        print(f"  {stat:<3} fold-to-fold Spearman: "
              f"{rho[0,1]:+.3f} {rho[0,2]:+.3f} {rho[1,2]:+.3f}")

    # --- 3a. ensemble of all era-matched generations ---------------------
    print("\n== ensemble (equal-weight mean of cross-sectional z-scores) ==")
    frames = []
    for t in df.columns:
        P = np.load(OUT / f"preds_g{t}.npz")
        frames.append(pd.Series(P["score"], name=t, index=pd.MultiIndex.from_arrays(
            [P["date"], P["pair_idx"]])))
    S = pd.concat(frames, axis=1)
    common = S.dropna()          # rows every included generation produced
    print(f"  {len(frames)} generations; common OOS rows {len(common)} of "
          f"{len(S)} (panel grows over time — intersection keeps it comparable)")
    z = common.groupby(level=0).transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-12))
    ens = z.mean(axis=1).to_numpy()

    base = np.load(OUT / "preds_g185.npz")
    B = pd.DataFrame({"d": base["date"], "p": base["pair_idx"],
                      "fwd1": base["fwd1"], "cost": base["cost"],
                      "vol20": base["vol20"]},
                     index=pd.MultiIndex.from_arrays([base["date"], base["pair_idx"]]))
    B = B.loc[common.index]
    d, pi = B["d"].to_numpy(), B["p"].to_numpy()
    cost, fwd1, vol20 = B["cost"].to_numpy(), B["fwd1"].to_numpy(), B["vol20"].to_numpy()
    base_sc = pd.Series(base["score"], index=pd.MultiIndex.from_arrays(
        [base["date"], base["pair_idx"]])).loc[common.index].to_numpy()
    print(f"  ensemble of {len(frames)} generations on {len(d)} aligned rows")

    print(f"\n  {'score':<22}{'rule':<15}{'PF':>7}{'mu bps':>9}{'sd bps':>8}"
          f"{'t':>7}{'sharpe':>8}")
    for label, sc in (("ensemble(all)", ens), ("best single g185", base_sc)):
        for rulename, kwargs in (("rank", {}), ("rank+volscale", {"vol_target": True})):
            raw = fxgate._positions_rank(d, pi, sc, vol20, cost, lev=1.0, rebal=5,
                                         **kwargs)
            ds = fxgate._daily_pnl(d, pi, raw, fwd1, cost, "all")
            st = stats(ds)
            print(f"  {label:<22}{rulename:<15}{st['pf']:>7.4f}"
                  f"{st['mu_bps']:>+9.3f}{st['sd_bps']:>8.2f}"
                  f"{st['t']:>+7.2f}{st['sharpe']:>+8.3f}")


if __name__ == "__main__":
    main()