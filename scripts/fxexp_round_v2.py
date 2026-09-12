#!/usr/bin/env python3
"""fxexp_round_v2 — the pre-registered panel-v2 generation round.

Pre-registration: docs/agents/research/fx-panel-v2-preregistration-2026-09-12.md
(written before any v2 build/probe/training run).

Fixed plan, not extended after seeing results:
  - panel: data/fx_expert/panel_v2.npz (the live panel.npz is untouched so the
    running lanes' checkpoints stay consistent)
  - 8 generations, fresh init, hp from fxexpert.loop.HPARAMS:
      U, U(seed 23), V, X, AA, N, S, W
  - tags 201..208 (numeric so every existing consumer — gate, deflation
    script, history parser — reads them; the pre-registration's "v201" spelling
    was cosmetic, the namespace separation is kept)
  - gate: fxexpert.gate.evaluate (the standing raw gate)
  - history rows appended to data/fx_expert/history.jsonl with round=panel_v2
  - no registration, no loop_state.json writes (the live loop owns that file)

Usage: .venv/bin/python3 scripts/fxexp_round_v2.py [--start 0] [--only 201,202]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402
from fxexpert import train as fxtrain  # noqa: E402
from fxexpert.loop import HPARAMS  # noqa: E402

OUT = REPO / "data" / "fx_expert"
HISTORY = OUT / "history.jsonl"

PLAN = [  # (tag, hp name, seed) — frozen in the pre-registration
    (201, "U", 11), (202, "U", 23), (203, "V", 11), (204, "X", 11),
    (205, "AA", 11), (206, "N", 11), (207, "S", 11), (208, "W", 11),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated tags")
    ap.add_argument("--panel", default="panel_v2.npz")
    ap.add_argument("--plan", default="",
                    help="override plan as tag:hp:seed,... (control runs)")
    a = ap.parse_args()

    global PLAN
    if a.plan:
        PLAN = [(int(t), h, int(s))
                for t, h, s in (x.split(":") for x in a.plan.split(","))]
    panel = dict(np.load(OUT / a.panel))
    print(f"[v2] panel {panel['features'].shape}, "
          f"{len(np.unique(panel['pair_idx']))} pairs, "
          f"{len(panel['feature_names'])} features")

    only = {int(x) for x in a.only.split(",") if x.strip()}
    for i, (tag, hpname, seed) in enumerate(PLAN):
        if i < a.start or (only and tag not in only):
            continue
        hp = HPARAMS[hpname]
        t0 = time.time()
        print(f"\n[v2] === g{tag}: hp={hpname} seed={seed} fresh init ===")
        try:
            g = fxtrain.run_generation(str(tag), hp, warm_tag=None, seed=seed,
                                       panel=panel)
            res = fxgate.evaluate(str(tag))
        except Exception as e:
            print(f"[v2] g{tag} FAILED: {type(e).__name__}: {e}")
            with HISTORY.open("a") as f:
                f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                    "tag": str(tag), "hp": hpname,
                                    "round": "panel_v2", "error": str(e)}) + "\n")
            continue
        m = res["model"]
        row = {"ts": datetime.now(timezone.utc).isoformat(), "tag": str(tag),
               "hp": hpname, "round": "panel_v2" if a.panel=="panel_v2.npz" else "v1_control", "seed": seed,
               "params": g["params"], "ic_mean": g["aggregate"]["ic_mean"],
               "fold_ics": [f.get("ic_oos") for f in g["folds"]],
               "folds_positive": g["aggregate"]["folds_positive"],
               "pf": m["pf"], "sharpe": m["sharpe"], "maxdd": m["maxdd"],
               "n_pairdays": m["n_pairdays"], "gate": res["gate"]["verdict"],
               "gate_reasons": res["gate"]["reasons"], "promoted": False,
               "registered": False, "warm_from": None,
               "secs": round(time.time() - t0, 1)}
        with HISTORY.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"[v2] g{tag}: gate {res['gate']['verdict']} PF {m['pf']} "
              f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()