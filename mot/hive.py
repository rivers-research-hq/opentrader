#!/usr/bin/env python3
"""Hive swarm registry (#56 Phase 2) — the roster of gated specialists.

Each specialist is a breeder artifact (`setup_search/evolution.py` output:
state/d_in/stats/theta/gene) registered under a slot key:
    {market}__{regime}__{horizon}
per #58's granularity decision (per-market × per-regime × per-horizon, NOT
per-industry — the scout universe is too thin).

Gate discipline (#60): a specialist enters the registry ONLY if its breeder
report cleared the +1% both-window HOLD bar (the gate runs on HOLDOUT
windows the breeder's GA never sees; evolution.py writes gate_pass +
holdout_margins to its report and task_hive_breed enforces it at the
registry boundary). The rule floor stays the decider until a specialist's
recorded per-trade impact beats it (RegimeRouter.pick semantics).

Calibration (#59): sigmoid for value-head outputs — p_edge =
sigmoid(scale * (v - theta)), clamped to [0.05, 0.95]. mean_impact is tracked
per (regime, slot) from war/paper relabels for the weighted vote.
"""
from __future__ import annotations

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

PROJECT = Path(__file__).resolve().parent.parent
REGISTRY = PROJECT / "data" / "hive" / "swarm_registry.json"


def _sigmoid(z: float) -> float:
    z = float(np.clip(z, -20, 20))
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class Specialist:
    slot: str                 # {market}__{regime}__{horizon}
    path: str                 # checkpoint path
    gate_margins: List[float] # [w0, w1] holdout discrimination at promotion
    theta: float = 0.0
    p_edge_scale: float = 2.0
    size_pct: float = 0.05
    promoted_at: str = ""
    impacts: Dict[str, Dict[str, float]] = field(default_factory=dict)  # regime -> {sum, n}


class SwarmRegistry:
    """Loads breeder artifacts + holds per-slot evidence for the vote."""

    def __init__(self, path: Path = REGISTRY):
        self.path = path
        self.slots: Dict[str, Specialist] = {}
        self._models: Dict[str, nn.Module] = {}
        self._stats: Dict[str, tuple] = {}
        if path.exists():
            try:
                d = json.loads(path.read_text())
                self.slots = {k: Specialist(**v) for k, v in d.get("slots", {}).items()}
            except Exception:
                pass

    # -- registration --------------------------------------------------------
    def register(self, checkpoint: Path, market: str, regime: str, horizon: int,
                 margins: List[float], theta: float) -> Optional[str]:
        """Register a breeder artifact IF it cleared the gate (+1% both windows)."""
        if not checkpoint.exists():
            return None
        if any(m < 0.01 for m in margins):
            return None  # gate discipline: never register a failing specialist
        slot = f"{market}__{horizon}"  # regime assigned at vote time, not promotion
        self.slots[slot] = Specialist(
            slot=slot, path=str(checkpoint), gate_margins=margins,
            theta=theta, promoted_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        self.save()
        return slot

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"slots": {k: asdict(v) for k, v in self.slots.items()},
             "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            indent=1, default=str))

    # -- inference -----------------------------------------------------------
    def _load_model(self, slot: str):
        if slot in self._models:
            return self._models[slot]
        spec = self.slots.get(slot)
        if spec is None:
            return None
        art = torch.load(spec.path, weights_only=True)
        art = torch.load(spec.path, weights_only=True)
        model = nn.Sequential(
            nn.Linear(art["d_in"], art["gene"]["hidden"]), nn.ReLU(),
            nn.Linear(art["gene"]["hidden"], 1),
        )
        model.load_state_dict(art["state"])
        model.eval()
        self._models[slot] = model
        self._stats[slot] = (art["stats"][0], art["stats"][1])
        return model

    def vote(self, slot: str, x: np.ndarray, regime: str) -> Optional[dict]:
        """Calibrated per-slot vote: (action, p_edge, mean_impact)."""
        model = self._load_model(slot)
        if model is None:
            return None
        spec = self.slots[slot]
        mean, std = self._stats[slot]
        z = (x - mean) / (std + 1e-8)
        with torch.no_grad():
            v = float(model(torch.tensor(z).unsqueeze(0)).squeeze(-1).item())
        take = v >= spec.theta
        p_edge = float(np.clip(_sigmoid(spec.p_edge_scale * (v - spec.theta)), 0.05, 0.95))
        imp = spec.impacts.get(regime, {})
        mean_impact = (imp.get("sum", 0.0) / imp["n"]) if imp.get("n", 0) > 0 else None
        return {"slot": slot, "take": take, "p_edge": p_edge,
                "v": v, "theta": spec.theta, "mean_impact": mean_impact,
                "n_impacts": imp.get("n", 0)}

    def record_impact(self, slot: str, regime: str, impact: float) -> None:
        spec = self.slots.get(slot)
        if spec is None:
            return
        imp = spec.impacts.setdefault(regime, {"sum": 0.0, "n": 0})
        imp["sum"] += impact
        imp["n"] += 1
        self.save()

    # -- state ---------------------------------------------------------------
    def snapshot(self) -> dict:
        return {"n_slots": len(self.slots),
                "slots": {k: {"gate_margins": v.gate_margins,
                              "n_impacts": sum(v.impacts[r]["n"] for r in v.impacts)}
                          for k, v in self.slots.items()}}
