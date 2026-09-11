#!/usr/bin/env python3
"""White's Reality Check for the fxexpert gate (deflated bar, #245 decision).

The gate's PF>=1.05 bar was evaluated 163 times on 3 fixed folds with no
multiple-testing correction, so the best-observed PF is inflated by selection.
White's Reality Check asks: under the null that no generation has true edge,
how likely is the observed max PF (or better) to arise by chance?

Implementation (population-max bootstrap, the shape of THIS sweep):
  - the "no edge" population = the leak-fixed (clean-era) generations, which
    all FAIL the bar (mean PF < 1.0) — they are the honest null.
  - bootstrap B resamples of that population; the p-value is the fraction of
    resampled maxima >= the observed max PF.

A generation survives the deflated bar only if p < alpha (default 0.05).

Usage: .venv/bin/python3 scripts/white_reality_check.py [--alpha 0.05]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HISTORY = Path("data/fx_expert/history.jsonl")


def load_pfs(clean_only=True):
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    out = []
    for r in rows:
        try:
            tag = int(r["tag"])
        except (KeyError, ValueError):
            continue
        if clean_only and tag < 36:  # g12-g35 = invalidated warm-start-leak era
            continue
        pf = r.get("pf")
        if pf is None or pf == float("inf"):
            continue
        out.append((tag, float(pf)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bootstrap", type=int, default=20000)
    a = ap.parse_args()

    if not HISTORY.exists():
        print("[wrc] history.jsonl not found")
        sys.exit(1)

    tagged = load_pfs()
    if not tagged:
        print("[wrc] no clean-era generations")
        sys.exit(1)

    pfs = np.array([pf for _, pf in tagged])
    obs_max = pfs.max()
    obs_tag = max(tagged, key=lambda x: x[1])[0]
    mean, sd = pfs.mean(), pfs.std(ddof=1)
    z = (obs_max - mean) / sd if sd > 0 else float("nan")

    rng = np.random.default_rng(a.seed)
    # White's Reality Check null: NO config has edge -> each config's true PF
    # is break-even (1.0) with the search's cross-sectional noise. Demean the
    # population to 1.0 so the observed max is judged against a "no edge" null
    # (the observed mean is itself a losing ~0.99, not the null).
    null = pfs - mean + 1.0
    n = len(null)
    maxima = np.empty(a.bootstrap)
    for b in range(a.bootstrap):
        maxima[b] = rng.choice(null, size=n, replace=True).max()
    p = float((maxima >= obs_max).mean())

    print(f"clean-era generations: {n} (tags g36+)")
    print(f"observed max PF: {obs_max:.4f} (tag g{obs_tag})")
    print(f"null population: mean PF {mean:.4f}, sd {sd:.4f}, z = {z:.2f}")
    print(f"White's Reality Check p-value: {p:.4f} ({a.bootstrap} bootstraps)")
    verdict = "SURVIVES" if p < a.alpha else "DOES NOT SURVIVE"
    print(f"deflated-bar verdict at alpha={a.alpha}: {verdict}")

    # what bar WOULD the best need to clear to survive at alpha?
    thr = float(np.quantile(maxima, 1 - a.alpha))
    print(f"survival threshold ({(1 - a.alpha)*100:.0f}th pct of null max): PF >= {thr:.4f}")


if __name__ == "__main__":
    main()
