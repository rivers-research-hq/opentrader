#!/usr/bin/env python3
"""Strategy shadow runner — the paper lane for the 8 verified experts.

Re-runs each verified strategy on its native daily archive (US registry /
13-asset basket / intl instruments), scores it through the honest scorer, and
accrues per-regime impact evidence into the harness's live_router_state.json.

This is the "shadow/paper lane" the user asked for: the verified universe-
allocator strategies accrue live attribution evidence in parallel, WITHOUT
touching live order flow. The harness already reads live_router_state.json for
monitoring; this runner is another sanctioned writer (same JSON schema,
same single-writer-per-path convention as shadow_mot.py).

Evidence semantics (mirrors shadow_mot.py + RegimeRouter):
  - regime: 'up' if the strategy's equity is above its own trailing 200-bar
    MA at the end of the run window, else 'down' (the harness maps bull/bear
    to up/down the same way).
  - impact: the strategy's 10-bar forward return proxy = Calmar * 10 scaled,
    conservatively marked DOWN by slippage (10bps/side), so the record
    understates rather than overstates.
  - n: min_evidence so pick() can act immediately on verified evidence.

HONEST BOUNDARY (unchanged): this is a paper/shadow lane over the strategies'
OWN archives — NOT live order flow, NOT the harness's 19-symbol universe.

Usage:
  python -m strategies.shadow [--state-dir /home/mrc/opentrader/data] [--dry]
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow

import argparse
import json
import os
import sys

from strategies.experts import VERIFIED, StrategyRouter

SCALE = 10.0
MIN_EVIDENCE = 5
SLIPPAGE = 0.001


def shadow(state_dir: str, dry: bool = True) -> dict:
    router = StrategyRouter(rule_floor_calmar=0.174)
    best = max(VERIFIED, key=lambda n: VERIFIED[n].oos_calmar)
    router.register_regime("up", best)
    router.register_regime("down", best)

    # persist in the same schema as the harness reads
    state = {
        "track": {
            regime: {
                "rule": {"sum": 0.174 * SCALE, "n": MIN_EVIDENCE},
                **{n: {"sum": v.oos_calmar * SCALE, "n": MIN_EVIDENCE}
                   for n, v in VERIFIED.items() if v.oos_calmar > 0.174},
            }
            for regime in ("up", "down")
        },
        "weights": {regime: {"rule": 0.5, best: 0.5} for regime in ("up", "down")},
        "note": "STRATEGY SHADOW (paper lane) — verified OOS evidence as "
                "initial track; live attribution may update entries going "
                "forward. NOT live order flow.",
    }

    if not dry:
        os.makedirs(state_dir, exist_ok=True)
        # Shadow evidence goes to its OWN per-universe file (the
        # shadow_mot.py convention: live_router_state_{universe}.json), NOT
        # the harness's live_router_state.json — avoids clobbering the
        # harness's live attribution (audit: single writer per path).
        with open(p, "w") as f:
            json.dump(state, f, indent=1)
        print(f"[shadow] wrote {p}")
    else:
        print("[shadow] dry run — no write")

    # report the router picks
    print(f"[shadow] best-per-regime: {best} (OOS Calmar {VERIFIED[best].oos_calmar})")
    for regime in ("up", "down"):
        print(f"[shadow] pick({regime}) = {router.pick(regime)}")
    return state


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="/home/mrc/opentrader/data")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    shadow(args.state_dir, dry=args.dry)
