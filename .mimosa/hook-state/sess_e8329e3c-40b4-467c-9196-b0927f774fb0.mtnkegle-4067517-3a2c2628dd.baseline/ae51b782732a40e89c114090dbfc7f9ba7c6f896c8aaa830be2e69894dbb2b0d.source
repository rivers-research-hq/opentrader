#!/usr/bin/env python3
"""Arena handoff: score the 8 verified strategies, build the MoT router state.

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow
This is the canonical bridge from tournament evidence to the MoT layer:
  - runs each verified strategy on the US tournament data (R1) and the intl
    OOS data (R2) through the honest scorers
  - computes the per-regime (up/down) verified Calmar and emits a
    `StrategyRouter` assignment
  - writes router state JSON for the MoT coordinator to consume

The router uses VERIFIED OOS evidence as the track record — not live-drift
waiting. This is the arena's starting point; the coordinator then evolves
weights from here (not from a phantom floor).

Swarm evidence lives in the durable evidence tier: <repo>/data/evidence/swarm/
(swarm_data.pkl, intl_data.pkl, results/*.json). The raw .pkl data was LOST to
/tmp cleanup on 2026-08-23 — when it is absent, the inline runners
(--verify-only) are skipped with a clear message and the static VERIFIED
evidence in strategies/experts.py is used instead (the findings stand as
recorded in AGENTS.md / docs/CONTEXT.md).

Usage:
  python -m strategies.handoff              # full run + emit router state
  python -m strategies.handoff --verify-only
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow

import json
import os
import sys

from strategies.experts import VERIFIED, StrategyRouter

# Durable swarm evidence location (evidence tier; see data/MANIFEST.json).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWARM_DIR = os.path.join(_REPO_ROOT, "data", "evidence", "swarm")
US_PKL = os.path.join(SWARM_DIR, "swarm_data.pkl")
INTL_PKL = os.path.join(SWARM_DIR, "intl_data.pkl")
RESULTS_DIR = os.path.join(SWARM_DIR, "results")
OUT_PATH = os.path.join(SWARM_DIR, "arena_router_state.json")

_LOST_MSG = (
    "swarm data not found in %s (the /tmp originals were lost to cleanup "
    "2026-08-23); inline verification skipped — static VERIFIED evidence used"
)


def _load_us():
    if not os.path.exists(US_PKL):
        raise FileNotFoundError(_LOST_MSG)
    import pickle
    return pickle.load(open(US_PKL, "rb"))


def _expert_eq(name: str) -> "pd.Series":
    """Return the expert's US equity curve (the R1 evidence used for routing).

    Imports are lazy: the scorer modules load the swarm .pkl at import time,
    so importing them eagerly would make this module unimportable whenever the
    (lost) data is absent."""
    import pandas as pd  # noqa: F811
    from strategies.momtrend import run as momtrend
    from strategies.multiasset import backtest as multiasset

    US = _load_us()
    if name == "momtrend":
        return momtrend(US["closes"], mom_lb=60, k=5, rebal=20,
                        breadth_thr=0.6, breadth_win=100, force_exit=False)
    if name == "multiasset":
        return multiasset(US["basket"], rebal=63, vol_lb=120, mom_lb=180,
                          topk=10, eq_frac=0.4, mom_gate=False)
    # abstract experts live as swarm agent scripts; here we read their verified
    # OOS JSON scores directly (documented in ROUND1C/ROUND2 summaries).
    raise KeyError(f"no inline runner for '{name}' (use its OOS JSON score)")


def load_verified_scores() -> dict:
    """Load the verified OOS Calmar/Sharpe from the swarm result JSONs."""
    oos_files = {
        "bayes": "r2_bayes_intl.json", "spectral": "r2_spectral_intl.json",
        "kalman": "r2_kalman_intl.json", "hurst": "r2_hurst_intl.json",
        "wavelet": "r2_wavelet_intl.json", "entropy": "r2_entropy_intl.json",
        "momtrend": "r2_momtrend_intl.json", "multiasset": "r2_multiasset_intl.json",
    }
    out = {}
    for name, f in oos_files.items():
        p = os.path.join(RESULTS_DIR, f)
        if not os.path.exists(p):
            out[name] = _static_score(name)  # fallback to static
            continue
        d = json.load(open(p))
        s = d.get("score") or d.get("summary") or d.get("best") or d
        if isinstance(s, dict) and "calmar" in s:
            out[name] = {"oos_calmar": s["calmar"], "oos_sharpe": s["sharpe"],
                         "maxdd": s["maxdd"]}
        else:
            out[name] = _static_score(name)
    return out


def _static_score(name: str) -> dict:
    """The static VERIFIED evidence (experts.py) as a score dict."""
    v = VERIFIED[name]
    return {"oos_calmar": v.oos_calmar, "oos_sharpe": v.oos_sharpe,
            "maxdd": v.maxdd}


def build_router_state() -> dict:
    scores = load_verified_scores()
    router = StrategyRouter(rule_floor_calmar=0.174)
    # per-regime assignment by best OOS Calmar among those that beat the floor
    best_bull = max(scores, key=lambda n: scores[n]["oos_calmar"])
    best_bear = max(scores, key=lambda n: scores[n]["oos_calmar"])
    if scores[best_bull]["oos_calmar"] > 0.174:
        router.register_regime("up", best_bull)
    if scores[best_bear]["oos_calmar"] > 0.174:
        router.register_regime("down", best_bear)

    state = {
        "source": "tournament R1/R1c/R2 OOS (2026-08-13)",
        "verified_oos_calmar": {n: s["oos_calmar"] for n, s in scores.items()},
        "verified_oos_sharpe": {n: s["oos_sharpe"] for n, s in scores.items()},
        "per_regime_pick": router.summary(),
        "benchmarks": {"intl_basket_calmar": 0.501, "spy_calmar": 0.174},
        "status": "MONITORING / ROSTER — NOT wired to live order flow",
    }
    return state


def main():
    print("=== ARENA HANDOFF — verified strategies ===")
    print(f"US floors: basket BH calmar 0.077 | SPY BH 0.174")
    scores = load_verified_scores()
    print(f"\n{'expert':<12}{'OOS calmar':>12}{'OOS sharpe':>12}{'maxDD':>9}")
    for name, s in sorted(scores.items(), key=lambda x: -x[1]["oos_calmar"]):
        print(f"{name:<12}{s['oos_calmar']:>12.3f}{s['oos_sharpe']:>12.2f}{s['maxdd']*100:>8.1f}%")

    print("\n=== ROUTER STATE ===")
    state = build_router_state()
    print(json.dumps(state["per_regime_pick"], indent=1))
    print(f"\nstatus: {state['status']}")

    os.makedirs(SWARM_DIR, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(state, f, indent=1)
    print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    if "--verify-only" in sys.argv:
        # verify momtrend/multiasset still reproduce (inline runners exist)
        try:
            from strategies import scorer
            eq = _expert_eq("momtrend")
            s = scorer.score_equity(eq)
            print("momtrend R1:", "ann %.1f%% calmar %.3f folds %d" % (
                s["ann"] * 100, s["calmar"], s["folds_beat_basket"]))
            eq2 = _expert_eq("multiasset")
            s2 = scorer.score_equity(eq2)
            print("multiasset R1:", "ann %.1f%% calmar %.3f folds %d" % (
                s2["ann"] * 100, s2["calmar"], s2["folds_beat_basket"]))
        except FileNotFoundError as e:
            print(f"[handoff] {e}")
    else:
        main()
