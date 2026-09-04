#!/usr/bin/env python3
"""ATDL — Automated Trading Development Lifecycle.

Google-style AI-driven SDLC applied to trading strategy evolution.

Phases (state machine):
  PLAN     → Analyze market, review coach reports, set objectives
  DEVELOP  → Train new LoRA adapters on curated data
  TEST     → Backtest candidate vs baseline on held-out data
  DEPLOY   → Promote winners (canary first, then full roll-out)
  MONITOR  → Watch live performance, detect drift, trigger PLAN
  ITERATE  → Collect learnings, update priors, loop

Architecture:
  ┌──────────┐   ┌──────────┐   ┌──────────┐
  │  PLAN    │──→│ DEVELOP  │──→│  TEST    │
  └──────────┘   └──────────┘   └──────────┘
       ↑                              │
       │         ┌──────────┐         │
       └─────────│ ITERATE  │←────────┘
                 └──────────┘
                      ↑
  ┌──────────┐        │
  │ MONITOR  │────────┘
  └──────────┘
       ↑
  ┌──────────┐
  │ DEPLOY   │
  └──────────┘

Usage:
  atdl = ATDL(pool, coach, ensemble, state_dir="data")
  atdl.step(cycle)  # called from harness main loop
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.atdl")


class Phase(Enum):
    IDLE = auto()
    PLAN = auto()
    DEVELOP = auto()
    TEST = auto()
    DEPLOY = auto()
    MONITOR = auto()
    ITERATE = auto()


PHASE_LABELS = {
    Phase.IDLE: "Idle",
    Phase.PLAN: "Planning",
    Phase.DEVELOP: "Developing",
    Phase.TEST: "Testing",
    Phase.DEPLOY: "Deploying",
    Phase.MONITOR: "Monitoring",
    Phase.ITERATE: "Iterating",
}


@dataclass
class StrategyVariant:
    name: str
    version: int
    adapter_path: str
    status: str = "candidate"  # candidate | canary | active | retired
    grade: str = "—"
    win_rate: float = 0.0
    sharpe: float = 0.0
    total_pnl: float = 0.0
    trades: int = 0
    created_at: str = ""
    promoted_at: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class LifecycleState:
    phase: Phase = Phase.IDLE
    cycle: int = 0
    plan: Dict[str, Any] = field(default_factory=dict)
    active_variants: List[StrategyVariant] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    last_update: str = ""


class ATDL:
    """Automated Trading Development Lifecycle orchestrator."""

    MIN_TRADES_FOR_REVIEW = 10
    CANARY_ALLOCATION = 0.10    # 10% of capital for canary testing
    CANARY_MIN_TRADES = 20      # trades before promoting canary
    PROMOTE_THRESHOLD = 1.15    # candidate must beat baseline by 15%

    def __init__(self, pool: Any = None, coach: Any = None,
                 state_dir: str = "data", output_dir: str = "models/finetune"):
        self.pool = pool
        self.coach = coach
        self.state_dir = Path(state_dir)
        self.output_dir = Path(output_dir)

        self.phase = Phase.IDLE
        self._phase_start_cycle: int = 0
        self._phase_timeout_cycles: int = 1000

        self.variants: List[StrategyVariant] = []
        self._variant_counter: int = 0
        self.baseline = StrategyVariant(
            name="baseline", version=0, adapter_path="", status="active",
        )
        self.candidate: Optional[StrategyVariant] = None

        self.history: List[Dict[str, Any]] = []
        self.state_file = self.state_dir / "atdl_state.json"

        self.rocm_python = self._find_rocm_python()
        self._load_state()

    def _find_rocm_python(self) -> str:
        candidates = ["/home/mrc/rocm_venv/bin/python3", "python3"]
        for p in candidates:
            if os.path.exists(p):
                return p
        return "python3"

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text())
            self.phase = Phase[state.get("phase", "IDLE")]
            self._variant_counter = state.get("variant_counter", 0)
            self.history = state.get("history", [])
            for vd in state.get("variants", []):
                sv = StrategyVariant(**vd)
                self.variants.append(sv)
                if sv.status == "active" and sv.name != "baseline":
                    self.baseline = sv
            logger.info(f"ATDL: loaded state ({len(self.variants)} variants, phase={self.phase.name})")
        except Exception as e:
            logger.debug(f"ATDL state load failed: {e}")

    def _save_state(self) -> None:
        state = {
            "phase": self.phase.name,
            "variant_counter": self._variant_counter,
            "variants": [
                {
                    "name": v.name, "version": v.version,
                    "adapter_path": v.adapter_path, "status": v.status,
                    "grade": v.grade, "win_rate": v.win_rate,
                    "sharpe": v.sharpe, "total_pnl": v.total_pnl,
                    "trades": v.trades, "created_at": v.created_at,
                    "promoted_at": v.promoted_at, "metrics": v.metrics,
                }
                for v in self.variants
            ],
            "history": self.history[-50:],
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2, default=str))

    # ═══════════════════════════════════════════════════════════════
    # Main step — called from harness
    # ═══════════════════════════════════════════════════════════════

    def step(self, cycle: int, force: bool = False) -> Optional[Dict[str, Any]]:
        """Advance the lifecycle state machine. Called from harness main loop.

        Returns a dict with any actions the harness should take, or None.
        """
        if self.phase == Phase.IDLE:
            return self._enter_plan(cycle)

        if self.phase == Phase.PLAN:
            return self._step_plan(cycle)

        if self.phase == Phase.DEVELOP:
            return self._step_develop(cycle)

        if self.phase == Phase.TEST:
            return self._step_test(cycle)

        if self.phase == Phase.DEPLOY:
            return self._step_deploy(cycle)

        if self.phase == Phase.MONITOR:
            return self._step_monitor(cycle)

        if self.phase == Phase.ITERATE:
            return self._step_iterate(cycle)

        return None

    def _transition(self, new_phase: Phase, cycle: int) -> None:
        old = self.phase
        self.phase = new_phase
        self._phase_start_cycle = cycle
        self.history.append({
            "from_phase": old.name, "to_phase": new_phase.name,
            "cycle": cycle, "timestamp": datetime.utcnow().isoformat(),
        })
        logger.info(
            f"ATDL: {PHASE_LABELS[old]} → {PHASE_LABELS[new_phase]} "
            f"(cycle {cycle})"
        )
        self._save_state()

    # ═══════════════════════════════════════════════════════════════
    # PLAN — analyze market, set objectives
    # ═══════════════════════════════════════════════════════════════

    def _enter_plan(self, cycle: int) -> Optional[Dict[str, Any]]:
        logger.info("ATDL PLAN: analyzing state and setting objectives")
        self._transition(Phase.PLAN, cycle)

        coach_grade = "F"
        retrain_recommended = True
        if self.coach:
            coach_grade = self.coach.get_current_grade()
            retrain_recommended = self.coach.is_training_needed()

        objectives = {
            "grade": coach_grade,
            "retrain": retrain_recommended,
            "focus": self.coach.get_training_focus() if self.coach else "general",
            "current_baseline": self.baseline.name,
            "active_variants": len([v for v in self.variants if v.status == "active"]),
        }
        logger.info(
            f"  Objectives: grade={coach_grade}, retrain={retrain_recommended}, "
            f"focus='{objectives['focus']}'"
        )
        return None

    # ═══════════════════════════════════════════════════════════════
    # PLAN step — wait for coach review to complete
    # ═══════════════════════════════════════════════════════════════

    def _step_plan(self, cycle: int) -> Optional[Dict[str, Any]]:
        # If coach recommends retraining, enter DEVELOP
        if self.coach and self.coach.is_training_needed():
            self._transition(Phase.DEVELOP, cycle)
            return None

        # If we have a canary that needs evaluation, enter TEST
        canaries = [v for v in self.variants if v.status == "canary"]
        if canaries and canaries[0].trades >= self.CANARY_MIN_TRADES:
            self.candidate = canaries[0]
            self._transition(Phase.TEST, cycle)
            return None

        # Stay in MONITOR if nothing to do
        self._transition(Phase.MONITOR, cycle)
        return None

    # ═══════════════════════════════════════════════════════════════
    # DEVELOP — create new strategy variant (LoRA adapter)
    # ═══════════════════════════════════════════════════════════════

    def _step_develop(self, cycle: int) -> Optional[Dict[str, Any]]:
        logger.info("ATDL DEVELOP: building new strategy variant")

        # Build training data
        curated_file = str(self.output_dir / "training" / "training_data_curated.jsonl")
        if self.coach:
            self.coach.curate_dataset(cycle)
        if not os.path.exists(curated_file):
            logger.warning("  No curated data available; using legacy")
            curated_file = str(self.output_dir / "training" / "training_data_legacy.jsonl")
            if not os.path.exists(curated_file):
                self._transition(Phase.MONITOR, cycle)
                return {"atdl_status": "skipped_develop: no training data"}

        # Determine version
        self._variant_counter += 1
        version = f"V{self._variant_counter}"
        name = f"Ptolemy-{version}"
        output_path = str(self.output_dir / name / "adapter")

        focus = self.coach.get_training_focus() if self.coach else "general"
        logger.info(f"  Training {name} (focus: {focus})...")

        # Launch training
        train_script = Path(__file__).parent.parent / "training" / "train_rocm.py"
        cmd = [
            self.rocm_python, str(train_script),
            "--data", curated_file, "--output", output_path,
            "--no-4bit", "--epochs", "2",
        ]

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=900, cwd=str(Path(__file__).parent.parent),
            )
            if proc.returncode == 0:
                variant = StrategyVariant(
                    name=name, version=self._variant_counter,
                    adapter_path=output_path, status="candidate",
                    created_at=datetime.utcnow().isoformat(),
                    metrics={"training_focus": focus},
                )
                self.variants.append(variant)
                self.candidate = variant
                logger.info(f"  {name} trained successfully → candidate")
                self._transition(Phase.TEST, cycle)
            else:
                logger.warning(f"  Training failed (exit {proc.returncode})")
                self._transition(Phase.MONITOR, cycle)
        except subprocess.TimeoutExpired:
            logger.warning("  Training timed out")
            self._transition(Phase.MONITOR, cycle)
        except Exception as e:
            logger.error(f"  Training error: {e}")
            self._transition(Phase.MONITOR, cycle)

        self._save_state()
        return None

    # ═══════════════════════════════════════════════════════════════
    # TEST — backtest candidate vs baseline, canary evaluation
    # ═══════════════════════════════════════════════════════════════

    def _step_test(self, cycle: int) -> Optional[Dict[str, Any]]:
        if not self.candidate:
            self._transition(Phase.MONITOR, cycle)
            return None

        logger.info(
            f"ATDL TEST: evaluating {self.candidate.name} vs {self.baseline.name}"
        )

        # Evaluate using coach if available
        eval_result = None
        if self.coach and self.candidate.adapter_path:
            eval_result = self.coach.evaluate_adapter(
                self.candidate.name, self.candidate.adapter_path,
            )

        if eval_result:
            winner = eval_result.get("winner", "base")
            improvement = eval_result.get("improvement_pct", 0)
            should_promote = eval_result.get("should_promote", False)

            logger.info(
                f"  Eval: winner={winner}, improvement={improvement:.0f}%, "
                f"promote={should_promote}"
            )

            if should_promote and improvement >= self.PROMOTE_THRESHOLD:
                self._transition(Phase.DEPLOY, cycle)
            elif improvement >= 1.0:  # slightly better → canary
                self.candidate.status = "canary"
                logger.info(f"  {self.candidate.name} → canary ({self.CANARY_ALLOCATION:.0%} allocation)")
                self._transition(Phase.MONITOR, cycle)
            else:
                self.candidate.status = "retired"
                logger.info(f"  {self.candidate.name} → retired (no improvement)")
                self._transition(Phase.MONITOR, cycle)
        else:
            # No eval data → deploy as canary to gather real data
            self.candidate.status = "canary"
            logger.info(
                f"  {self.candidate.name} → canary (no eval data, "
                f"{self.CANARY_ALLOCATION:.0%} allocation for live testing)"
            )
            self._transition(Phase.DEPLOY, cycle)

        self._save_state()
        return None

    # ═══════════════════════════════════════════════════════════════
    # DEPLOY — promote candidate to active, demote baseline if worse
    # ═══════════════════════════════════════════════════════════════

    def _step_deploy(self, cycle: int) -> Optional[Dict[str, Any]]:
        if not self.candidate:
            self._transition(Phase.MONITOR, cycle)
            return None

        logger.info(f"ATDL DEPLOY: promoting {self.candidate.name}")

        old_baseline = self.baseline

        self.candidate.status = "active"
        self.candidate.promoted_at = datetime.utcnow().isoformat()
        self.baseline = self.candidate

        if old_baseline and old_baseline.name != "baseline":
            old_baseline.status = "retired"
            logger.info(f"  {old_baseline.name} → retired")

        self.candidate = None

        action = {
            "atdl_deploy": {
                "active": self.baseline.name,
                "adapter_path": self.baseline.adapter_path,
                "canary_allocation": self.CANARY_ALLOCATION,
            }
        }

        logger.info(
            f"  Active strategy: {self.baseline.name} at {self.baseline.adapter_path}"
        )
        self._transition(Phase.MONITOR, cycle)
        self._save_state()
        return action

    # ═══════════════════════════════════════════════════════════════
    # MONITOR — watch live performance, trigger PLAN on drift
    # ═══════════════════════════════════════════════════════════════

    def _step_monitor(self, cycle: int) -> Optional[Dict[str, Any]]:
        # Check if coach grade has degraded
        grade = self.coach.get_current_grade() if self.coach else "F"

        if grade in ("D", "F"):
            elapsed = cycle - self._phase_start_cycle
            if elapsed > 500:
                logger.info(
                    f"ATDL MONITOR: grade={grade}, elapsed={elapsed} cycles. "
                    "Triggering PLAN."
                )
                self._transition(Phase.PLAN, cycle)
                return None

        return None

    # ═══════════════════════════════════════════════════════════════
    # ITERATE — collect learnings, update priors
    # ═══════════════════════════════════════════════════════════════

    def _step_iterate(self, cycle: int) -> Optional[Dict[str, Any]]:
        logger.info("ATDL ITERATE: collecting lifecycle learnings")

        active = [v for v in self.variants if v.status == "active"]
        canary = [v for v in self.variants if v.status == "canary"]
        retired = [v for v in self.variants if v.status == "retired"]
        total_variants = len(self.variants)

        logger.info(
            f"  Variants: {total_variants} total, {len(active)} active, "
            f"{len(canary)} canary, {len(retired)} retired"
        )

        # Write iteration summary
        summary = {
            "cycle": cycle,
            "total_variants": total_variants,
            "active": self.baseline.name,
            "best_grade_seen": max(
                (v.grade for v in self.variants if v.grade not in ("—", "N/A")),
                default="F",
            ),
            "phase_history": [
                h for h in self.history[-10:]
            ],
        }
        logger.info(f"  Summary: {json.dumps(summary, indent=2)}")

        self._transition(Phase.PLAN, cycle)
        self._save_state()
        return {"atdl_iteration": summary}

    # ═══════════════════════════════════════════════════════════════
    # State query
    # ═══════════════════════════════════════════════════════════════

    def get_status(self) -> Dict[str, Any]:
        return {
            "phase": PHASE_LABELS.get(self.phase, str(self.phase)),
            "cycle": self._phase_start_cycle,
            "baseline": self.baseline.name,
            "candidate": self.candidate.name if self.candidate else None,
            "variants": {
                v.name: {
                    "status": v.status, "grade": v.grade,
                    "win_rate": v.win_rate, "trades": v.trades,
                }
                for v in self.variants
            },
            "history": self.history[-5:],
        }
