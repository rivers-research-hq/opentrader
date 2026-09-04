#!/usr/bin/env python3
"""Seed the MoT router state with the tournament's VERIFIED evidence.

The harness reads live_router_state.json = {"track": {regime: {expert:
{sum, n}}}, "weights": {...}} (monitoring-only attribution). Today it starts
empty — every expert must earn weight from live trades, which at 0 fills
means the router never leaves the rule floor.

This seeder writes the TOURNAMENT evidence as the INITIAL track record:
  - track[regime][expert].sum = OOS Calmar * 10  (a score proxy in the same
    units as per-trade impact, scaled so the router's argmax works)
  - track[regime][expert].n   = min_evidence (so pick() can act on it)
  - weights[regime][expert]   = initial schedule from StrategyRouter

The router's rule-floor prior (mean impact of "rule") is left EMPTY here —
per the pick() logic, if the rule has no record, the floor holds. We seed the
floor too (SPY US Calmar 0.174 * 10 = 1.74) so the comparison is defined and
verified experts can actually displace it.

This is the honest starting point for the arena: the self-evolution layer
begins from validated evidence, and live attribution then updates these
entries going forward. Status: SEED only — the harness continues to treat
the router as monitoring (no gate change).

Usage: python -m strategies.seed_router [--state-dir /home/mrc/opentrader/data]
"""

import json
import os
import sys

from strategies.experts import VERIFIED, StrategyRouter

# verified OOS Calmar per expert (source: ROUND2_OOS_SUMMARY.md, re-verified)
OOS_CALMAR = {n: v.oos_calmar for n, v in VERIFIED.items()}
# regime assignment: bull/bear both pick the best drawdown-protected return
# engine; keep it simple — the arena/coordinator refines this later.
MIN_EVIDENCE = 5
SCALE = 10.0  # Calmar -> impact-sum proxy units


def seed(state_dir: str, emit: bool = True) -> dict:
    router = StrategyRouter(rule_floor_calmar=0.174)
    best = max(OOS_CALMAR, key=OOS_CALMAR.get)
    router.register_regime("bull", best)
    router.register_regime("bear", best)

    track = {}
    weights = {}
    # Regime keys MUST match the harness: harness._record_router_impact maps
    # bull/bear -> 'up'/'down' (harness.py:2636-2639), and the shadow engine
    # records under 'up'/'down'. Using 'bull'/'bear' would make the seed inert.
    for regime in ("up", "down"):
        track[regime] = {}
        weights[regime] = {}
        # floor baseline (SPY US Calmar 0.174, scaled)
        track[regime]["rule"] = {"sum": 0.174 * SCALE, "n": MIN_EVIDENCE}
        for name, cal in OOS_CALMAR.items():
            if cal <= 0.174:
                continue
            track[regime][name] = {"sum": cal * SCALE, "n": MIN_EVIDENCE}
        # initial weights: floor 1.0 until the coordinator shifts; but give the
        # seeded best a real starting share so the arena has something to evolve
        weights[regime] = {"rule": 0.5, best: 0.5}

    state = {"track": track, "weights": weights,
             "note": "SEEDED from tournament OOS evidence (2026-08-13); regime "
                     "keys 'up'/'down' match the harness's attribution mapping; "
                     "live attribution updates these entries going forward."}

    if emit:
        os.makedirs(state_dir, exist_ok=True)
        p = os.path.join(state_dir, "live_router_state.json")
        with open(p, "w") as f:
            json.dump(state, f, indent=1)
        print(f"seeded {p}")
        print(f"  best-per-regime: {best} (OOS Calmar {OOS_CALMAR[best]})")
        print(f"  verified experts seeded: {[n for n,c in OOS_CALMAR.items() if c>0.174]}")
    return state


if __name__ == "__main__":
    args = [a for a in sys.argv if a.startswith("--state-dir")]
    state_dir = args[0].split("=")[1] if args else "/home/mrc/opentrader/data"
    seed(state_dir)
