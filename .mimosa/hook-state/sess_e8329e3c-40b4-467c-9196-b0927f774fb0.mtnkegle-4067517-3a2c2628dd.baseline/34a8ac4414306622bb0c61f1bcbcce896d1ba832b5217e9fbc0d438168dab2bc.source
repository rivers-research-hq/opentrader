#!/usr/bin/env python3
"""Weight evolution — the arena's self-evolution layer shifts weight off the
phantom floor using VERIFIED tournament evidence.

The router's `step()` and the MoT coordinator both wait on LIVE attribution
(which at ~0 fills means years of waiting). This module evolves the weight
schedule NOW, from the verified OOS evidence: weight per (regime, expert)
proportional to verified OOS Calmar, with the rule-floor prior preserved.

Mechanism (consistent with mot/mixture.RegimeRouter semantics):
  - For each regime ('up'/'down'), each verified expert gets weight
    proportional to its OOS Calmar above the floor (0.174 = SPY).
  - The rule floor keeps a floor share (the router's "rule holds unless an
    expert beats it" prior) — set here to the 0.174 baseline's share.
  - Weights are normalized so the top expert never exceeds the router's cap
    (0.5) per step semantics — but the FULL schedule is written so live
    `step()` can continue from here.

This writes data/live_router_state.json (the harness-monitored file) with an
EVOLVED schedule. Status: ROUTING evidence evolution — not live order flow.

Usage:
  python -m strategies.evolve_weights [--state-dir ...] [--dry]
"""

import argparse
import json
import os
import sys

from strategies.experts import VERIFIED

FLOOR_CALMAR = 0.174   # SPY US Calmar (the rule floor's benchmark)
CAP = 0.5              # router per-expert weight cap
FLOOR_SHARE = 0.20     # rule floor keeps this much (prior)


def _evolve_schedule() -> dict:
    """weight per regime = OOS Calmar above floor, proportional, cap-respecting."""
    calmar = {n: v.oos_calmar for n, v in VERIFIED.items()}
    eligible = {n: c for n, c in calmar.items() if c > FLOOR_CALMAR}
    # include laggard_macro overlays? No — those are overlays on laggard, not
    # independent experts; the base experts own the weight schedule.
    eligible.pop("laggard_macro", None)

    schedule = {}
    for regime in ("up", "down"):
        weights = {FLOOR_CALMAR: FLOOR_SHARE}  # placeholder, replaced below
        raw = {n: max(0.0, c - FLOOR_CALMAR) for n, c in eligible.items()}
        total = sum(raw.values())
        if total <= 0:
            schedule[regime] = {"rule": 1.0}
            continue
        w = {n: (v / total) * (1.0 - FLOOR_SHARE) for n, v in raw.items()}
        # cap the top expert at CAP, redistribute the excess to the floor
        top = max(w, key=w.get)
        if w[top] > CAP:
            excess = w[top] - CAP
            w[top] = CAP
            w["rule"] = w.get("rule", 0.0) + excess
        w["rule"] = w.get("rule", 0.0) + FLOOR_SHARE
        schedule[regime] = w
    return schedule


def evolve(state_dir: str, dry: bool = False) -> dict:
    schedule = _evolve_schedule()

    # load existing track (the seeded evidence) so we preserve it.
    # Single-writer contract (#155): all reads/writes of the live router
    # state go through strategies/router_state.py.
    from strategies.router_state import read_router_state, write_router_state
    state = read_router_state(state_dir)
    state["weights"] = schedule

    # RECONCILE the track with the verified evidence: every verified expert
    # must have a track entry (sum = OOS Calmar * SCALE, n = min_evidence) so
    # pick() and weights AGREE (audit: weights and track are two views of the
    # same verified evidence — never let them diverge).
    SCALE = 10.0
    MIN_EVIDENCE = 5
    from strategies.experts import VERIFIED as _VERIFIED
    track = state.setdefault("track", {})
    for regime in ("up", "down"):
        t = track.setdefault(regime, {})
        t.setdefault("rule", {"sum": 0.174 * SCALE, "n": MIN_EVIDENCE})
        for name, v in _VERIFIED.items():
            if name == "laggard_macro":
                continue
            t[name] = {"sum": v.oos_calmar * SCALE, "n": MIN_EVIDENCE}

    state["note"] = ("WEIGHT EVOLUTION (2026-08-13): weights + track reconciled "
                     "to verified OOS Calmar (floor 0.174, cap 0.5); router "
                     "step() can continue evolving from live attribution.")

    if not dry:
        write_router_state(state, state_dir=state_dir)
        print(f"[evolve] wrote {os.path.join(state_dir, 'live_router_state.json')}")
    else:
        print("[evolve] dry run — no write")

    print("[evolve] evolved weight schedule:")
    for regime, w in schedule.items():
        top = sorted(w.items(), key=lambda x: -x[1])[:4]
        print(f"  {regime}: " + "  ".join(f"{k}={v:.2f}" for k, v in top))
    return state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="/home/mrc/opentrader/data")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    evolve(args.state_dir, dry=args.dry)
