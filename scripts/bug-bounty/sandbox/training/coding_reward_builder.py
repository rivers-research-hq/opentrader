#!/usr/bin/env python3
"""Reward functions for RL fine-tuning of OpenTrader coding agents.

Provides reward signals for GRPO and other RL algorithms in the coding domain:
  - code_quality_score: test-pass rate across commits (normalized to [0, 1])
  - bug_intro_penalty: negative penalty proportional to bug-introduction rate
  - code_review_signal: aggregated code-review feedback in [0, 1]
  - code_loop_detection: detect repetitive coding actions
  - code_diversity_bonus: entropy-based bonus for diverse actions in [0, 1]
  - code_anti_loop_penalty: penalty for repetitive code generation in [0, max_penalty]
  - coding_composite_reward: weighted combination of all coding signals
  - coding_reward_from_state: convenience loader that reads from state_dir

See the corresponding trading reward_builder.py for parallel implementations.
"""
import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("opentrader.coding_reward")

# ──────────────────────────────────────────────────────────────────
# Quality-based rewards
# ──────────────────────────────────────────────────────────────────


def code_quality_score(
    code_diffs: list[dict],
    pass_rate_threshold: float = 0.0,
) -> float:
    """Return the average test-pass rate across commits, clamped to [0, 1].

    Each diff dict must contain 'test_pass_rate' (float 0-1).
    Commits below the threshold are counted as 0.

    Returns a float in [0, 1].
    """
    if not code_diffs:
        return 0.0

    rates = []
    for d in code_diffs:
        pr = float(d.get("test_pass_rate", 0))
        # Clamp to valid range
        pr = max(0.0, min(1.0, pr))
        rates.append(pr)

    avg = float(np.mean(rates))
    return round(max(0.0, min(1.0, avg)), 6)


def bug_intro_penalty(
    code_diffs: list[dict],
    penalty_per_bug: float = -0.05,
) -> float:
    """Return a negative penalty proportional to the bug-introduction rate.

    Each diff dict must contain 'bugs_introduced' (int).
    The penalty is normalized per-commit so it scales with history length.

    Returns a float <= 0 (zero when no bugs).
    """
    if not code_diffs:
        return 0.0

    total_bugs = 0
    for d in code_diffs:
        total_bugs += int(d.get("bugs_introduced", 0))

    n = len(code_diffs)
    bug_rate = total_bugs / n if n > 0 else 0.0
    penalty = bug_rate * penalty_per_bug

    return round(float(penalty), 6)


def code_review_signal(
    code_diffs: list[dict],
    max_review_score: float = 5.0,
) -> float:
    """Aggregate code-review feedback into a normalized score in [0, 1].

    Each diff dict contains 'review_score' (float 0-max_review_score).

    Returns a float in [0, 1].
    """
    if not code_diffs:
        return 0.0

    scores = []
    for d in code_diffs:
        r = float(d.get("review_score", 0))
        scores.append(r)

    avg = float(np.mean(scores))
    # Normalize to [0, 1]
    normalized = max(0.0, min(1.0, avg / max_review_score))

    return round(normalized, 6)


# ──────────────────────────────────────────────────────────────────
# Behavioral rewards: loop detection, diversity, anti-loop
# ──────────────────────────────────────────────────────────────────


def code_loop_detection(
    signal_history: list[dict],
    window: int = 20,
    action_ratio_threshold: float = 0.80,
) -> tuple[bool, dict]:
    """Detect if the coding agent is stuck producing repetitive code.

    A behavioral loop is defined as producing the same action
    (e.g. all IMPLEMENT or all NOOP) for >80% of the last N cycles.

    Args:
        signal_history: List of dicts with 'action' key
            ('IMPLEMENT', 'DEBUG', 'REFACTOR', 'NOOP').
        window: Lookback window in signals.
        action_ratio_threshold: Fraction of identical actions that
            triggers loop detection.

    Returns:
        (is_stuck, diagnostics) — is_stuck is True when a loop is
        detected. diagnostics contains dominant_action, action_ratio,
        unique_actions, window_size, etc.
    """
    if len(signal_history) < window:
        return False, {
            "reason": "insufficient_data",
            "count": len(signal_history),
        }

    recent = signal_history[-window:]
    actions = [s.get("action", "NOOP") for s in recent]

    action_counts = Counter(actions)
    dominant_action, dominant_count = action_counts.most_common(1)[0]
    dominant_ratio = dominant_count / len(actions)

    is_stuck = dominant_ratio >= action_ratio_threshold
    unique_actions = len(action_counts)

    diagnostics: dict = {
        "dominant_action": dominant_action,
        "dominant_ratio": round(dominant_ratio, 2),
        "action_counts": dict(action_counts),
        "unique_actions": unique_actions,
        "window_size": window,
    }

    if is_stuck:
        if dominant_action == "NOOP":
            diagnostics["loop_type"] = "paralysis"
        elif dominant_action == "IMPLEMENT":
            diagnostics["loop_type"] = "overwork"
        elif dominant_action == "DEBUG":
            diagnostics["loop_type"] = "debug_loop"
        else:
            diagnostics["loop_type"] = "unknown"
    else:
        diagnostics["loop_type"] = "none"

    return is_stuck, diagnostics


def code_diversity_bonus(
    signal_history: list[dict],
    window: int = 20,
) -> float:
    """Entropy-based bonus for diverse coding actions. Returns [0, 1].

    Uses normalized Shannon entropy of the action distribution.
    Higher entropy (more diverse actions) = higher bonus.
    """
    if len(signal_history) < window:
        return 0.5

    recent = signal_history[-window:]
    actions = [s.get("action", "NOOP") for s in recent]

    counts = Counter(actions)
    total = len(actions)

    # Normalized Shannon entropy
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p)

    # Max entropy for 4 actions = log(4) ≈ 1.386
    max_entropy = math.log(4)
    return round(min(1.0, entropy / max_entropy), 4)


def code_anti_loop_penalty(
    signal_history: list[dict],
    window: int = 20,
    max_penalty: float = 0.5,
) -> float:
    """Penalty for repetitive code generation. Returns [0, max_penalty].

    This is the inverse of code_diversity_bonus: high diversity =
    low penalty.

    Invert: high novelty = low penalty.
    """
    if len(signal_history) < window:
        return 0.0

    diversity = code_diversity_bonus(signal_history, window)
    # Invert: high diversity = low penalty
    penalty = (1.0 - diversity) * max_penalty
    return round(penalty, 4)


# ──────────────────────────────────────────────────────────────────
# Composite rewards
# ──────────────────────────────────────────────────────────────────


def coding_composite_reward(
    code_diffs: list[dict],
    signal_history: list[dict],
    coach_report: Optional[dict] = None,
    w_quality: float = 0.40,
    w_review: float = 0.20,
    w_diversity: float = 0.30,
    w_penalty: float = 0.00,
    w_bug: float = -0.10,
) -> tuple[float, dict]:
    """Weighted composite reward. Returns (total_reward, meta_dict).

    Combines quality signals (test pass rate, bug penalties, review
    feedback) with behavioral signals (diversity, anti-loop, coach
    guidance).

    Args:
        code_diffs: List of commit/diff dicts with test_pass_rate,
            bugs_introduced, review_score.
        signal_history: List of signal dicts with 'action' and optionally
            'reason' keys.
        coach_report: Optional coach analysis dict.
        w_quality, w_review, w_diversity: Positive weights.
        w_penalty: Weight for anti-loop penalty (positive weight,
            penalty is already negative).
        w_bug: Weight for bug penalty (already negative).

    Returns:
        (total_reward, meta) where meta contains individual components.
    """
    quality = code_quality_score(code_diffs)
    bug_pen = bug_intro_penalty(code_diffs)
    review = code_review_signal(code_diffs)
    diversity = code_diversity_bonus(signal_history)
    anti_loop = code_anti_loop_penalty(signal_history)

    # Coach-guided behavioral adjustment
    coach_boost = 0.0
    coach_penalty = 0.0
    failure_patterns = []

    if coach_report:
        failure_patterns = coach_report.get("failure_patterns", [])
        winning_patterns = coach_report.get("winning_patterns", [])
        coach_grade = coach_report.get("grade", "N/A")

        grade_map = {"A": 0.15, "B": 0.1, "C": 0.05, "D": -0.1, "F": -0.2}
        grade_bonus = grade_map.get(coach_grade, 0.0)
        coach_boost += grade_bonus

        # Pattern matching: if recent signals look like failure patterns,
        # penalize
        if failure_patterns:
            recent_texts = [
                s.get("reason", "") for s in signal_history[-20:]
            ]
            pattern_matches = sum(
                1
                for fp in failure_patterns
                for rt in recent_texts
                if fp[:20].lower() in rt.lower()
            )
            if pattern_matches > 0:
                coach_penalty = min(0.3, pattern_matches * 0.05)
                coach_boost -= coach_penalty

        # Boost if matching winning patterns
        if winning_patterns:
            recent_texts = [
                s.get("reason", "") for s in signal_history[-20:]
            ]
            win_matches = sum(
                1
                for wp in winning_patterns
                for rt in recent_texts
                if wp[:20].lower() in rt.lower()
            )
            if win_matches > 0:
                coach_boost += min(0.3, win_matches * 0.05)

    total = (
        w_quality * quality
        + w_bug * bug_pen
        + w_review * review
        + w_diversity * diversity
        + w_penalty * anti_loop
        + coach_boost
    )

    meta = {
        "code_quality_score": round(quality, 4),
        "bug_penalty": round(bug_pen, 4),
        "code_review_score": round(review, 4),
        "diversity_bonus": round(diversity, 4),
        "anti_loop_penalty": round(anti_loop, 4),
        "coach_boost": round(coach_boost, 4),
        "coach_penalty": round(coach_penalty, 4),
        "total": round(float(total), 4),
    }

    return round(float(total), 4), meta


def coding_reward_from_state(
    state_dir: str,
    window: int = 20,
    **composite_kwargs,
) -> float:
    """Load coding state files from state_dir and compute composite reward.

    Reads:
      - agent_state.json for code_diffs and signal_history,
      - coach_report.json for coach feedback.

    Returns the composite reward value.
    """
    state_path = Path(state_dir)
    agent_path = state_path / "agent_state.json"
    coach_path = state_path / "coach_report.json"

    code_diffs: list[dict] = []
    signal_history: list[dict] = []
    coach_report: Optional[dict] = None

    if agent_path.exists():
        try:
            with open(agent_path) as f:
                agent = json.load(f)
            code_diffs = agent.get("code_diffs", agent.get("_code_diffs", []))
            signal_history = (
                agent.get("signal_history",
                agent.get("_signal_history", []))
            )
        except Exception as e:
            logger.warning("Failed to load agent_state.json: %s", e)

    if coach_path.exists():
        try:
            with open(coach_path) as f:
                coach_report = json.load(f)
        except Exception as e:
            logger.warning("Failed to load coach_report.json: %s", e)

    total, meta = coding_composite_reward(
        code_diffs,
        signal_history,
        coach_report,
        window=window,
        **composite_kwargs,
    )

    logger.info(
        "coding_reward_from_state: total=%s, meta=%s", total, meta
    )
    return total


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute RL rewards for coding agents from state files"
    )
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    reward = coding_reward_from_state(args.state_dir)
    print(f"coding_composite_reward={reward}")

    # Additional diagnostic output from agent_state if available
    state_path = Path(args.state_dir)
    agent_path = state_path / "agent_state.json"
    if agent_path.exists():
        try:
            with open(agent_path) as f:
                agent = json.load(f)
            diffs = agent.get("code_diffs", agent.get("_code_diffs", []))
            sigs = agent.get("signal_history", agent.get("_signal_history", []))
            print(f"commits={len(diffs)} signals={len(sigs)}")
            if diffs:
                print(
                    f"quality_score={code_quality_score(diffs)}"
                )
                print(
                    f"bug_penalty={bug_intro_penalty(diffs)}"
                )
                print(
                    f"review_signal={code_review_signal(diffs)}"
                )
            if sigs:
                stuck, diag = code_loop_detection(sigs)
                print(f"stuck={stuck} loop_type={diag.get('loop_type')}")
                print(
                    f"diversity={code_diversity_bonus(sigs)}"
                )
                print(
                    f"anti_loop_penalty={code_anti_loop_penalty(sigs)}"
                )
        except Exception as e:
            logger.error("Error reading agent_state.json: %s", e)
