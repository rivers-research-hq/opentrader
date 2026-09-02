#!/usr/bin/env python3
"""Performance tracking and MoE gating for multi-agent system.

Tracks each agent's rolling accuracy per regime type.
Computes dynamic weights for synthesis.
"""
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("opentrader.scoring")

DECAY_WINDOW = 50  # How many recent decisions to consider


@dataclass
class AgentRecord:
    """Track record for a single agent role."""
    name: str
    total_decisions: int = 0
    correct_calls: int = 0
    win_loss_ratio: float = 0.0
    avg_confidence: float = 0.0
    regime_performance: Dict[str, Any] = field(default_factory=dict)
    recent_scores: List[float] = field(default_factory=list)  # rolling window

    @property
    def accuracy(self) -> float:
        if self.total_decisions == 0:
            return 0.5
        return self.correct_calls / self.total_decisions

    @property
    def rolling_avg(self) -> float:
        if not self.recent_scores:
            return 0.5
        return sum(self.recent_scores) / len(self.recent_scores)


class AgentScorer:
    """Tracks agent performance and computes dynamic weights.

    Usage:
        scorer = AgentScorer(state_dir)
        scorer.record("bull", action="BUY", confidence=0.7,
                      regime="trending", correct=True)
        weights = scorer.get_weights(regime="trending")
    """

    def __init__(self, state_dir: str):
        self.path = Path(state_dir) / "agent_scores.json"
        self.records: Dict[str, AgentRecord] = self._load()
        self._lock = threading.Lock()

    def _load(self) -> Dict[str, AgentRecord]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                return {k: AgentRecord(**v) for k, v in data.items()}
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        with self._lock:
            data = {k: {
                "name": v.name, "total_decisions": v.total_decisions,
                "correct_calls": v.correct_calls, "win_loss_ratio": v.win_loss_ratio,
                "avg_confidence": v.avg_confidence,
                "regime_performance": v.regime_performance,
                "recent_scores": v.recent_scores[-DECAY_WINDOW:],
            } for k, v in self.records.items()}
            try:
                self.path.write_text(json.dumps(data, indent=2))
            except Exception:
                pass  # non-critical, ignore write failures in parallel mode

    def record(self, agent: str, action: str, confidence: float,
               regime: str, correct: bool) -> None:
        """Record a single decision outcome."""
        with self._lock:
            if agent not in self.records:
                self.records[agent] = AgentRecord(name=agent)

            rec = self.records[agent]
            rec.total_decisions += 1
            rec.avg_confidence = (
                (rec.avg_confidence * (rec.total_decisions - 1) + confidence)
                / rec.total_decisions
            )

            # Score: 1.0 for correct high-conf, 0.0 for wrong high-conf, scaled
            score = 1.0 if correct else 0.0
            if confidence < 0.4:
                score = 0.5  # low confidence = less impact regardless

            rec.recent_scores.append(score)
            if len(rec.recent_scores) > DECAY_WINDOW:
                rec.recent_scores.pop(0)

            if correct:
                rec.correct_calls += 1
            rec.win_loss_ratio = rec.correct_calls / max(rec.total_decisions, 1)

            # Migrate old float format → dict format (Fix 5 companion)
            rp = rec.regime_performance.get(regime)
            if isinstance(rp, (int, float)):
                # Old format: float accuracy → convert to dict
                old_acc = float(rp)
                rec.regime_performance[regime] = {
                    "correct": int(round(old_acc * rec.total_decisions)),
                    "total": rec.total_decisions,
                }
            elif regime not in rec.regime_performance:
                rec.regime_performance[regime] = {"correct": 0, "total": 0}
            rec.regime_performance[regime]["total"] += 1
            if correct:
                rec.regime_performance[regime]["correct"] += 1

        self._save()

    def get_weight(self, agent: str, regime: str = None) -> float:
        """Compute dynamic weight for an agent based on recent performance."""
        rec = self.records.get(agent)
        if not rec or rec.total_decisions < 5:
            return 1.0  # insufficient data = equal weight

        # Base: rolling average
        weight = rec.rolling_avg

        # Regime bonus: how well this agent performs in current regime
        if regime and regime in rec.regime_performance:
            rp = rec.regime_performance[regime]
            if isinstance(rp, dict):
                total = rp.get("total", 0)
                acc = rp.get("correct", 0) / total if total > 0 else 0.5
            else:
                acc = float(rp)
            regime_adj = acc - 0.5  # -0.5 to +0.5
            weight += regime_adj * 0.3

        return max(0.1, min(1.0, weight))

    def get_weights(self, regime: str = None) -> Dict[str, float]:
        """Get weights for all agents, normalized to sum = 1.0."""
        raw = {}
        for agent in self.records:
            raw[agent] = self.get_weight(agent, regime)

        if not raw:
            return {"bull": 0.4, "bear": 0.35, "risk": 0.25}

        total = sum(raw.values())
        return {k: v / total for k, v in raw.items()}

    def summary(self) -> dict:
        return {
            agent: {
                "accuracy": rec.accuracy,
                "rolling": rec.rolling_avg,
                "confidence": round(rec.avg_confidence, 2),
                "decisions": rec.total_decisions,
            }
            for agent, rec in self.records.items()
        }
