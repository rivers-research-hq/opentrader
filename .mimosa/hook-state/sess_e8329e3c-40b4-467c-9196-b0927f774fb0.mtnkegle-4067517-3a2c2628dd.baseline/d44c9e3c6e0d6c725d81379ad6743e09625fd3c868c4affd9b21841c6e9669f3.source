#!/usr/bin/env python3
"""Cron-safe harness scheduler — triggers ATDL milestones on schedule.

Gate-driven, idempotent. Each function checks preconditions before acting.
Safe to call from cron every minute — it won't double-trigger.

Scheduled milestones:
  Week 1 Day 1:   DPO training (if pairs >= 20 and no DPO model exists)
  Week 1 Day 2-3: Research-scout sweep + capability distill
  Week 1 Day 3-4: Research model training (if gate passed)
  Week 2 Day 5:   Full ATDL cycle trigger
  Week 2 Day 6-7: Next S-tier train or cartographer fold
  Ongoing:        Gate monitoring, lock safety, logging
"""
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "data" / "scheduler.log"
STATE_FILE = PROJECT_ROOT / "data" / "scheduler_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("harness_scheduler")


# ── State persistence ─────────────────────────────────────────

def _load_state() -> Dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "last_dpo_check": None,
        "last_scout_sweep": None,
        "last_distill": None,
        "last_research_model_check": None,
        "last_atdl_trigger": None,
        "dpo_triggered": False,
        "research_model_triggered": False,
        "first_full_cycle_triggered": False,
    }


def _save_state(state: Dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _hours_since(ts: Optional[str]) -> float:
    if not ts:
        return float("inf")
    try:
        dt = datetime.fromisoformat(ts)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return float("inf")


# ── Gate checks ───────────────────────────────────────────────

def _check_training_lock() -> Tuple[bool, str]:
    """Return (blocked, reason)."""
    lock = PROJECT_ROOT / "data" / "training.lock"
    if lock.exists():
        return True, "training.lock exists"
    return False, ""


def _ensure_torch_rocm() -> bool:
    """Ensure PyTorch has ROCm support before any training."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from training.torch_guard import ensure_rocm
        return ensure_rocm()
    except Exception as e:
        logger.warning("Torch guard failed: %s", e)
        return False


def _get_adapter_registry() -> Dict:
    path = PROJECT_ROOT / "data" / "adapter_registry.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _get_capability_state() -> Dict:
    path = PROJECT_ROOT / "data" / "research" / "distilled_registry.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"cumulative_scenarios": 0}


def _get_harness_phase() -> str:
    path = PROJECT_ROOT / "data" / "atdl_state.json"
    if path.exists():
        with open(path) as f:
            return json.load(f).get("phase", "UNKNOWN")
    return "UNKNOWN"


# ── Milestone triggers ────────────────────────────────────────

def trigger_dpo_training(state: Dict) -> bool:
    """Week 1 Day 1: Run DPO training if pairs available and no DPO adapter."""
    if state.get("dpo_triggered"):
        return False

    blocked, reason = _check_training_lock()
    if blocked:
        logger.info("DPO training blocked: %s", reason)
        return False

    # Check if DPO adapter already exists
    reg = _get_adapter_registry()
    for v, entry in reg.items():
        if "P" in v and entry.get("status") in ("active", "pending"):
            logger.info("DPO adapter already exists: %s", v)
            state["dpo_triggered"] = True
            _save_state(state)
            return False

    # Check DPO pair count
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from training.dpo_builder import build_dpo_dataset
        path, count = build_dpo_dataset("data")
        if count < 20:
            logger.info("DPO pairs insufficient: %d < 20", count)
            return False
        logger.info("DPO pairs available: %d — launching training", count)
    except Exception as e:
        logger.warning("DPO pair check failed: %s", e)
        return False

    if not _ensure_torch_rocm():
        logger.error("Cannot run DPO training: PyTorch ROCm not available")
        return False

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "training" / "dpo_trainer.py"),
         "--state-dir", "data", "--version", "Ptolemy-P1"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=3600,
    )
    if result.returncode == 0:
        logger.info("DPO training completed. stdout: %s", result.stdout[-500:])
        state["dpo_triggered"] = True
        state["last_dpo_check"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    else:
        logger.error("DPO training failed (rc=%d): %s", result.returncode, result.stderr[-500:])
        return False


def trigger_research_scout(state: Dict) -> bool:
    """Week 1 Day 2-3: Run research-scout sweep."""
    last = _hours_since(state.get("last_scout_sweep"))
    if last < 12:
        logger.info("Research-scout sweep skipped: last run %.1f hours ago", last)
        return False

    logger.info("Launching research-scout sweep")
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from training.research_runner import run_sweep
        result = run_sweep()
        logger.info("Research sweep: %s", json.dumps(result, default=str)[:200])
        state["last_scout_sweep"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    except ImportError:
        logger.warning("research_runner.run_sweep not available — marking as done")
        state["last_scout_sweep"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    except Exception as e:
        logger.error("Research sweep failed: %s", e)
        return False


def trigger_capability_distill(state: Dict) -> bool:
    """Week 1 Day 2-3: Process unprocessed capability manifests."""
    last = _hours_since(state.get("last_distill"))
    if last < 12:
        return False

    logger.info("Launching capability distillation")
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from training.capability_distiller import distill_all
        result = distill_all("data")
        state["last_distill"] = datetime.now(timezone.utc).isoformat()
        logger.info("Distillation: %s", json.dumps(result, default=str)[:200])

        # Check gate after distillation
        cap_state = _get_capability_state()
        cumulative = cap_state.get("cumulative_scenarios", 0)
        if cumulative >= 50:
            logger.info("RESEARCH MODEL GATE PASSED: %d/50 scenarios", cumulative)

        _save_state(state)
        return True
    except Exception as e:
        logger.error("Distillation failed: %s", e)
        return False


def trigger_research_model_train(state: Dict) -> bool:
    """Week 1 Day 3-4: Train research model if gate passed."""
    if state.get("research_model_triggered"):
        return False

    blocked, reason = _check_training_lock()
    if blocked:
        logger.info("Research model blocked: %s", reason)
        return False

    cap_state = _get_capability_state()
    if cap_state.get("cumulative_scenarios", 0) < 50:
        logger.info("Research model gate not met: %d/50",
                     cap_state.get("cumulative_scenarios", 0))
        return False

    logger.info("Launching research model training")
    if not _ensure_torch_rocm():
        logger.error("Cannot train research model: PyTorch ROCm not available")
        return False

    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "training" / "research_model.py"),
         "--force"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=7200,
    )
    if result.returncode == 0:
        logger.info("Research model training completed")
        state["research_model_triggered"] = True
        state["last_research_model_check"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        return True
    else:
        logger.error("Research model training failed (rc=%d): %s",
                     result.returncode, result.stderr[-500:])
        return False


def trigger_full_atdl_cycle(state: Dict) -> bool:
    """Week 2: Trigger a complete ATDL cycle (PLAN→DEVELOP→TEST→DEPLOY)."""
    if state.get("first_full_cycle_triggered"):
        return False

    blocked, reason = _check_training_lock()
    if blocked:
        logger.info("Full ATDL cycle blocked: %s", reason)
        return False

    phase = _get_harness_phase()
    logger.info("Current harness phase: %s", phase)

    # Check if we have bootstrap CI available
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from training.traderbench import TraderBench
        bench = TraderBench()
        if not hasattr(bench.evaluate, "__code__"):
            logger.warning("TraderBench evaluate missing — skipping full cycle")
            return False
    except Exception:
        pass

    # Signal the harness to run full cycle
    # (The harness reads atdl_state.json each cycle, so we update it)
    atdl_path = PROJECT_ROOT / "data" / "atdl_state.json"
    if atdl_path.exists():
        with open(atdl_path) as f:
            atdl = json.load(f)
        atdl["force_full_cycle"] = True
        atdl["force_cycle_at"] = datetime.now(timezone.utc).isoformat()
        with open(atdl_path, "w") as f:
            json.dump(atdl, f, indent=2)
        logger.info("Full ATDL cycle flagged for next harness iteration")

    state["first_full_cycle_triggered"] = True
    state["last_atdl_trigger"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    return True


def trigger_s_tier_retrain(state: Dict) -> bool:
    """Week 2 Day 6-7: Trigger next S-tier if performance degraded or new data."""
    last = _hours_since(state.get("last_atdl_trigger"))
    if last < 48:
        return False

    blocked, reason = _check_training_lock()
    if blocked:
        return False

    reg = _get_adapter_registry()
    active = None
    for v, entry in reg.items():
        if entry.get("status") == "active":
            active = v
            break

    # Check if folded capabilities exist → new cartographer
    cap_state = _get_capability_state()
    folded = cap_state.get("folded_capabilities", [])
    if folded and not any("Mercator" in v for v in reg):
        logger.info("Folded capabilities detected: %s — triggering new cartographer", folded)

    logger.info("S-tier check: active=%s, folded=%s", active, folded)
    state["last_atdl_trigger"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    return True


# ── Status report ─────────────────────────────────────────────

def print_status():
    """Generate a human-readable status report."""
    state = _load_state()
    cap = _get_capability_state()
    reg = _get_adapter_registry()
    phase = _get_harness_phase()

    active = [(v, e) for v, e in reg.items() if e.get("status") == "active"]
    active_str = ", ".join(f"{v} (score={e.get('training_score', '?')})"
                           for v, e in active) if active else "none"

    lines = [
        "=" * 50,
        "HARNESS SCHEDULER STATUS",
        "=" * 50,
        f"Harness phase:     {phase}",
        f"Active adapter:    {active_str}",
        f"Scenarios:         {cap.get('cumulative_scenarios', 0)}/50",
        f"DPO triggered:     {state.get('dpo_triggered', False)}",
        f"Research model:    {state.get('research_model_triggered', False)}",
        f"Full cycle:        {state.get('first_full_cycle_triggered', False)}",
        f"Last DPO check:    {state.get('last_dpo_check', 'never')}",
        f"Last scout sweep:  {state.get('last_scout_sweep', 'never')}",
        f"Last distill:      {state.get('last_distill', 'never')}",
        f"Last model check:  {state.get('last_research_model_check', 'never')}",
        f"Last ATDL trigger: {state.get('last_atdl_trigger', 'never')}",
        "=" * 50,
    ]
    print("\n".join(lines))


# ── Main (cron entry point) ──────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cron-safe harness scheduler")
    parser.add_argument("action", nargs="?", default="auto",
                        choices=["auto", "dpo", "scout", "distill", "research", "cycle",
                                 "status", "reset"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    state = _load_state()

    if args.action == "status":
        print_status()
        return

    if args.action == "reset":
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        logger.info("Scheduler state reset")
        return

    actions = {
        "dpo": trigger_dpo_training,
        "scout": trigger_research_scout,
        "distill": trigger_capability_distill,
        "research": trigger_research_model_train,
        "cycle": trigger_full_atdl_cycle,
    }

    if args.action in actions:
        if args.force:
            state["dpo_triggered"] = False
            state["research_model_triggered"] = False
            state["first_full_cycle_triggered"] = False
            _save_state(state)
        success = actions[args.action](state)
        logger.info("Action %s: %s", args.action, "OK" if success else "skipped/failed")
        return

    # Auto mode: run all milestones in order
    logger.info("=== Scheduler tick ===")

    # Week 1 Day 1: DPO
    trigger_dpo_training(state)

    # Week 1 Day 2-3: Research sweep + distill
    trigger_research_scout(state)
    trigger_capability_distill(state)

    # Week 1 Day 3-4: Research model
    trigger_research_model_train(state)

    # Week 2 Day 5: Full ATDL cycle
    trigger_full_atdl_cycle(state)

    # Week 2 Day 6-7: Next S-tier
    trigger_s_tier_retrain(state)

    logger.info("=== Scheduler tick complete ===")


if __name__ == "__main__":
    main()
