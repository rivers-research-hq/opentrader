# -*- coding: utf-8 -*-
"""
mot/monitors.py — Independent monitor committee for signal quality oversight.

Architecture:
  - AccuracyMonitor: per-(symbol,action) accuracy tracking, confidence multipliers
  - RiskMonitor: position sizing and exposure limits
  - CommitteeChair: orchestrates both, adjusts signals by historical accuracy

No LLM calls — purely statistical circuit-breaker for the debate engine.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommitteeResult:
    """Output of committee signal review."""
    approved: bool = True
    adjusted_confidence: float = 1.0
    adjusted_position_pct: float = 0.10
    committee_multiplier: float = 1.0
    notes: str = ""


class AccuracyMonitor:
    """Tracks per-(symbol, action) accuracy to adjust confidence.

    Confidence multiplier tiers (based on tracked accuracy):
        >= 60%  → 1.00  (full confidence)
        50-59%  → 0.85
        40-49%  → 0.65
        30-39%  → 0.45
        <  30%  → 0.30
    """

    TIER_MULTIPLIERS = [
        (0.60, 1.00),
        (0.50, 0.90),
        (0.40, 0.75),
        (0.30, 0.55),
        (0.00, 0.40),  # floor: even 0% accuracy gets 0.40× (still trades, learns)
    ]

    def __init__(self, min_samples: int = 3):
        self._stats: Dict[str, Dict[str, int]] = {}  # key → {correct, total}
        self._min_samples = min_samples

    def _key(self, symbol: str, action: str) -> str:
        return f"{symbol}:{action}"

    def record(self, symbol: str, action: str, correct: bool) -> None:
        key = self._key(symbol, action)
        if key not in self._stats:
            self._stats[key] = {"correct": 0, "total": 0}
        if correct:
            self._stats[key]["correct"] += 1
        self._stats[key]["total"] += 1

    def get_multiplier(self, symbol: str, action: str) -> float:
        """Return confidence multiplier for this (symbol, action).

        Returns 1.0 during cold start (< min_samples recorded).
        """
        key = self._key(symbol, action)
        stats = self._stats.get(key)
        if stats is None or stats["total"] < self._min_samples:
            return 1.0  # cold start: no adjustment
        accuracy = stats["correct"] / max(stats["total"], 1)
        for threshold, multiplier in self.TIER_MULTIPLIERS:
            if accuracy >= threshold:
                return multiplier
        return 0.30  # fallback

    def get_accuracy(self, symbol: str, action: str) -> Optional[float]:
        key = self._key(symbol, action)
        stats = self._stats.get(key)
        if stats is None or stats["total"] == 0:
            return None
        return stats["correct"] / stats["total"]

    def to_dict(self) -> dict:
        return {
            key: {"correct": v["correct"], "total": v["total"],
                  "accuracy": round(v["correct"] / max(v["total"], 1), 3)}
            for key, v in self._stats.items()
        }

    def from_dict(self, d: dict) -> None:
        """Restore _stats from a to_dict() snapshot.

        Loader tolerates missing or extra 'accuracy' field (recomputed on demand).
        """
        self._stats = {}
        for key, v in (d or {}).items():
            if isinstance(v, dict) and "correct" in v and "total" in v:
                self._stats[key] = {"correct": v["correct"], "total": v["total"]}
        if not self._stats:
            # Backward compat: old shape was keyed by "symbol:action" with int accuracy
            for key, acc in (d or {}).items():
                if isinstance(acc, (int, float)):
                    # Reconstruct with total=1 fallback if we only have a fraction
                    total = 1
                    correct = round(acc * total)
                    self._stats[key] = {"correct": correct, "total": total}


class RiskMonitor:
    """Validates signals against risk constraints."""

    def __init__(self, max_position_pct: float = 0.20, max_total_exposure: float = 0.70):
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure

    def check(self, position_pct: float, current_exposure: float) -> tuple[bool, float, str]:
        """Validate proposed position against limits.

        Returns (ok, adjusted_position_pct, warning).
        """
        notes = []

        # Cap position at max_position_pct
        capped = min(position_pct, self.max_position_pct)

        # Check total exposure after adding this position
        new_exposure = current_exposure + capped
        if new_exposure > self.max_total_exposure:
            # Reduce to fit within exposure cap
            room = max(0, self.max_total_exposure - current_exposure)
            capped = min(capped, room)
            notes.append(f"exposure limited ({new_exposure:.1%} → {self.max_total_exposure:.0%})")

        if capped < position_pct * 0.3:
            return False, 0.0, f"position veto: {position_pct:.1%} → insufficient room (exp={current_exposure:.0%})"

        if notes:
            return True, capped, "; ".join(notes)
        return True, capped, ""


class CommitteeChair:
    """Orchestrates AccuracyMonitor + RiskMonitor for signal review.

    Workflow:
        1. review(symbol, action, confidence, position_pct, exposure)
           → CommitteeResult with adjusted confidence/position
        2. record_outcome(symbol, action, correct) after trade closes
           → feeds accuracy tracking for future reviews
    """

    def __init__(self, max_position_pct: float = 0.20, max_total_exposure: float = 0.70,
                 min_accuracy_samples: int = 3):
        self.accuracy = AccuracyMonitor(min_samples=min_accuracy_samples)
        self.risk_monitor = RiskMonitor(
            max_position_pct=max_position_pct,
            max_total_exposure=max_total_exposure,
        )
        self._min_accuracy_samples = min_accuracy_samples

    def review(self, symbol: str, action: str, confidence: float,
               position_pct: float, current_exposure: float) -> CommitteeResult:
        """Review a signal before execution.

        Returns CommitteeResult with adjustments applied.
        """
        # ── Risk check first ──
        ok, risk_pct, risk_notes = self.risk_monitor.check(position_pct, current_exposure)
        if not ok:
            return CommitteeResult(
                approved=False,
                adjusted_confidence=confidence,
                adjusted_position_pct=position_pct,
                committee_multiplier=1.0,
                notes=risk_notes,
            )

        # ── Accuracy adjustment ──
        acc_mult = self.accuracy.get_multiplier(symbol, action)
        accuracy = self.accuracy.get_accuracy(symbol, action)
        adj_conf = confidence * acc_mult

        # Notes
        parts = []
        if risk_notes:
            parts.append(risk_notes)
        if accuracy is not None:
            parts.append(f"acc={accuracy:.0%}→×{acc_mult:.2f}")
        else:
            parts.append("warmup")

        # Veto if adjusted confidence too low
        if adj_conf < 0.10:  # lowered from 0.30→0.20→0.10 — let signals through during warmup
            return CommitteeResult(
                approved=False,
                adjusted_confidence=adj_conf,
                adjusted_position_pct=risk_pct * acc_mult,
                committee_multiplier=acc_mult,
                notes=f"veto: adj_conf={adj_conf:.0%} < 10% ; {'; '.join(parts)}",
            )

        return CommitteeResult(
            approved=True,
            adjusted_confidence=adj_conf,
            adjusted_position_pct=risk_pct * acc_mult,
            committee_multiplier=acc_mult,
            notes="; ".join(parts) if parts else "",
        )

    def record_outcome(self, symbol: str, action: str, correct: bool) -> None:
        """Record a trade outcome for accuracy tracking."""
        self.accuracy.record(symbol, action, correct)

    def summary(self) -> dict:
        return {
            "accuracy": self.accuracy.to_dict(),
            "risk_limits": {
                "max_position_pct": self.risk_monitor.max_position_pct,
                "max_total_exposure": self.risk_monitor.max_total_exposure,
            },
        }

    def restore(self, d: dict) -> None:
        """Restore accuracy stats from a summary() snapshot (inverse of summary()).

        risk_limits are NOT restored here (they are reset by MoT/harness risk
        config sync during run_cycle). Restoring only the learned accuracy stats.
        """
        acc = (d or {}).get("accuracy")
        if acc:
            self.accuracy.from_dict(acc)
