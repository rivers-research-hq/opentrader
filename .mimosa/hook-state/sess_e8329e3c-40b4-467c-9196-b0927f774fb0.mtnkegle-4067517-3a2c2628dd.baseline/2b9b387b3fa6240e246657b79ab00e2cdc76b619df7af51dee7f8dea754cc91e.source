#!/usr/bin/env python3
"""Teacher/Student Training Framework for OpenTrader.

Architecture:
  1. TEACHER generates trading scenarios (LLM or programmatic)
  2. STUDENT (agent) analyzes and decides BUY/SELL/HOLD
  3. SCORER evaluates student vs ground truth
  4. PATTERN BANK accumulates scored episodes for future reference

Port of ATLANTIS teacher_student.py concepts into OpenTrader's architecture.
"""
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .programmatic_teacher import ProgrammaticTeacher, Scenario

logger = logging.getLogger("opentrader.training.ts")


@dataclass
class StudentResponse:
    """A student's response to a teacher scenario."""
    decision: str           # BUY, SELL, HOLD
    confidence: float       # 0.0 - 1.0
    reasoning: str = ""
    position_pct: float = 0.0
    latency_ms: float = 0.0
    meta: dict = field(default_factory=dict)


@dataclass
class ScoredEpisode:
    """A complete training episode: scenario + student response + score."""
    scenario: Scenario
    response: StudentResponse
    score: float            # 0.0 - 1.0
    is_correct: bool
    partial_credit: float   # Partial credit for right direction, wrong size
    feedback: str = ""
    timestamp: str = ""


# Type alias for student decision function
StudentFn = Callable[[Scenario], StudentResponse]


class PatternBank:
    """Accumulated training patterns stored as JSONL.

    Each entry is a scored episode. Used for:
    - Retrieval augmentation (student sees similar past patterns)
    - Fine-tuning data generation
    - Progress tracking
    """

    def __init__(self, bank_dir: str = None, max_size: int = 10000):
        if bank_dir is None:
            bank_dir = str(Path.cwd() / "data" / "teacher_student")
        self.bank_dir = Path(bank_dir)
        self.bank_dir.mkdir(parents=True, exist_ok=True)
        self.bank_path = self.bank_dir / "pattern_bank.jsonl"
        self.progress_path = self.bank_dir / "progress.json"
        self.max_size = max_size
        self._episodes: List[ScoredEpisode] = []
        self._load()

    def _load(self) -> None:
        """Load existing patterns from disk."""
        if self.bank_path.exists():
            try:
                with open(self.bank_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            self._episodes.append(ScoredEpisode(
                                scenario=Scenario(**data.get("scenario", {})),
                                response=StudentResponse(**data.get("response", {})),
                                score=data.get("score", 0),
                                is_correct=data.get("is_correct", False),
                                partial_credit=data.get("partial_credit", 0),
                                feedback=data.get("feedback", ""),
                                timestamp=data.get("timestamp", ""),
                            ))
                logger.info(f"Loaded {len(self._episodes)} patterns from bank")
            except Exception as e:
                logger.warning(f"Could not load pattern bank: {e}")

    def append(self, episode: ScoredEpisode) -> None:
        """Add a scored episode to the bank."""
        self._episodes.append(episode)
        # Trim to max size
        if len(self._episodes) > self.max_size:
            self._episodes = self._episodes[-self.max_size:]
        # Write to disk
        try:
            data = {
                "scenario": {
                    "scenario_type": episode.scenario.scenario_type,
                    "description": episode.scenario.description,
                    "bars": episode.scenario.bars,
                    "ground_truth": episode.scenario.ground_truth,
                    "confidence": episode.scenario.confidence,
                    "difficulty": episode.scenario.difficulty,
                    "explanation": episode.scenario.explanation,
                },
                "response": {
                    "decision": episode.response.decision,
                    "confidence": episode.response.confidence,
                    "reasoning": episode.response.reasoning,
                    "position_pct": episode.response.position_pct,
                    "latency_ms": episode.response.latency_ms,
                },
                "score": episode.score,
                "is_correct": episode.is_correct,
                "partial_credit": episode.partial_credit,
                "feedback": episode.feedback,
                "timestamp": episode.timestamp or datetime.now(timezone.utc).isoformat(),
            }
            with open(self.bank_path, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.warning(f"Could not write pattern: {e}")

    def get_recent(self, n: int = 20) -> List[ScoredEpisode]:
        """Get most recent episodes."""
        return self._episodes[-n:]

    def get_best(self, n: int = 10) -> List[ScoredEpisode]:
        """Get highest-scoring episodes."""
        sorted_eps = sorted(self._episodes, key=lambda e: e.score, reverse=True)
        return sorted_eps[:n]

    def get_stats(self) -> dict:
        """Compute aggregate statistics."""
        if not self._episodes:
            return {"count": 0}
        scores = [e.score for e in self._episodes]
        correct = sum(1 for e in self._episodes if e.is_correct)
        return {
            "count": len(self._episodes),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "best_score": round(max(scores), 3) if scores else 0,
            "correct_pct": round(correct / len(self._episodes) * 100, 1) if self._episodes else 0,
            "total_correct": correct,
        }

    def get_learning_curve(self) -> List[dict]:
        """Return score over time for dashboard charting."""
        return [
            {"episode": i, "score": e.score, "correct": e.is_correct}
            for i, e in enumerate(self._episodes)
        ]

    def size(self) -> int:
        return len(self._episodes)

    def clear(self) -> None:
        self._episodes.clear()
        if self.bank_path.exists():
            self.bank_path.unlink()


class TeacherStudentFramework:
    """Core teacher/student training loop.

    Generates scenarios, evaluates student decisions, and accumulates patterns.
    Can use either programmatic or LLM teachers.
    """

    def __init__(
        self,
        student_fn: StudentFn = None,
        teacher=None,
        bank: PatternBank = None,
        score_threshold: float = 0.5,
    ):
        self.student_fn = student_fn
        self.teacher = teacher or ProgrammaticTeacher(seed=42)
        self.bank = bank or PatternBank()
        self.score_threshold = score_threshold

        # Stats
        self.epochs_completed = 0
        self.total_episodes = 0
        self.running_avg_score = 0.0

    def set_student(self, fn: StudentFn) -> None:
        """Set the student decision function."""
        self.student_fn = fn

    def score_decision(self, scenario: Scenario, response: StudentResponse) -> Tuple[float, bool, float, str]:
        """Score a student's decision against the teacher's ground truth.

        Returns (score, is_correct, partial_credit, feedback).
        Score is 0.0-1.0 with partial credit for direction match.
        """
        gt = scenario.ground_truth
        dec = response.decision

        # Exact match: full score scaled by confidence match
        if dec == gt:
            base_score = 0.85 + 0.15 * response.confidence
            is_correct = True
            partial_credit = 1.0
            feedback = f"Correct! Student chose {dec}, teacher expected {gt}."
        else:
            is_correct = False
            # Partial credit: right direction, wrong action
            direction_map = {"BUY": 1, "SELL": -1, "HOLD": 0}
            gt_dir = direction_map.get(gt, 0)
            dec_dir = direction_map.get(dec, 0)

            if gt_dir == 0 and dec_dir != 0:
                # HOLD expected but student acted
                base_score = 0.3 * response.confidence
                partial_credit = 0.3
                feedback = (f"Should have held. Student took {dec} action "
                            f"when patience was warranted.")
            elif gt_dir != 0 and dec_dir == 0:
                # Student held when should have acted
                base_score = 0.2 * response.confidence
                partial_credit = 0.2
                feedback = (f"Missed opportunity. Teacher expected {gt} "
                            f"but student held.")
            elif gt_dir == dec_dir:
                # Right direction, wrong magnitude
                base_score = 0.6 * response.confidence
                partial_credit = 0.6
                # Check if position sizing was reasonable
                if gt == "BUY" and response.position_pct < 0.03:
                    base_score *= 0.8
                    feedback = (f"Right direction ({dec}) but position too small. "
                                f"Should have committed more capital.")
                elif gt == "SELL" and response.position_pct < 0.5:
                    base_score *= 0.8
                    feedback = (f"Right direction ({dec}) but should reduce more. "
                                f"Expected stronger bearish conviction.")
                else:
                    feedback = (f"Right direction ({dec}) but expected {gt}. "
                                f"Good directional read.")
            else:
                # Wrong direction entirely
                base_score = 0.05
                partial_credit = 0.0
                feedback = (f"Wrong direction. Student chose {dec} but teacher "
                            f"expected {gt}. Missed key technical signals.")

        score = min(1.0, max(0.0, base_score))
        return score, is_correct, partial_credit, feedback

    def run_episode(self, scenario_type: str = None) -> ScoredEpisode:
        """Run one training episode: generate scenario, student decides, score."""
        if self.student_fn is None:
            raise ValueError("No student function set. Call set_student() first.")

        # 1. Teacher generates scenario
        scenario = self.teacher.generate(scenario_type)

        # 2. Student decides
        start = time.time()
        response = self.student_fn(scenario)
        latency = (time.time() - start) * 1000
        response.latency_ms = round(latency, 1)

        # 3. Score
        score, is_correct, partial_credit, feedback = self.score_decision(scenario, response)

        episode = ScoredEpisode(
            scenario=scenario,
            response=response,
            score=score,
            is_correct=is_correct,
            partial_credit=partial_credit,
            feedback=feedback,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 4. Store in pattern bank if above threshold
        if score >= self.score_threshold:
            self.bank.append(episode)

        self.total_episodes += 1
        # Running average
        alpha = 0.1
        self.running_avg_score = (1 - alpha) * self.running_avg_score + alpha * score

        logger.info(
            f"Episode {self.total_episodes}: {scenario.scenario_type:20s} "
            f"student={response.decision:5s} gt={scenario.ground_truth:5s} "
            f"score={score:.2f} latency={response.latency_ms:.0f}ms"
        )

        return episode

    def run_epoch(self, scenarios_per_epoch: int = 10) -> dict:
        """Run one epoch (multiple episodes) and return stats."""
        self.epochs_completed += 1
        episodes = [self.run_episode() for _ in range(scenarios_per_epoch)]
        scores = [e.score for e in episodes]
        correct = sum(1 for e in episodes if e.is_correct)

        stats = {
            "epoch": self.epochs_completed,
            "episodes": scenarios_per_epoch,
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
            "correct_pct": round(correct / len(scores) * 100, 1) if scores else 0,
            "total_patterns": self.bank.size(),
            "total_episodes": self.total_episodes,
        }
        logger.info(f"Epoch {self.epochs_completed} complete: {stats}")
        return stats

    def get_progress(self) -> dict:
        """Get full training progress report."""
        bank_stats = self.bank.get_stats()
        return {
            "epochs": self.epochs_completed,
            "total_episodes": self.total_episodes,
            "running_avg_score": round(self.running_avg_score, 3),
            "pattern_bank": bank_stats,
            "learning_curve": self.bank.get_learning_curve(),
        }

    def save_progress(self, path: str = None) -> None:
        """Save training progress to JSON."""
        if path is None:
            path = str(self.bank.bank_dir / "training_progress.json")
        progress = self.get_progress()
        with open(path, "w") as f:
            json.dump(progress, f, indent=2, default=str)
        logger.info(f"Training progress saved to {path}")
