#!/usr/bin/env python3
"""FlashTrainer — single-step training that fires during idle GPU cycles.

Runs between trading cycles when the agent is HOLD-ing or the schedule
allocates training time. Uses checkpoint files to resume across cycles.

Two modes:
  - student:    Quick — student model responds, teacher scores (1-3s)
  - full:       Full scenario generation + evaluation (5-10s)
"""
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from training.teacher_student import (
    TeacherStudentFramework, PatternBank
)
from training.programmatic_teacher import ProgrammaticTeacher

logger = logging.getLogger("opentrader.flash_train")


@dataclass
class FlashCheckpoint:
    """Resumable training progress."""
    total_steps: int = 0
    total_score: float = 0.0
    avg_score: float = 0.0
    best_score: float = 0.0
    best_scenario: Optional[str] = None
    scenario_index: int = 0
    mode: str = "student"  # 'student' or 'full'
    last_step_time: float = 0.0
    patterns_generated: int = 0


class FlashTrainer:
    """Single-step training that fits between trading cycles.

    Two training modes:
      - student: Quick — student model responds, teacher scores (1-3s)
      - rl: Behavioral RL — reward-weighted SFT using closed trades (60-120s)

    The RL mode fires when the agent shows behavioral looping patterns
    (stuck on one action for many cycles). It uses the behavioral composite
    reward to weight training examples and produces adapter updates.

    Usage:
        trainer = FlashTrainer(state_dir, llama_host="http://127.0.0.1:5802")
        # In the harness loop:
        if trainer.should_train():
            result = trainer.step()
            logger.info(f"Flash-train: score={result['score']:.2f}")

        # Or explicitly trigger behavioral RL:
        if trainer.should_rl_train():
            rl_result = trainer.rl_step()
    """

    MAX_STEPS_PER_SESSION = 50  # Cap steps before requiring a pause
    HOLD_STREAK_THRESHOLD = 3   # Trigger training after N consecutive HOLDs
    MIN_CYCLE_GAP = 1.5         # Minimum seconds between training steps

    def __init__(
        self,
        state_dir: str,
        llama_host: str = "http://127.0.0.1:5802",
        student_model: str = "ls:qwythos-9b-mtp",
        teacher_model: str = "ls:qwythos-9b-mtp",
        auto_train: bool = True,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.llama_host = llama_host
        self.student_model = student_model
        self.teacher_model = teacher_model
        self.auto_train = auto_train

        self.checkpoint_path = self.state_dir / "flash_train_checkpoint.json"
        self.pattern_bank_path = self.state_dir / "flash_pattern_bank.json"

        # Internal state
        self.checkpoint = self._load_checkpoint()
        self._hold_streak = 0
        self._last_step_time = 0.0
        self._last_rl_step_time = 0.0
        self._teacher: Optional[ProgrammaticTeacher] = None
        self._framework: Optional[TeacherStudentFramework] = None
        self._pattern_bank: Optional[ScenarioBank] = None
        self._rl_trainer = None

    # ── Checkpoint Persistence ──────────────────────────────────

    def _load_checkpoint(self) -> FlashCheckpoint:
        if self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text())
                return FlashCheckpoint(**data)
            except Exception:
                pass
        return FlashCheckpoint()

    def _save_checkpoint(self) -> None:
        data = {
            "total_steps": self.checkpoint.total_steps,
            "total_score": self.checkpoint.total_score,
            "avg_score": self.checkpoint.avg_score,
            "best_score": self.checkpoint.best_score,
            "best_scenario": self.checkpoint.best_scenario,
            "scenario_index": self.checkpoint.scenario_index,
            "mode": self.checkpoint.mode,
            "last_step_time": self.checkpoint.last_step_time,
            "patterns_generated": self.checkpoint.patterns_generated,
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.checkpoint_path)

    # ── Training Decision ───────────────────────────────────────

    def on_hold(self) -> None:
        """Notify trainer that the agent produced a HOLD signal."""
        self._hold_streak += 1

    def on_trade(self) -> None:
        """Notify trainer that the agent produced a BUY/SELL signal."""
        self._hold_streak = 0

    def should_train(self) -> bool:
        """Check if conditions are right for a training step."""
        if not self.auto_train:
            return False
        # Must have HOLD streak
        if self._hold_streak < self.HOLD_STREAK_THRESHOLD:
            return False
        # Must not exceed session cap
        if self.checkpoint.total_steps >= self.MAX_STEPS_PER_SESSION:
            return False
        # Rate limit: minimum gap between steps
        if time.time() - self._last_step_time < self.MIN_CYCLE_GAP:
            return False
        return True

    def reset_session(self) -> None:
        """Reset step counter for a new training session."""
        self.checkpoint.total_steps = 0
        self._save_checkpoint()

    # ── The Core Step ──────────────────────────────────────────

    def step(self, mode: str = "student") -> dict:
        """Run one training step. Returns result dict.

        mode: 'student' (1-3s, score only) or 'full' (5-10s, generate+score)
        """
        now = time.time()
        self._last_step_time = now

        # Lazy init framework
        if self._framework is None:
            self._teacher = ProgrammaticTeacher()
            self._framework = TeacherStudentFramework(
                student_model=self.student_model,
                teacher_model=self.teacher_model,
                llama_host=self.llama_host,
            )
            self._pattern_bank = PatternBank(bank_dir=str(self.state_dir / "pattern_bank"))

        try:
            if mode == "full":
                result = self._step_full()
            else:
                result = self._step_student()

            self.checkpoint.total_steps += 1
            self.checkpoint.last_step_time = time.time() - now

            # Update score tracking
            score = result.get("score", 0)
            self.checkpoint.total_score += score
            self.checkpoint.avg_score = (
                self.checkpoint.total_score / max(1, self.checkpoint.total_steps)
            )
            if score > self.checkpoint.best_score:
                self.checkpoint.best_score = score
                self.checkpoint.best_scenario = result.get("scenario", "")

            self._save_checkpoint()
            return result

        except Exception as e:
            logger.warning(f"Flash-train step failed: {e}")
            return {"status": "error", "error": str(e), "score": 0}

    def _step_full(self) -> dict:
        """Full mode: generate scenario, student responds, teacher scores."""
        scenario = self._teacher.generate_scenario(
            scenario_type=self._next_scenario_type(),
        )
        self.checkpoint.scenario_index += 1
        self.checkpoint.patterns_generated += 1

        # Run episode with this scenario
        episode = self._framework.run_episode(scenario_type=scenario.name)
        score = episode.score if episode else 0
        self._pattern_bank.append(episode)

        return {"status": "ok", "score": score,
                "scenario": getattr(scenario, 'name', str(scenario)), "mode": "full"}

    def _step_student(self) -> dict:
        """Student-only mode: evaluate on a recent pattern."""
        recent = self._pattern_bank.get_recent(5)
        if not recent:
            return self._step_full()

        # Pick a pattern round-robin
        idx = self.checkpoint.scenario_index % len(recent)
        pattern = recent[idx]
        self.checkpoint.scenario_index += 1

        # Score the existing pattern's decision
        score = pattern.score if hasattr(pattern, 'score') else 0.5
        return {"status": "ok", "score": score,
                "pattern": f"pattern-{idx}", "mode": "student"}

    # ── Behavioral RL Integration ────────────────────────────────

    def _get_rl_trainer(self):
        """Lazy-init the BehavioralRLTrainer."""
        if self._rl_trainer is None:
            try:
                from training.rl_trainer import BehavioralRLTrainer

                self._rl_trainer = BehavioralRLTrainer(
                    state_dir=str(self.state_dir),
                    min_examples=5,
                    max_examples=30,
                    checkpoint_interval_seconds=300,
                    max_step_seconds=120,
                )
            except Exception as e:
                logger.debug(f"BehavioralRLTrainer init skipped: {e}")
                self._rl_trainer = False  # Sentinel to avoid retry
        if self._rl_trainer is False:
            return None
        return self._rl_trainer

    def should_rl_train(self) -> bool:
        """Check if we should run a behavioral RL training step.

        Triggers when:
          - Long HOLD streak detected (agent is stuck/paralyzed)
          - No prior RL training step recently
          - Enough closed trades exist
          - No training lock
        """
        if not self.auto_train:
            return False
        if self._hold_streak < self.HOLD_STREAK_THRESHOLD:
            return False
        if time.time() - self._last_rl_step_time < self.MIN_CYCLE_GAP:
            return False

        rl = self._get_rl_trainer()
        if rl is None:
            return False

        should, _ = rl.should_train()
        return should

    def rl_step(self) -> dict:
        """Run one behavioral RL training step during idle cycles.

        This is the key mechanism for breaking behavioral loops:
        the agent's closed trades are scored and turned into
        reward-weighted training data, then a quick SFT pass
        updates the adapter weights.
        """
        rl = self._get_rl_trainer()
        if rl is None:
            return {"status": "skipped", "reason": "rl_trainer unavailable"}

        result = rl.step()
        self._last_rl_step_time = time.time()
        logger.info(
            f"FlashTrainer RL step: status={result.get('status')} "
            f"version={result.get('version', 'N/A')} "
            f"examples={result.get('examples', 0)}"
        )
        return result

    # ── Helpers ─────────────────────────────────────────────────

    def _next_scenario_type(self) -> str:
        """Rotate through scenario types for variety."""
        types = ["trending_up", "breakdown", "ranging", "volatile_rally",
                 "W_bottom", "pump_and_dump", "double_top"]
        return types[self.checkpoint.scenario_index % len(types)]

    def _load_bank(self) -> dict:
        if self.pattern_bank_path.exists():
            try:
                return json.loads(self.pattern_bank_path.read_text())
            except Exception:
                pass
        return {"patterns": []}

    def _save_bank(self, data: dict) -> None:
        tmp = self.pattern_bank_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.pattern_bank_path)

    # ── Stats ──────────────────────────────────────────────────

    def summary(self) -> dict:
        ck = self.checkpoint
        return {
            "total_steps": ck.total_steps,
            "avg_score": round(ck.avg_score, 3),
            "best_score": round(ck.best_score, 3),
            "best_scenario": ck.best_scenario,
            "patterns_generated": ck.patterns_generated,
            "hold_streak": self._hold_streak,
            "mode": ck.mode,
        }
