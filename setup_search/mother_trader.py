#!/usr/bin/env python3
"""Mother Trader (#56 Phase 2) — weighted voting + consensus gate (#59).

Mechanism (#59 resolution):
- SOFT VOTE per regime:  sum over active specialists of mean_impact * p_edge.
  mean_impact is the recorded per-trade impact (from paper relabels) — the
  router's track record; p_edge is the calibrated sigmoid. Specialists
  without evidence contribute p_edge only (mean_impact = 0 until proven).
- CONSENSUS GATE: the swarm may TAKE only if the soft vote >= consensus_threshold
  AND at least `min_voters` specialists agree. Below that: HOLD.
- Degrades to allow (no gate) when the swarm is empty — the rule floor's
  decision role is unchanged (Mother Trader is a veto, never a replacement).

Calibration (audit 2026-08-11): the original bar 0.10 was set before the
vote scale was measured. Actual scale: mean_impact ~0.02-0.05 (fraction per
closed trade) × p_edge 0-0.95, and unproven slots contribute 0.0 until
evidence exists. With 2 slots the old gate was mathematically unreachable
(max 2 × 0.95 × mean_impact < 0.10 unless mean_impact > 5.3%) and — worse —
the harness applied the veto to ALL entries, so an unproven swarm froze the
rule floor too (silent hold). Now:
- soft = sum over voters of ramp(n_impacts) * mean_impact * p_edge, where
  ramp(n) = min(1, n / EVIDENCE_RAMP): one lucky trade cannot open the gate,
  sustained per-slot evidence can.
- bar 0.02: two proven specialists at ~2.5% avg impact and high confidence
  clear it (2 × 1.0 × 0.025 × 0.9 = 0.045); one specialist cannot (min_voters).
- the harness vetoes only SPECIALIST-driven entries, never the rule floor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from mot.hive import SwarmRegistry

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "hive" / "mother_trader_state.json"

DEFAULT_CONSENSUS = 0.02   # soft-vote threshold to permit TAKE (audit 2026-08-11)
EVIDENCE_RAMP = 5          # a vote's weight ramps to full after 5 closed-trade impacts
MIN_VOTERS = 2             # at least this many specialists must vote TAKE
ACTIVE_SLOTS = [           # per-market × per-horizon roster (#58); regime assigned at vote time
    "equities__10", "equities__21",
    "crypto__10", "crypto__21",
]


class MotherTrader:
    """Aggregates the swarm's votes per regime into one decision."""

    def __init__(self, registry: Optional[SwarmRegistry] = None,
                 consensus: float = DEFAULT_CONSENSUS,
                 min_voters: int = MIN_VOTERS,
                 active_slots: Optional[List[str]] = None,
                 state_path: Path = STATE):
        self.registry = registry or SwarmRegistry()
        self.consensus = consensus
        self.min_voters = min_voters
        self.active_slots = active_slots or ACTIVE_SLOTS
        self.state_path = state_path
        self.state = {"decisions": 0, "takes": 0, "holds": 0,
                      "last": None, "history": []}
        if state_path.exists():
            try:
                self.state.update(json.loads(state_path.read_text()))
            except Exception:
                pass

    # -- core ----------------------------------------------------------------
    def decide(self, x: np.ndarray, regime: str) -> dict:
        """Soft-vote the swarm for one candidate state; returns the decision."""
        votes = []
        for slot in self.active_slots:
            v = self.registry.vote(slot, x, regime)
            if v is not None:
                votes.append(v)
        if not votes:
            return {"action": "ALLOW", "soft_vote": None, "votes": [],
                    "reason": "swarm empty — rule floor decides"}
        soft = sum((v["mean_impact"] or 0.0) * v["p_edge"]
                   * min(1.0, (v.get("n_impacts") or 0) / EVIDENCE_RAMP)
                   for v in votes)
        take_votes = [v for v in votes if v["take"]]
        allow = soft >= self.consensus and len(take_votes) >= self.min_voters
        self.state["decisions"] += 1
        self.state["takes" if allow else "holds"] += 1
        self.state["last"] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "regime": regime, "soft_vote": soft,
                              "allow": allow, "n_voters": len(take_votes)}
        self.state["history"].append(self.state["last"])
        self.state["history"] = self.state["history"][-200:]
        self.save()
        return {"action": "ALLOW" if allow else "HOLD", "soft_vote": soft,
                "votes": votes, "reason": ("consensus" if allow else
                                           f"soft {soft:.3f} < {self.consensus} or "
                                           f"voters {len(take_votes)} < {self.min_voters}")}

    def record_impact(self, slot: str, regime: str, impact: float) -> None:
        self.registry.record_impact(slot, regime, impact)

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=1, default=str))

    def snapshot(self) -> dict:
        return {"n_slots": len(self.registry.slots),
                "decisions": self.state["decisions"],
                "takes": self.state["takes"], "holds": self.state["holds"],
                "registry": self.registry.snapshot()}
