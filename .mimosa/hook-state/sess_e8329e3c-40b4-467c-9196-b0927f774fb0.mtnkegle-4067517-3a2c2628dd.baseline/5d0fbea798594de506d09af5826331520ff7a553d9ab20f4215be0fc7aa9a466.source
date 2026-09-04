#!/usr/bin/env python3
"""Persistent reflection log for multi-agent debate outcomes.

Stores every debate → outcome pair so future debates include
context like: "Last time Bull recommended BUY in this regime,
the trade was +2.3% after 12 hours."
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.reflection")

MAX_REFLECTIONS = 500


class ReflectionLog:
    """Persistent log of debate outcomes for agent reflection.

    Query:
        reflections = ReflectionLog(state_dir)
        ctx = reflections.get_reflection_context(regime="trending")
        # → "Last 3 decisions in trending regime: 2 correct, 1 wrong"
    """

    def __init__(self, state_dir: str):
        self.path = Path(state_dir) / "reflection_log.json"
        self.log: List[dict] = self._load()

    def _load(self) -> List[dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return []

    def _save(self) -> None:
        # Prune old entries
        if len(self.log) > MAX_REFLECTIONS:
            self.log = self.log[-MAX_REFLECTIONS:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.log, indent=2))
        os.replace(tmp, self.path)

    def record(self, debate_action: str, debate_confidence: float,
               regime: str, bull_action: str, bear_action: str,
               risk_verdict: str, outcome: str = "pending",
               pnl_change: float = 0.0) -> None:
        """Record a debate session outcome."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "debate_action": debate_action,
            "debate_confidence": debate_confidence,
            "regime": regime,
            "bull_action": bull_action,
            "bear_action": bear_action,
            "risk_verdict": risk_verdict,
            "outcome": outcome,
            "pnl_change": round(pnl_change, 4),
        }
        self.log.append(entry)
        self._save()

    def update_outcome(self, action: str, actual_pnl: float) -> None:
        """Mark the most recent matching debate as resolved (correct/wrong).
        Called after a BUY completes → SELL or vice versa.
        """
        for entry in reversed(self.log):
            if entry["debate_action"] == action and entry["outcome"] == "pending":
                profitable = (action == "BUY" and actual_pnl > 0) or \
                             (action == "SELL" and actual_pnl > 0)
                entry["outcome"] = "correct" if profitable else "wrong"
                entry["pnl_change"] = round(actual_pnl, 4)
                self._save()
                return

    def get_reflection_context(self, regime: str = None, n: int = 3) -> str:
        """Build a reflection context string for agent prompts."""
        filtered = [e for e in self.log if e["outcome"] != "pending"]
        if regime:
            filtered = [e for e in filtered if e.get("regime") == regime]

        recent = filtered[-n:] if len(filtered) >= n else filtered
        if not recent:
            return ""

        correct = sum(1 for e in recent if e["outcome"] == "correct")
        total = len(recent)
        lines = [
            f"Reflection: Last {total} decisions in {regime or 'all markets'}: "
            f"{correct}/{total} correct."
        ]
        for e in recent[-3:]:
            pnl = e.get("pnl_change", 0)
            if pnl != 0:
                lines.append(
                    f"  {e['debate_action']} @ {e.get('debate_confidence',0):.0%} "
                    f"→ {e['outcome']} ({pnl:+.2%})"
                )
        return "\n".join(lines)

    @property
    def stats(self) -> dict:
        recent = self.log[-min(len(self.log), 100):]
        correct = sum(1 for e in recent if e["outcome"] == "correct")
        pending = sum(1 for e in recent if e["outcome"] == "pending")
        wrong = sum(1 for e in recent if e["outcome"] == "wrong")
        return {
            "total": len(recent),
            "correct": correct,
            "wrong": wrong,
            "pending": pending,
            "accuracy": round(correct / max(correct + wrong, 1), 3),
        }
