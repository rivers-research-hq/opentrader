#!/usr/bin/env python3
"""White's Reality Check / Hansen SPA for the fxexpert search (deflated bar, #245).

The gate's PF>=1.05 bar was evaluated once per generation on 3 fixed OOS folds
with no multiple-testing correction, so the best-observed PF is inflated by
selection. #245 (human, 2026-09-11) decided the admissible correction is
White's Reality Check; this script is the return-series implementation.

Modes
-----
returns (default) — the admissible deflation. For every clean-era generation
  recompute the gate's own daily OOS P&L series (fxexpert.gate.daily_pnl_series,
  the same _simulate path the gate scored), then run a stationary bootstrap
  (Politis-Romano) over TIME PERIODS, resampling the same day-blocks for every
  generation jointly so cross-generation dependence (warm-start chains, shared
  folds, shared universe) is preserved.

  Two statistics, same resampling — these are the deflated bar (#245):
    mean — textbook White RC on the daily mean return:
             V_k = sqrt(T) * mean_t(r_kt);  V = max_k V_k
             Z*_kb = sqrt(T) * (mean over resampled days - mean_t r_kt)
             p_RC  = P(max_k Z*_kb >= V)
    pf   — the gate metric itself. Under the null that no generation has edge,
           each series is recentered to zero mean return (PF ~ 1) and the
           bootstrap distribution of max_k PF is compared with the observed
           best PF. Directly answers "is 1.2862 beyond a no-edge search".

  A studentized (Hansen SPA-style) variant is reported as a diagnostic only:
  tests/test_wrc_calibration.py measures it as liberal on a zero-edge null
  (rejection 0.13-0.20 at alpha=0.10), while the two statistics above calibrate
  at alpha (RC 0.050 at alpha=0.05; PF 0.11 at alpha=0.10). The verdict rests
  on RC/PF, not on the studentized diagnostic.

pf-population — the legacy population-max bootstrap over recorded PF values.
  Kept for provenance only: it resamples the PF scores cross-sectionally, so
  the observed max is always a member of the null population and p is
  degenerate (documented in docs/health/hardening-backlog-2026-09-11.md item 1).

Usage: .venv/bin/python3 scripts/white_reality_check.py [--mode returns]
       [--era match|all|16|58] [--block 20] [--bootstrap 20000] [--alpha 0.05]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from fxexpert.gate import OUT_DIR, daily_pnl_series  # noqa: E402

HISTORY = OUT_DIR / "history.jsonl"
OUT_JSON = OUT_DIR / "wrc_return_series.json"


def load_history(clean_from=36):
    """Clean-era generations that have both preds and train artifacts."""
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    out = []
    for r in rows:
        tag = str(r["tag"])
        try:
            num = int(tag)
        except ValueError:
            num = None
        if clean_from and (num is None or num < clean_from):
            continue  # g12-g35 = invalidated warm-start-leak era
        if (OUT_DIR / f"preds_g{tag}.npz").exists() and \
           (OUT_DIR / f"train_g{tag}.json").exists():
            out.append({"tag": tag, "pf": r.get("pf"), "hp": r.get("hp"),
                        "ts": r.get("ts")})
    return out


def universe_size(tag):
    return int(np.unique(np.load(OUT_DIR / f"preds_g{tag}.npz")["pair_idx"]).size)


def build_frame(gens, verbose=True):
    """T x K matrix of daily OOS P&L, one column per generation, aligned on
    the dates every generation shares."""
    cols = {}
    for g in gens:
        cols[g["tag"]] = daily_pnl_series(g["tag"])
    df = pd.DataFrame(cols)
    n0, n1 = len(df), len(df.dropna())
    if verbose and n1 < n0:
        print(f"  alignment: {n0} union days -> {n1} common days "
              f"({n0 - n1} dropped, not shared by all generations)")
    return df.dropna()


def stationary_counts(T, L, rng, B):
    """(B, T) resample counts for a stationary bootstrap with mean block
    length L (Politis-Romano 1994): block starts geometric, wrap-around."""
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


def pf_of(series):
    g = series[series > 0].sum()
    l = -series[series < 0].sum()
    return float(g / l) if l > 0 else float("inf")


def run_bootstrap(R, block, B, rng, alpha):
    """Joint stationary-block bootstrap of the (T, K) daily-P&L matrix.
    Returns both statistics' observed values and p-values."""
    T, K = R.shape
    W = stationary_counts(T, block, rng, B) / T     # (B, T) resample weights
    mu = R.mean(axis=0)                              # (K,)
    M = W @ R                                        # (B, K) resampled means
    Z = np.sqrt(T) * (M - mu)                        # centered, (B, K)

    V_k = np.sqrt(T) * mu
    V = float(V_k.max())
    win = int(V_k.argmax())
    omega = Z.std(axis=0, ddof=1)
    omega = np.where(omega > 0, omega, np.inf)
    S = float((V_k / omega).max())
    g_rc = np.maximum(0.0, V_k)                      # Hansen recentering
    p_rc = float((Z.max(axis=1) >= V).mean())
    p_spa_stud = float(((Z / omega).max(axis=1) >= S).mean())
    p_spa_cons = float((((Z - g_rc) / omega).max(axis=1) >= S).mean())
    p_win_mean = float((Z[:, win] >= V_k[win]).mean())

    # PF-space null: recenter each series to zero mean return (no-edge),
    # resample the same blocks, take the max PF per replicate.
    Rc = R - mu
    Ppos, Pneg = np.maximum(Rc, 0.0), np.maximum(-Rc, 0.0)
    Sp, Sn = W @ Ppos, W @ Pneg
    with np.errstate(divide="ignore", invalid="ignore"):
        PF_null = np.where(Sn > 0, Sp / Sn, np.inf)
    pf_k = np.array([pf_of(R[:, k]) for k in range(K)])
    pf_win = float(pf_k.max())
    k_pf = int(pf_k.argmax())
    p_pf = float((PF_null.max(axis=1) >= pf_win).mean())
    p_pf_win = float((PF_null[:, k_pf] >= pf_win).mean())
    pf_null_q = float(np.quantile(PF_null.max(axis=1), 1 - alpha))
    mean_thr = float(np.quantile(Z.max(axis=1), 1 - alpha) / np.sqrt(T))

    return {
        "T": int(T), "K": int(K), "block": block, "bootstrap": B,
        "winner_mean_stat": win, "V": V,
        "p_rc_mean": p_rc, "p_winner_mean": p_win_mean,
        "p_spa_studentized_diagnostic": p_spa_stud,
        "p_spa_consistent_diagnostic": p_spa_cons,
        "mean_daily_bps_winner": float(mu[win] * 1e4),
        "mean_daily_bps_threshold": float(mean_thr * 1e4),
        "pf_winner": pf_win, "pf_winner_tag_idx": k_pf,
        "p_pf": p_pf, "p_pf_winner": p_pf_win,
        "pf_null_alpha_quantile": pf_null_q,
        "pf_null_median": float(np.median(PF_null.max(axis=1))),
        "tags": None,  # filled by caller
    }, {"V_k": V_k, "pf_k": pf_k, "mu": mu, "Z": Z, "PF_null": PF_null}


def report_era(name, gens, block, B, alpha, seed, sens_blocks=(), named=()):
    print(f"\n=== era '{name}': {len(gens)} generations, "
          f"block={block}, B={B} ===")
    df = build_frame(gens)
    tags = list(df.columns)
    R = df.to_numpy(dtype=np.float64)
    rng = np.random.default_rng(seed)
    res, per = run_bootstrap(R, block, B, rng, alpha)
    res["tags"] = tags

    # sanity: series-derived PF must match the recorded gate PF. Gens whose
    # recorded value predates a gate-code change are re-scored consistently
    # (the search's stored preds + hp are the evidence; see the disclosure).
    rec = {g["tag"]: g["pf"] for g in gens}
    stale = [(t, rec[t], round(per["pf_k"][i], 4))
             for i, t in enumerate(tags)
             if rec.get(t) is not None and abs(per["pf_k"][i] - rec[t]) > 0.01]
    res["recorded_pf_stale"] = [{"tag": t, "recorded": r, "recomputed": c}
                                for t, r, c in stale]
    if stale:
        print(f"  noted: {len(stale)}/{len(tags)} recorded history PFs differ "
              f"from the current-code recompute (tags "
              f"g{stale[0][0]}..g{stale[-1][0]}); the search's recorded rows "
              f"predate the thr_cont position fix. Deflation uses the "
              f"recomputed series for every generation.")
    else:
        print(f"  sanity: all {len(tags)} recomputed PFs match the recorded "
              f"gate PFs")

    i_mean, i_pf = res["winner_mean_stat"], res["pf_winner_tag_idx"]
    print(f"  observed max PF      : {res['pf_winner']:.4f} (g{tags[i_pf]})")
    print(f"  observed V (mean-stat): {res['V']:.4f} (g{tags[i_mean]}, "
          f"{res['mean_daily_bps_winner']:.3f} bps/day)")
    print(f"  White RC  p(mean)    : {res['p_rc_mean']:.4f}   "
          f"-> {'SURVIVES' if res['p_rc_mean'] < alpha else 'DOES NOT SURVIVE'}")
    print(f"  White RC  p(PF)      : {res['p_pf']:.4f}   "
          f"-> {'SURVIVES' if res['p_pf'] < alpha else 'DOES NOT SURVIVE'}"
          f"   (null max-PF median {res['pf_null_median']:.4f}, "
          f"{100*(1-alpha):.0f}th pct {res['pf_null_alpha_quantile']:.4f})")
    print(f"  [diagnostic, liberal] studentized p: {res['p_spa_studentized_diagnostic']:.4f} "
          f"(consistent variant {res['p_spa_consistent_diagnostic']:.4f})")
    print(f"  marginal (uncorrected) p of the winner: mean {res['p_winner_mean']:.4f}, "
          f"PF {res['p_pf_winner']:.4f}")
    print(f"  to clear alpha={alpha} on the mean bar: >= "
          f"{res['mean_daily_bps_threshold']:.3f} bps/day "
          f"(winner has {res['mean_daily_bps_winner']:.3f})")

    for L in sens_blocks:
        if L == block:
            continue
        r2, _ = run_bootstrap(R, L, B, np.random.default_rng(seed), alpha)
        print(f"  block {L:>2}d: p_mean(RC) {r2['p_rc_mean']:.4f}  "
              f"p_PF {r2['p_pf']:.4f}")
        res.setdefault("block_sensitivity", {})[str(L)] = {
            "p_rc_mean": r2["p_rc_mean"], "p_pf": r2["p_pf"],
            "pf_null_alpha_quantile": r2["pf_null_alpha_quantile"]}

    top = sorted(zip(tags, per["pf_k"], per["mu"] * 1e4),
                 key=lambda x: -x[1])[:5]
    print("  top-5 by PF: " + " | ".join(
        f"g{t} PF {pf:.4f} {m:.3f}bps" for t, pf, m in top))
    if named:
        report_tags(res, per, tags, named, alpha)
    return res


def report_tags(res, per, tags, wanted, alpha):
    """Marginal (uncorrected) readout for named generations: the per-model
    analogue of the deflated test, for re-judging specific registrations."""
    idx = {t: i for i, t in enumerate(tags)}
    print(f"  named generations (marginal p = single-model bootstrap):")
    out = {}
    for w in wanted:
        if w not in idx:
            print(f"    g{w}: not in this population")
            continue
        i = idx[w]
        p_mean = float((per["Z"][:, i] >= per["V_k"][i]).mean())
        p_pf = float((per["PF_null"][:, i] >= per["pf_k"][i]).mean())
        print(f"    g{w}: PF {per['pf_k'][i]:.4f}, {per['mu'][i]*1e4:.3f} bps/day, "
              f"marginal p(mean) {p_mean:.4f}, p(PF) {p_pf:.4f}")
        out[w] = {"pf": float(per["pf_k"][i]),
                  "mean_daily_bps": float(per["mu"][i] * 1e4),
                  "p_mean_marginal": p_mean, "p_pf_marginal": p_pf}
    res["named_generations"] = out


def mode_pf_population(alpha, B, seed):
    """Legacy (degenerate) population-max bootstrap over recorded PFs."""
    gens = load_history()
    pfs = np.array([g["pf"] for g in gens if g["pf"] is not None
                    and np.isfinite(g["pf"])])
    tags = [g["tag"] for g in gens if g["pf"] is not None and np.isfinite(g["pf"])]
    obs = pfs.max()
    mean = pfs.mean()
    centered = pfs - mean
    rng = np.random.default_rng(seed)
    maxima = np.array([rng.choice(centered, size=len(centered), replace=True).max()
                       for _ in range(B)])
    p = float((maxima >= obs - mean).mean())
    print(f"[pf-population, DEGENERATE] n={len(pfs)} max PF {obs:.4f} "
          f"(g{tags[int(pfs.argmax())]}) mean {mean:.4f} p={p:.4f}")
    print("  NOTE: cross-sectional PF resampling puts the observed max inside "
          "the null -> p is not a valid data-snooping correction. Use --mode "
          "returns.")
    return {"mode": "pf-population", "n": len(pfs), "max_pf": float(obs),
            "mean_pf": float(mean), "p": p}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["returns", "pf-population"],
                    default="returns")
    ap.add_argument("--era", choices=["match", "all", "16", "58"], default="match",
                    help="population: 'match' = same universe size as the best "
                         "generation (the search that produced it); 'all' = "
                         "every clean-era generation")
    ap.add_argument("--block", type=int, default=20,
                    help="mean stationary-bootstrap block length, trading days")
    ap.add_argument("--bootstrap", type=int, default=20000)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sens", default="5,10,20,40,60",
                    help="block lengths for the sensitivity table")
    ap.add_argument("--tags", default="185,151,137,138",
                    help="generations for the marginal (uncorrected) readout")
    a = ap.parse_args()
    named = tuple(x.strip() for x in a.tags.split(",") if x.strip())

    if a.mode == "pf-population":
        res = mode_pf_population(a.alpha, a.bootstrap, a.seed)
        print(json.dumps(res, indent=1))
        return

    gens = load_history()
    if not gens:
        print("[wrc] no clean-era generations with artifacts")
        sys.exit(1)
    best = max(gens, key=lambda g: g["pf"] if g["pf"] is not None else -1)
    best_era = universe_size(best["tag"])
    for g in gens:
        g["npairs"] = universe_size(g["tag"])
    print(f"[wrc] clean-era generations: {len(gens)} "
          f"(eras: {sorted(set(g['npairs'] for g in gens))} pairs); "
          f"best recorded PF g{best['tag']} {best['pf']} on {best_era}-pair era")

    sens = [int(x) for x in a.sens.split(",") if x.strip()]
    out = {"mode": "returns", "alpha": a.alpha, "block": a.block,
           "bootstrap": a.bootstrap, "seed": a.seed,
           "best_recorded": {"tag": best["tag"], "pf": best["pf"],
                             "era_pairs": best_era},
           "populations": {}}

    eras = []
    if a.era == "match":
        eras.append(("match", [g for g in gens if g["npairs"] == best_era],
                     sens))
        eras.append(("all", gens, ()))
    elif a.era == "all":
        eras.append(("all", gens, sens))
    else:
        n = int(a.era)
        eras.append((f"{n}pairs", [g for g in gens if g["npairs"] == n], sens))

    for name, pop, sb in eras:
        if not pop:
            continue
        out["populations"][name] = report_era(
            name, pop, a.block, a.bootstrap, a.alpha, a.seed, sb, named)

    OUT_JSON.write_text(json.dumps(out, indent=1))
    print(f"\n[wrc] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()