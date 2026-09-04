#!/usr/bin/env python3
"""WS-A daily-archive MoT shadow — the edge evidence engine.

Evaluates the trained value-head experts on the SAME daily archives they were
validated on, head-to-head against the rule floor on identical candidates, and
records per-regime (entry-state) impacts into per-universe persisted router
state (data/live_router_state_{universe}.json — distinct from the arena's
mot_router_state.json and the harness's live_router_state.json).

Design (per docs/research/live-feedback-methodology.md):
  - The arena's held-out gate is the EDGE evidence; this shadow is the
    evidence-rich monitor (thousands of candidates per run vs ~0.5 trades/month
    on the live harness — the harness cannot accrue evidence in any runway).
  - The rule floor takes every regime-passing screen-passer (validated
    behavior); each expert takes only where V(s) >= theta. Impacts are 10-bar
    forward returns, conservative: 10bps notional slippage subtracted from
    every execution so the record understates.
  - Paired-ish semantics: experts and the rule are evaluated on the SAME
    candidate rows; each records its own executions (arena convention).

Universes:
  us            11-dim US rows  -> rule floor + momentum head
  macro         18-dim macro    -> rule floor + macro head
  international 11-dim intl     -> rule floor + international head
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
CONSERVATIVE_SLIPPAGE = 0.001  # 10bps per side, paper must understate

UNIVERSES = ("us", "macro", "international")


def _collect(universe: str, period: str):
    if universe == "macro":
        from arena.candidates_macro import collect
    elif universe == "international":
        from arena.candidates_international import collect
    else:
        from arena.candidates import collect
    rows, base = collect(period)
    return rows, base


def _load_expert(universe: str):
    """ValueHeadExpert for the universe's head; None if no checkpoint."""
    from arena import agent as agent_mod
    from mot.experts import ValueHeadExpert

    paths = {
        "us": PROJECT / "data" / "arena" / "arena_value_head.pt",
        "macro": PROJECT / "data" / "arena" / "arena_macro_value_head.pt",
        "international": PROJECT / "data" / "arena" / "arena_international_value_head.pt",
    }
    p = paths[universe]
    if not p.exists():
        return None
    exp = ValueHeadExpert.from_checkpoint(p, name=universe)
    return exp


def _take_votes(rows, expert):
    """Vectorized take/skip over all candidate rows."""
    if expert is None:
        return np.zeros(len(rows), dtype=bool)
    from arena import agent as agent_mod
    xs = [r["x"] for r in rows]
    vs = agent_mod.predict_batch(expert.art, xs)
    theta = expert.art["theta"]
    return vs >= theta


def run_universe(universe: str, period: str, sample: int) -> dict:
    from mot.mixture import RegimeRouter

    rows, _ = _collect(universe, period)
    if sample and sample > 0:
        rng = np.random.RandomState(7)
        idx = rng.permutation(len(rows))[:sample]
        rows = [rows[i] for i in idx]

    expert = _load_expert(universe)
    takes = _take_votes(rows, expert)

    router = RegimeRouter(rule_floor="rule", min_evidence=5)
    state_file = PROJECT / "data" / f"live_router_state_{universe}.json"
    if state_file.exists():
        try:
            d = json.loads(state_file.read_text())
            router.track = d.get("track", {})
            router.weights = d.get("weights", {})
        except Exception:
            pass

    n_rule = 0
    n_expert = 0
    for i, r in enumerate(rows):
        regime = "up" if r["regime_up"] else "down"
        impact = float(r["fwd"]) - CONSERVATIVE_SLIPPAGE
        # rule floor: takes regime-passing screen-passers (validated behavior)
        if r["regime_up"]:
            router.record(regime, "rule", impact)
            n_rule += 1
        # expert: takes where V(s) >= theta
        if takes[i] and expert is not None:
            router.record(regime, expert.name, impact)
            n_expert += 1

    state_file.write_text(json.dumps(
        {"track": router.track, "weights": router.weights}, indent=1))
    return {
        "universe": universe,
        "n_candidates": len(rows),
        "n_rule_takes": n_rule,
        "n_expert_takes": n_expert,
        "expert": expert.name if expert else None,
        "picks": {r: router.pick(r) for r in ("up", "down")},
        "evidence": {
            r: {e: {"n": t["n"], "mean_impact": round(t["sum"] / t["n"], 5)}
                for e, t in es.items()}
            for r, es in router.track.items()
        },
        "state_file": str(state_file),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="5y")
    ap.add_argument("--sample", type=int, default=0, help="0 = all candidates")
    ap.add_argument("--universe", default="all", choices=list(UNIVERSES) + ["all"])
    args = ap.parse_args()

    unis = list(UNIVERSES) if args.universe == "all" else [args.universe]
    for u in unis:
        rep = run_universe(u, args.period, args.sample)
        print(f"[shadow] {u}: {rep['n_candidates']} candidates | "
              f"rule={rep['n_rule_takes']} expert({rep['expert']})={rep['n_expert_takes']} "
              f"| picks={rep['picks']}", flush=True)
        for reg, ev in rep["evidence"].items():
            line = "  ".join(f"{e}:n={t['n']},m={t['mean_impact']:+.3%}" for e, t in ev.items())
            print(f"    {reg}: {line}", flush=True)
    print(f"[shadow] state -> data/live_router_state_*.json")


if __name__ == "__main__":
    main()
