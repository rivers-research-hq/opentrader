#!/usr/bin/env python3
"""worlds — Stage 1 of the adversarial loop (protocol §5d): robustness
realities via date-block bootstrap.

The promotion question changes from "did the candidate survive ONE
walkforward" to "does its edge hold across N resampled worlds". Block-
bootstrap worlds are statistically honest — no learned generator, no
artifact risk (Stage 2 puts a learned generator behind acceptance tests;
this stage needs none):

  - Blocks of consecutive DATES are resampled (geometric block length,
    mean ~1 month) and ALL symbols move together — within-block
    cross-asset structure and volatility clustering are REAL; only the
    path ordering is perturbed.
  - Worlds are RE-DATED onto synthetic sequential timestamps so the gym's
    simulate()/Ctx run unchanged; COT/carry travel with each source date
    (the 3-day publication-lag logic stays consistent).
  - Per world: the candidate trades under the gym's uniform risk shape;
    OOS (last 40% of the world) stats are collected.
  - Verdict per candidate: OOS PF distribution across worlds, fraction of
    worlds with PF>1 and positive P&L, and the REAL path's percentile.
    Recommendation (human decides): robust if >=70% of worlds PF>1 AND the
    real path sits inside the 25th-90th percentile (not a lucky draw).

Usage:
  python3 scripts/worlds.py --worlds 1000 --block-mean 21 \
      --candidates c08_mr_fade_cot,c04_mr_fade_ma20,c01_mom_k5_pos
"""

import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))
from signal_gym import CAND_DIR, load_candidate, simulate, stats  # noqa: E402  (the gym IS the engine)

CANDLES = PROJECT / "data" / "signal_gym" / "candles.json"
EXOG = PROJECT / "data" / "exog_cache.json"
OUT = PROJECT / "data" / "agent_gym" / "worlds"


def build_world(dates, series, exog_ts, rng, block_mean):
    """One bootstrap world: re-dated block resample. Returns (series, dates, exog)."""
    n = len(dates)
    idx = []
    p = 1.0 / block_mean  # geometric block length: P(L=k) = (1-p)^(k-1) p
    while len(idx) < n:
        block = 1
        while block < n and rng.random() > p:
            block += 1
        start = rng.randint(0, n - block)
        idx.extend(range(start, start + block))
    idx = idx[:n]

    start_ts = dates[0]
    w_series = {sym: {} for sym in series}
    w_exog = {k: {} for k in exog_ts}
    for j, si in enumerate(idx):
        ts_new = start_ts + j * 86400
        d_old = dates[si]
        d_old_str = datetime.fromtimestamp(d_old, tz=timezone.utc).strftime("%Y-%m-%d")
        d_new = datetime.fromtimestamp(ts_new, tz=timezone.utc).strftime("%Y-%m-%d")
        for sym, s in series.items():
            px = s.get(d_old)
            if px:
                w_series[sym][ts_new] = px
        for k, m in exog_ts.items():
            v = m.get(d_old_str)
            if v is not None:
                w_exog[k][d_new] = v  # gym Ctx.exog compares ISO date STRINGS
    return w_series, [start_ts + j * 86400 for j in range(n)], w_exog


def main():
    argv = sys.argv
    n_worlds = int(argv[argv.index("--worlds") + 1]) if "--worlds" in argv else 1000
    block_mean = int(argv[argv.index("--block-mean") + 1]) if "--block-mean" in argv else 21
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 20260901
    cand_names = (argv[argv.index("--candidates") + 1].split(",")
                  if "--candidates" in argv
                  else ["c08_mr_fade_cot", "c04_mr_fade_ma20", "c01_mom_k5_pos"])

    raw = json.load(open(CANDLES))
    series = {s: {int(ts): tuple(px) for ts, px in d.items()} for s, d in raw.items()}
    dates = sorted({ts for s in series.values() for ts in s})
    symbols = list(series)
    is_end = int(len(dates) * 0.6)
    exog_raw = json.load(open(EXOG)) if EXOG.exists() else {}
    exog_ts = {k: dict(v) for k, v in exog_raw.items()
               if k != "meta" and isinstance(v, dict)}  # ISO date-string keyed

    print(f"worlds — {n_worlds} realities, block mean {block_mean}d, "
          f"{len(symbols)} majors x {len(dates)} bars, seed {seed}")
    print(f"candidates: {cand_names}\n")

    out = {"meta": {"worlds": n_worlds, "block_mean": block_mean, "seed": seed,
                    "window": [dates[0], dates[-1]]}, "candidates": {}}
    for name in cand_names:
        cand = load_candidate(CAND_DIR / f"{name}.py")
        # real path
        trades_real, _ = simulate(cand, series, dates, symbols, is_end, exog=exog_raw)
        real_oos = stats(trades_real["oos"])
        real_pf = real_oos["pf"] if real_oos else None

        rng = random.Random(seed)
        pfs, pnls, ns = [], [], []
        for w in range(n_worlds):
            w_series, w_dates, w_exog = build_world(dates, series, exog_ts, rng, block_mean)
            trades, _eq = simulate(cand, w_series, w_dates, symbols, is_end, exog=w_exog)
            s = stats(trades["oos"])
            if s and s["pf"] is not None:
                pfs.append(min(s["pf"], 20.0))  # cap inf for distribution stats
                pnls.append(s["pl"])
                ns.append(s["n"])
        pct = (sum(1 for p in pfs if p < (real_pf or 0)) + 0.5 * sum(1 for p in pfs if p == (real_pf or 0))) / max(1, len(pfs)) * 100
        res = {
            "real_oos": real_oos,
            "worlds_pf_mean": round(statistics.mean(pfs), 3) if pfs else None,
            "worlds_pf_p5": round(sorted(pfs)[int(0.05 * len(pfs))], 3) if pfs else None,
            "worlds_pf_median": round(statistics.median(pfs), 3) if pfs else None,
            "worlds_pf_pct_gt1": round(100 * sum(1 for p in pfs if p > 1) / len(pfs), 1) if pfs else None,
            "worlds_pnl_pct_pos": round(100 * sum(1 for p in pnls if p > 0) / len(pnls), 1) if pnls else None,
            "worlds_mean_n": round(statistics.mean(ns), 1) if ns else None,
            "real_pf_percentile": round(pct, 1),
        }
        out["candidates"][name] = res
        print(f"  {cand.NAME:<24} worlds OOS PF mean {res['worlds_pf_mean']} "
              f"p5 {res['worlds_pf_p5']} med {res['worlds_pf_median']} | "
              f"PF>1 in {res['worlds_pf_pct_gt1']}% | P&L>0 in {res['worlds_pnl_pct_pos']}% | "
              f"real path {real_pf and round(real_pf, 2)} @ p{res['real_pf_percentile']} "
              f"(n/world {res['worlds_mean_n']})")

    out_dir = OUT / f"w{n_worlds}-b{block_mean}-s{seed}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "worlds.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"\nresults: {out_dir / 'worlds.json'}")


if __name__ == "__main__":
    main()
