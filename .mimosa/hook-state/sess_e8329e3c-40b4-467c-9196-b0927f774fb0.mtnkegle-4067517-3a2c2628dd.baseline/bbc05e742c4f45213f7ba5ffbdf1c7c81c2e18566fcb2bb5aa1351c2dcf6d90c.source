#!/usr/bin/env python3
"""Training data builder — converts reflection log + cycle history into
ShareGPT-formatted training examples for LoRA fine-tuning.

Architecture:
  reflection_log.json  ─┐
  cycle_*.json history ─┤→ data_builder → training_data.jsonl (ShareGPT)
  mot_state.json       ─┘

Each training example is a conversation:
  system:   "You are a trading agent..."
  user:     "<OHLCV summary> <portfolio state> <regime>"
  assistant: "Action: BUY/SELL/HOLD. Reason: ..."

The builder is invoked before each fine-tune cycle and produces a JSONL
file consumable by finetune_cycle.py.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.data_builder")

# How many of the most recent reflections to use
MAX_REFLECTIONS = 200
# Minimum entries needed to bother building data
MIN_REFLECTIONS_FOR_TRAIN = 10


def build_training_data(
    state_dir: str,
    output_path: str = None,
    include_history: bool = True,
) -> Tuple[str, int]:
    """Build ShareGPT training data from reflection log + cycle history.

    Args:
        state_dir: Directory containing state/reflection/history files.
        output_path: Where to write the .jsonl file. Defaults to
                     <state_dir>/training/training_data.jsonl.
        include_history: Whether to correlate with cycle history for
                         richer OHLCV context.

    Returns:
        (output_path, num_examples)
    """
    state_path = Path(state_dir)
    ref_path = state_path / "reflection_log.json"

    if not ref_path.exists():
        logger.info("No reflection log found — no training data to build.")
        return "", 0

    # ── Load reflection log ────────────────────────────────────
    try:
        reflections = json.loads(ref_path.read_text())
    except Exception as e:
        logger.warning(f"Failed to load reflection log: {e}")
        return "", 0

    # Use resolved entries when available; fall back to all recent entries
    resolved = [r for r in reflections if r.get("outcome") in ("correct", "wrong")]
    if len(resolved) >= MIN_REFLECTIONS_FOR_TRAIN:
        selected = resolved
        logger.info(f"Using {len(selected)} resolved reflections")
    elif len(reflections) >= MIN_REFLECTIONS_FOR_TRAIN:
        selected = reflections
        logger.info(f"Using {len(selected)} reflections (unresolved)")
    else:
        logger.info(
            f"Need {MIN_REFLECTIONS_FOR_TRAIN} reflections, "
            f"have {len(reflections)} ({len(resolved)} resolved). Skipping."
        )
        return "", 0

    # Take the most recent ones
    selected = selected[-MAX_REFLECTIONS:]

    # ── Load cycle history for OHLCV context ──────────────────
    history_map: Dict[str, dict] = {}
    if include_history:
        history_dir = state_path / "history"
        if history_dir.exists():
            for f in sorted(history_dir.glob("cycle_*.json")):
                try:
                    data = json.loads(f.read_text())
                    ts = data.get("timestamp", "")
                    if ts:
                        history_map[ts] = data
                except Exception:
                    continue

    # ── Load MoT state for version context ──────────────────
    mot_version = "Ptolemy-S0"
    mot_path = state_path / "mot_state.json"
    if mot_path.exists():
        try:
            mot = json.loads(mot_path.read_text())
            name = mot.get("name", "Ptolemy")
            gen = mot.get("generation", 1)
            mot_version = f"{name}-{gen}"
        except Exception:
            pass

    # ── Build examples ────────────────────────────────────────
    examples = []
    for entry in selected:
        conv = _entry_to_conversation(entry, history_map, mot_version)
        if conv:
            examples.append({"conversations": conv})

    if not examples:
        logger.info("No valid training examples could be built.")
        return "", 0

    # ── Write output ──────────────────────────────────────────
    if output_path is None:
        train_dir = state_path / "training"
        train_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(train_dir / "training_data.jsonl")
    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    logger.info(
        f"Built {len(examples)} training examples from "
        f"{len(selected)} reflections → {output_path}"
    )
    return output_path, len(examples)


def _entry_to_conversation(
    entry: dict,
    history_map: Dict[str, dict],
    mot_version: str,
) -> Optional[List[dict]]:
    """Convert a single reflection entry to a ShareGPT conversation."""
    action = entry.get("debate_action", "HOLD")
    outcome = entry.get("outcome", "pending")
    regime = entry.get("regime", "unknown")
    confidence = entry.get("debate_confidence", 0.5)
    bull_act = entry.get("bull_action", "HOLD")
    bear_act = entry.get("bear_action", "HOLD")
    risk_verdict = entry.get("risk_verdict", "HOLD")
    pnl = entry.get("pnl_change", 0.0)
    timestamp = entry.get("timestamp", "")

    # Find matching cycle history entry (fuzzy: by timestamp prefix)
    ohlcv_summary = _find_ohlcv_context(timestamp, history_map)

    # ── Build system message ──────────────────────────────
    system_msg = (
        f"You are a trading agent (version {mot_version}) operating "
        f"in a {regime} market. You participate in a debate with "
        f"Bull and Bear analysts, then a Risk manager scores both "
        f"sides and produces a final action. Your task is to learn "
        f"from past debate outcomes."
    )

    # ── Build user message ────────────────────────────────
    user_lines = [f"Market regime: {regime}"]
    if ohlcv_summary:
        user_lines.append(f"Market context: {ohlcv_summary}")
    user_lines.append(f"Portfolio change: {pnl:+.4%}")
    user_lines.append("")
    user_lines.append("Debate input:")
    user_lines.append(f"  Bull argues: {bull_act}")
    user_lines.append(f"  Bear argues: {bear_act}")
    user_lines.append(f"  Risk verdict: {risk_verdict}")
    user_lines.append(f"  Debate confidence: {confidence:.0%}")
    user_msg = "\n".join(user_lines)

    # ── Build assistant message ───────────────────────────
    correct_label = "correct" if outcome == "correct" else "incorrect"
    assistant_msg = (
        f"Action: {action}\n"
        f"Outcome: {correct_label} (PnL: {pnl:+.4%})\n"
        f"Lesson learned: The debate resulted in a {action} signal "
        f"with {confidence:.0%} confidence. This was {correct_label} "
        f"in {regime} market conditions."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": assistant_msg},
    ]


def _find_ohlcv_context(timestamp: str, history_map: Dict[str, dict]) -> str:
    """Find the nearest cycle history entry for a given timestamp."""
    if not timestamp or not history_map:
        return ""
    # Try exact match first (truncate to minute precision)
    ts_prefix = timestamp[:16]  # "2025-07-03T12:34"
    candidates = []
    for hts, data in history_map.items():
        if hts.startswith(ts_prefix):
            candidates.append(data)
    if not candidates:
        # Fuzzy: find closest within 1 hour
        try:
            target = datetime.fromisoformat(timestamp)
            for hts, data in history_map.items():
                try:
                    ht = datetime.fromisoformat(hts)
                    diff = abs((ht - target).total_seconds())
                    if diff < 3600:
                        candidates.append(data)
                except Exception:
                    continue
        except Exception:
            pass

    if not candidates:
        return ""

    # Use first matching entry
    data = candidates[0]
    prices = data.get("prices", {})
    signals = data.get("signals", [])

    parts = []
    if prices:
        price_str = ", ".join(
            f"{sym}: ${pr:.2f}" for sym, pr in list(prices.items())[:3]
        )
        parts.append(f"Prices: {price_str}")
    if signals:
        last_sig = signals[-1] if signals else {}
        parts.append(
            f"Last signal: {last_sig.get('action', '?')} "
            f"({last_sig.get('confidence', 0):.0%})"
        )
    return " | ".join(parts)


def reflection_stats(state_dir: str) -> dict:
    """Return stats about current reflection log for dashboard."""
    ref_path = Path(state_dir) / "reflection_log.json"
    if not ref_path.exists():
        return {"total": 0, "resolved": 0, "trainable": 0}

    try:
        reflections = json.loads(ref_path.read_text())
    except Exception:
        return {"total": 0, "resolved": 0, "trainable": 0}

    resolved = [r for r in reflections if r.get("outcome") in ("correct", "wrong")]
    trainable = len(resolved) >= MIN_REFLECTIONS_FOR_TRAIN

    return {
        "total": len(reflections),
        "resolved": len(resolved),
        "trainable": trainable,
        "min_required": MIN_REFLECTIONS_FOR_TRAIN,
    }
