#!/usr/bin/env python3
"""MoT — Model of Traders Coordinator.

Manages:
  - Cartographer naming for model versions (Ptolemy, Mercator, Ortelius...)
  - 6-hour self-scheduling evaluation cycle
  - Performance scoring and schedule adjustment
  - Multi-model coordination (one per time window)

The MoT runs alongside the harness, evaluating performance every
REVIEW_HOURS and adjusting the schedule based on results.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.mot")

# ── Cartographer Naming (explorer succession, wraps after Ritter) ──
CARTOGRAPHER_NAMES = [
    "Ptolemy", "Mercator", "Ortelius", "Cassini", "Cook", "Ritter",
]

REVIEW_HOURS = 6       # How often the MoT evaluates
MIN_CYCLES_FOR_REVIEW = 10  # Minimum cycles before evaluating
MOT_STATE_FILE = "mot_state.json"

# Score thresholds for decision making
SCORE_ITERATE = 0.1    # Below this: start new model version
SCORE_REDUCE = 0.4     # Below this: narrow trading window
SCORE_INCREASE = 0.7   # Above this: expand trading window


@dataclass
class MoTState:
    """Persistent MoT state."""
    name: str = "Ptolemy"         # Current generation name
    generation: int = 1           # Generation within this name (Ptolemy-1, Ptolemy-2...)
    season: int = 1               # Season counter (incremented after Omega)
    last_review: str = ""         # ISO timestamp of last review
    total_reviews: int = 0
    current_score: float = 0.0
    decision: str = "initializing"
    recommendation: str = ""
    model_performance: Dict[str, float] = field(default_factory=dict)
    schedule_history: List[dict] = field(default_factory=list)


class MoTCoordinator:
    """Model of Traders — evaluates performance and adjusts schedule."""

    def __init__(self, state_dir: str, harness=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.harness = harness
        self.state = self._load_state()

    def _state_path(self) -> Path:
        return self.state_dir / MOT_STATE_FILE

    def _load_state(self) -> MoTState:
        path = self._state_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return MoTState(**data)
            except Exception:
                pass
        return MoTState()

    def _save_state(self) -> None:
        self._state_path().write_text(json.dumps(asdict(self.state), indent=2))

    def version_string(self) -> str:
        """e.g. 'Ptolemy-3' or 'Mercator-1'"""
        return f"{self.state.name}-{self.state.generation}"

    def iterate_version(self) -> str:
        """Advance to next name. Ptolemy-1 → Ptolemy-2 → Mercator-1 → ... → Ritter-9 → Ptolemy-1 (season++)"""
        names = CARTOGRAPHER_NAMES
        idx = names.index(self.state.name) if self.state.name in names else 0
        self.state.generation += 1
        if self.state.generation > 9:
            # Advance to next name
            idx = (idx + 1) % len(names)
            self.state.generation = 1
            if idx == 0:  # wrapped around
                self.state.season += 1
        self.state.name = names[idx]
        self._save_state()
        logger.info(f"MoT: new version → {self.version_string()} (season {self.state.season})")
        return self.version_string()

    # ── Performance Evaluation ───────────────────────────────────

    def evaluate(self) -> dict:
        """Evaluate the last REVIEW_HOURS of trading performance.

        Returns a dict with score, decision, and recommendation.
        """
        cycles = self._load_recent_cycles()
        if len(cycles) < MIN_CYCLES_FOR_REVIEW:
            return {
                "score": 0.0, "decision": "insufficient_data",
                "cycles_analyzed": len(cycles),
                "recommendation": f"Need {MIN_CYCLES_FOR_REVIEW} cycles, have {len(cycles)}",
            }

        # ── Compute metrics ─────────────────────────────────
        returns = self._compute_returns(cycles)
        win_rate = self._compute_win_rate(cycles)
        cycle_efficiency = self._compute_efficiency(cycles)
        avg_confidence = self._compute_avg_confidence(cycles)

        # ── Score (weighted) ────────────────────────────────
        score = (
            min(1.0, max(0, returns * 10)) * 0.40 +  # 10% return → 1.0
            win_rate * 0.30 +
            cycle_efficiency * 0.20 +
            avg_confidence * 0.10
        )

        # ── Decision ───────────────────────────────────────
        if score >= SCORE_INCREASE:
            decision = "increase"
            recommendation = self._recommend_increase()
        elif score >= SCORE_REDUCE:
            decision = "maintain"
            recommendation = "Performance stable. Keep current schedule."
        elif score >= SCORE_ITERATE:
            decision = "reduce"
            recommendation = self._recommend_reduce()
        else:
            decision = "iterate"
            new_name = self.iterate_version()
            recommendation = f"Poor performance. New model: {new_name}. Narrow trading window to 2h."

        # ── Update state ───────────────────────────────────
        self.state.current_score = round(score, 3)
        self.state.decision = decision
        self.state.recommendation = recommendation
        self.state.last_review = datetime.now(timezone.utc).isoformat()
        self.state.total_reviews += 1
        self.state.model_performance = {
            "return_pct": round(returns * 100, 2),
            "win_rate": round(win_rate, 2),
            "efficiency": round(cycle_efficiency, 2),
            "avg_confidence": round(avg_confidence, 2),
        }
        self.state.schedule_history.append({
            "timestamp": self.state.last_review,
            "score": self.state.current_score,
            "decision": decision,
            "version": self.version_string(),
        })
        if len(self.state.schedule_history) > 50:
            self.state.schedule_history = self.state.schedule_history[-50:]

        self._save_state()

        logger.info(
            f"MoT: score={score:.3f} decision={decision} "
            f"return={returns*100:.1f}% win={win_rate:.0%} "
            f"v{self.version_string()}"
        )

        return {
            "score": round(score, 3),
            "decision": decision,
            "cycles_analyzed": len(cycles),
            "recommendation": recommendation,
            "version": self.version_string(),
            "metrics": self.state.model_performance,
        }

    # ── Metric Computations ──────────────────────────────────────

    def _load_recent_cycles(self) -> List[dict]:
        """Load cycle snapshots from the last REVIEW_HOURS."""
        history_dir = self.state_dir / "history"
        if not history_dir.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=REVIEW_HOURS)
        cycles = []
        for f in sorted(history_dir.glob("cycle_*.json")):
            try:
                data = json.loads(f.read_text())
                ts = data.get("timestamp", "")
                if ts and datetime.fromisoformat(ts) > cutoff:
                    cycles.append(data)
            except Exception:
                continue
        return cycles

    @staticmethod
    def _compute_returns(cycles: List[dict]) -> float:
        """Return (final - initial) / initial."""
        if len(cycles) < 2:
            return 0.0
        start = cycles[0].get("portfolio_value", 0)
        end = cycles[-1].get("portfolio_value", 0)
        return (end - start) / max(start, 1)

    @staticmethod
    def _compute_win_rate(cycles: List[dict]) -> float:
        """Fraction of closed trades with positive PnL.

        Reads each cycle's `trades` field (entries from the trade journal,
        each carrying `pnl_pct`). A trade counts as a win if pnl_pct > 0.
        Returns 0.5 (neutral) if no closed trades exist.
        """
        traded = []
        for c in cycles:
            for t in c.get("trades", []):
                pnl = t.get("pnl_pct")
                if pnl is not None:
                    traded.append(pnl)
        if not traded:
            return 0.5
        wins = sum(1 for p in traded if p > 0)
        return wins / len(traded)

    @staticmethod
    def _compute_efficiency(cycles: List[dict]) -> float:
        """How efficiently we're using allocated time. 1.0 = running continuously."""
        if len(cycles) < 2:
            return 0.0
        first_ts = cycles[0].get("timestamp", "")
        last_ts = cycles[-1].get("timestamp", "")
        if not first_ts or not last_ts:
            return 0.5
        try:
            duration_h = (datetime.fromisoformat(last_ts) -
                          datetime.fromisoformat(first_ts)).total_seconds() / 3600
            cycles_per_h = len(cycles) / max(duration_h, 1)
            return min(1.0, cycles_per_h / 30)  # normalize: 30 cycles/h = 1.0 (very active)
        except Exception:
            return 0.5

    @staticmethod
    def _compute_avg_confidence(cycles: List[dict]) -> float:
        """Average signal confidence across the period."""
        confs = []
        for c in cycles:
            for s in c.get("signals", []):
                confs.append(s.get("confidence", 0))
        return sum(confs) / max(len(confs), 1)

    # ── Recommendation Generators ───────────────────────────────

    def _recommend_increase(self) -> str:
        """Generate recommendation for increasing activity."""
        name = self.version_string()
        return (
            f"{name} performing well. Consider expanding trading window by 2h, "
            f"increasing position size to 10%, or adding a second symbol."
        )

    def _recommend_reduce(self) -> str:
        """Generate recommendation for reducing activity."""
        name = self.version_string()
        return (
            f"{name} underperforming. Reduce trading window to 4h max, "
            f"lower position size to 3%, run training scenario analysis."
        )

    # ── Auto-Apply Schedule ─────────────────────────────────────

    def apply_to_schedule(self, schedule: dict, evaluation: dict) -> dict:
        """Apply the evaluation decision to the schedule.

        Returns updated schedule dict.
        """
        decision = evaluation.get("decision", "maintain")
        sched = {k: dict(v) for k, v in (schedule or {}).items()}

        if decision == "increase":
            # Expand trading hours by 2h
            for role in ["trading"]:
                if role in sched:
                    sl = sched[role]
                    sl["start"] = max(0, (sl.get("start", 8) or 8) - 1)
                    sl["end"] = min(24, (sl.get("end", 12) or 12) + 1)
                    logger.info(f"MoT: expanded {role} to {sl['start']}h-{sl['end']}h")

        elif decision == "reduce":
            # Narrow trading to 4h
            for role in ["trading"]:
                if role in sched:
                    sl = sched[role]
                    mid = ((sl.get("start", 8) or 8) + (sl.get("end", 16) or 16)) / 2
                    sl["start"] = max(0, int(mid - 2))
                    sl["end"] = min(24, int(mid + 2))
                    sl["freq"] = "4h"
                    logger.info(f"MoT: reduced {role} to {sl['start']}h-{sl['end']}h")

        elif decision == "iterate":
            # Minimize trading, maximize training
            for role in ["trading"]:
                if role in sched:
                    sched[role]["start"] = 8
                    sched[role]["end"] = 10
                    sched[role]["freq"] = "4h"
                    sched[role]["cap"] = 60
            for role in ["student"]:
                if role in sched:
                    sched[role]["start"] = 10
                    sched[role]["end"] = 18
                    sched[role]["freq"] = "1h"
            logger.info("MoT: iterate mode — narrow trading, expand training")

        # Tag schedule with version info
        for sl in sched.values():
            sl["_mot_version"] = self.version_string()
            sl["_mot_score"] = evaluation.get("score", 0)

        return sched
