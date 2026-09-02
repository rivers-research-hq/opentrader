"""MoT experts — concrete Expert implementations for the RegimeRouter.

Closes seam d (mot/experts.py was aspirational): a ``ValueHeadExpert`` wraps the
arena's trained value-head MLP as a first-class ``mot.mixture.Expert`` that
emits ``ExpertDecision(action, size_pct, p_edge, evidence)``. The value head is
the deployable edge (the "many MB models" vision); the LLM stays the
explainable/architect layer.

``p_edge`` calibration: V(s) is a forward-return estimate (not a probability), so
p_edge is a logistic map ``sigmoid(k * V(s))`` with k=2 (V=+0.5 -> ~0.73,
V=-0.5 -> ~0.27), clipped to [0.05, 0.95].
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np

from mot.mixture import ExpertDecision

PROJECT = Path(__file__).resolve().parent.parent
ARENA_CHECKPOINT = PROJECT / "data" / "arena" / "arena_value_head.pt"


def _sigmoid(z):
    z = np.clip(z, -20, 20)
    return 1.0 / (1.0 + np.exp(-z))


class ValueHeadExpert:
    """Wraps an arena value head (ArenaMLP) as a MoT Expert.

    decide() accepts either a state dict with an 'x' feature vector (arena war
    contract) or a MoT-style ctx carrying 'x'. Falls back to HOLD (no position)
    if no feature vector is available — the expert never proposes blindly.
    """

    def __init__(self, art: Optional[dict] = None, name: str = "value-head",
                 size_pct: float = 0.05, p_edge_scale: float = 2.0):
        self.art = art
        self.name = name
        self.size_pct = size_pct
        self.p_edge_scale = p_edge_scale
        if art is not None:
            self.art["model"].eval()

    # -- loading -------------------------------------------------------------
    @classmethod
    def from_checkpoint(cls, path: Optional[Path] = None,
                        name: str = "value-head") -> "ValueHeadExpert":
        path = path or ARENA_CHECKPOINT
        if not path.exists():
            return cls(art=None, name=name)
        from arena import agent as agent_mod
        art = agent_mod.load(path)
        return cls(art=art, name=name) if art else cls(art=None, name=name)

    # -- Expert protocol ------------------------------------------------------
    def decide(self, ctx: Any, symbol: str = "") -> ExpertDecision:
        if self.art is None:
            return ExpertDecision(action="HOLD", p_edge=0.0,
                                  evidence={"reason": "no checkpoint"})
        x = getattr(ctx, "x", None)
        if x is None and isinstance(ctx, dict):
            x = ctx.get("x")
        if x is None:
            return ExpertDecision(action="HOLD", p_edge=0.0,
                                  evidence={"reason": "no feature vector"})
        v = float(self._predict(x)[0])
        take = v >= self.art["theta"]
        p_edge = float(np.clip(_sigmoid(self.p_edge_scale * v), 0.05, 0.95))
        return ExpertDecision(
            action="BUY" if take else "HOLD",
            size_pct=self.size_pct if take else 0.0,
            p_edge=p_edge,
            evidence={"value": v, "theta": self.art["theta"],
                      "margin": v - self.art["theta"]},
        )

    def _predict(self, x):
        from arena.agent import predict_batch
        return predict_batch(self.art, [x])

    # -- convenience for the arena wire-up -----------------------------------
    def record_impacts(self, router, war_report, expert_name=None):
        """Feed per-regime per-trade impacts from a war report into a
        RegimeRouter (closes seam e: the router finally receives real data).

        war_report: arena/war.py run_war output; regime_decomp[expert] gives
        per-regime mean pnl_pct and counts."""
        name = expert_name or self.name
        for reg, stats in war_report.get("regime_decomp", {}).get(name, {}).items():
            n = stats.get("n", 0)
            if n >= router.min_evidence:
                router.record("up" if reg == "up" else "down", name, stats.get("mean_pnl_pct", 0.0))
        return router
