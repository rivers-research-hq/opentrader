#!/usr/bin/env python3
"""Autonomous task: breed the next specialist cohort + promote gate-passers
into the swarm registry (#56 Phase 2).

Runs the evolutionary breeder per roster slot, then registers every artifact
that cleared the +1% both-window HOLD bar into data/hive/swarm_registry.json
(gate discipline: failing individuals are never registered — evolution.py
reports gate_pass + holdout_margins from windows the GA never saw; this task
enforces the bar at the registry boundary).

Slot roster (#58): per-market × per-regime × per-horizon. Regime here is the
BREEDER's view (the rule floor's SPY-96d gate is applied at inference by the
harness; the breeder gates on both windows so the specialist is
regime-agnostic at promotion — the router assigns regime at vote time).

Artifacts (audit 2026-08-11): each slot owns its artifact + report
(momentum_specialist_10d.pt/_report.json, ...). evolution.py --out-name
writes directly to the slot file, so horizon breeds can never clobber each
other. A re-breed that fails the HOLD gate keeps the previous registration
(never downgrade the swarm on a bad run); a missing artifact unregisters the
slot (no dangling pointers).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import torch

from mot.hive import SwarmRegistry

PROJECT = Path(__file__).resolve().parent.parent
HIVE = PROJECT / "data" / "hive"
ROCM_PY = "/home/mrc/rocm_venv/bin/python3"

# (market, horizon) — equities data exists; crypto slots stay empty until
# crypto_ohlcv.pkl is re-sourced (noted on #56 carry-forward).
SLOTS = [
    ("equities", 10),
    ("equities", 21),
]


def _breed(market: str, horizon: int, seed: int = 42) -> Path:
    out_name = f"momentum_specialist_{horizon}d"
    out = HIVE / f"{out_name}.pt"
    subprocess.run(
        [ROCM_PY, "-m", "setup_search.evolution",
         "--pop", "50", "--gens", "3", "--seed", str(seed),
         "--market", market, "--forward", str(horizon),
         "--out-name", out_name],
        cwd=str(PROJECT), check=False,
    )
    return out


def main() -> None:
    reg = SwarmRegistry()
    promoted = []
    for market, horizon in SLOTS:
        out_name = f"momentum_specialist_{horizon}d"
        ckpt = HIVE / f"{out_name}.pt"
        rep_path = HIVE / f"{out_name}_report.json"
        if ckpt.exists():
            print(f"[hive] {market}/{horizon}: artifact exists, skipping breed")
        else:
            print(f"[hive] breeding {market} fwd={horizon}...", flush=True)
            _breed(market, horizon)
        if not ckpt.exists() or not rep_path.exists():
            print(f"[hive] {market}/{horizon}: no artifact/per-slot report — "
                  f"unregistering stale slot")
            reg.slots.pop(f"{market}__{horizon}", None)
            continue
        rep = json.loads(rep_path.read_text())
        margins = rep.get("holdout_margins", [])
        # Gate discipline: the HOLDOUT gate (windows the GA never saw) must
        # pass; "best_margins" are selection windows and are NOT a gate.
        if not rep.get("gate_pass", False):
            detail = [(r["window"], round(r["margin"], 3), r["kept"])
                      for r in rep.get("holdout_detail", [])]
            print(f"[hive] {market}/{horizon}: HOLD gate FAIL ({detail}, "
                  f"min_kept {rep.get('min_kept')}) — not promoted")
            continue
        # theta from the artifact itself, not the report's gene (which the
        # fit overrides with its val-tuned value).
        art = torch.load(ckpt, weights_only=False)
        theta = float(art.get("theta", 0.0))
        slot = reg.register(ckpt, market, "both", horizon, margins, theta=theta)
        if slot:
            promoted.append(slot)
            print(f"[hive] PROMOTED {slot} holdout_margins={margins}")
    reg.save()
    print(f"[hive] registry: {reg.snapshot()}")


if __name__ == "__main__":
    main()
