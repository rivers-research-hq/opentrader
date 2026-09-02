#!/usr/bin/env python3
"""Training Scheduler — decides when to pause trading and fine-tune.

Optimization problem:
  - Trading profit: ~$13.89/hr (opportunity cost of training)
  - Training benefit: +3-5% win rate → +$0.42/hr
  - Training cost: ~$2.78 first run, ~$0.69 cached
  - Payback: 6.6 hours (first), 1.6 hours (cached)

Decision criteria (all must pass):
  1. WIN_RATE < 0.65              → model needs improvement
  2. NEW_EXAMPLES >= 20            → enough data to learn
  3. FEAR_GREED in 20-55           → non-extreme market = lower opportunity cost
  4. HOUR window matches           → low volatility periods
  5. No CRITICAL positions         → TP/SL can ride but no new entries
"""
import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from setup_search import gpu_activity

logger = logging.getLogger("opentrader.scheduler")

STATE_DIR = Path(__file__).resolve().parent.parent / "data"
SCHEDULER_STATE = STATE_DIR / "train_schedule.json"
TRAINING_LOCK = STATE_DIR / "training.lock"
HOLD_ACK = STATE_DIR / "training_hold_ack"
# Serving server is managed by systemd (opentrader-llama-gpu1.service) — the
# single source of truth for its model/alias/port/ctx. Stop/start via systemctl
# only; never pkill llama-server (AGENTS.md), and never relaunch by hand.
LLAMA_SERVER_UNIT = "opentrader-llama-gpu1.service"

# Optimal windows (UTC hours with lowest crypto volatility)
WINDOW_1_START, WINDOW_1_END = 0, 6    # Midnight-6AM UTC
WINDOW_2_START, WINDOW_2_END = 12, 18   # Noon-6PM UTC (overlap with Asian close, pre-Europe)

# Decision thresholds
WIN_RATE_THRESHOLD = 0.65
MIN_NEW_EXAMPLES = 20
MIN_CYCLES_BETWEEN_TRAINS = 50
FG_MIN, FG_MAX = 20, 55


def _read_state() -> Dict:
    """Read current trading state from disk."""
    try:
        with open(STATE_DIR / "high_level_state.json") as f:
            hl = json.load(f)
    except Exception:
        hl = {}
    try:
        with open(STATE_DIR / "agent_state.json") as f:
            agent = json.load(f)
    except Exception:
        agent = {}
    try:
        with open(STATE_DIR / "paper_state.json") as f:
            paper = json.load(f)
    except Exception:
        paper = {}
    try:
        with open(STATE_DIR / "news_cache.json") as f:
            news = json.load(f)
    except Exception:
        news = {}
    return {"hl": hl, "agent": agent, "paper": paper, "news": news}


def _get_last_train() -> Optional[Dict]:
    """Read last training result."""
    try:
        with open(STATE_DIR / "training" / "finetune_status.json") as f:
            return json.load(f)
    except Exception:
        return None


def compute_training_score(state: Dict) -> Dict:
    """Compute a training-desirability score and return detailed reasoning.

    Returns dict with:
      - score: 0.0-1.0 (higher = more desirable to train)
      - can_train: bool (all critical preconditions met)
      - reasons: list of human-readable reasons
      - metrics: raw values used in decision
    """
    reasons = []
    score_components = []

    # ── 1. Win rate check ──
    accuracy = state.get("agent", {}).get("signal_accuracy", {})
    wr = accuracy.get("overall_accuracy_pct", 50) / 100
    if wr < WIN_RATE_THRESHOLD:
        reasons.append(f"✅ Win rate {wr:.0%} < {WIN_RATE_THRESHOLD:.0%} → training needed")
        score_components.append(0.3)
    else:
        reasons.append(f"❌ Win rate {wr:.0%} >= {WIN_RATE_THRESHOLD:.0%} → model fine")

    # ── 2. Data accumulation ──
    try:
        with open(STATE_DIR / "training" / "training_data.jsonl") as f:
            examples = sum(1 for _ in f)
    except Exception:
        examples = 0
    if examples >= MIN_NEW_EXAMPLES:
        reasons.append(f"✅ {examples} examples >= {MIN_NEW_EXAMPLES} → enough data")
        score_components.append(0.25)
    else:
        reasons.append(f"❌ {examples} examples < {MIN_NEW_EXAMPLES} → insufficient data")

    # ── 3. Fear & Greed (volatility proxy) ──
    fg = state.get("news", {}).get("sources", {}).get("fear_greed", {})
    fg_value = fg.get("value", 50)
    if FG_MIN <= fg_value <= FG_MAX:
        reasons.append(f"✅ F&G {fg_value} in [{FG_MIN},{FG_MAX}] → moderate volatility")
        score_components.append(0.2)
    else:
        label = "Extreme Fear" if fg_value < FG_MIN else "Extreme Greed"
        reasons.append(f"❌ F&G {fg_value} = {label} → high opportunity cost")

    # ── 4. Time window ──
    hour = datetime.now(timezone.utc).hour
    in_window_1 = WINDOW_1_START <= hour < WINDOW_1_END
    in_window_2 = WINDOW_2_START <= hour < WINDOW_2_END
    if in_window_1 or in_window_2:
        window = f"{WINDOW_1_START}-{WINDOW_1_END}" if in_window_1 else f"{WINDOW_2_START}-{WINDOW_2_END}"
        reasons.append(f"✅ Hour {hour:02d} UTC in window [{window}] → low volume")
        score_components.append(0.15)
    else:
        reasons.append(f"❌ Hour {hour:02d} UTC outside windows → normal volume")

    # ── 5. Cycle cooldown ──
    cycle = state.get("paper", {}).get("cycle", 0)
    last_train = _get_last_train()
    last_cycle = last_train.get("cycle", 0) if last_train else 0
    cycles_since = cycle - last_cycle
    if cycles_since >= MIN_CYCLES_BETWEEN_TRAINS:
        reasons.append(f"✅ {cycles_since} cycles since last train >= {MIN_CYCLES_BETWEEN_TRAINS}")
        score_components.append(0.1)
    else:
        reasons.append(f"❌ {cycles_since} cycles < {MIN_CYCLES_BETWEEN_TRAINS} → cooldown active")

    # ── 6. Open positions check (warning, not hard block) ──
    positions = state.get("paper", {}).get("positions", [])
    has_positions = len(positions) > 0
    if has_positions:
        reasons.append("⚠️  Positions open — TP/SL active, no new entries during train")

    score = sum(score_components)
    can_train = len(score_components) >= 4  # need win_rate + data + F&G + time window

    return {
        "score": round(score, 2),
        "can_train": can_train,
        "reasons": reasons,
        "metrics": {
            "win_rate": round(wr, 2),
            "examples": examples,
            "fear_greed": fg_value,
            "hour_utc": hour,
            "cycles_since_train": cycles_since,
            "has_positions": has_positions,
        }
    }


def is_idle(state_dir: str = "data") -> bool:
    """Check if the system is idle — training NOT needed and no training in progress.

    Used by the research loop to decide when to run a sweep.
    Returns True if training is not recommended and no lock is held.
    """
    lock = STATE_DIR / "training.lock"
    if lock.exists():
        return False

    state = _read_state()
    decision = compute_training_score(state)
    return not decision["can_train"]


def evaluate() -> Dict:
    """Evaluate whether training should occur now. Saves decision to disk."""
    state = _read_state()
    decision = compute_training_score(state)
    decision["timestamp"] = datetime.now(timezone.utc).isoformat()
    SCHEDULER_STATE.write_text(json.dumps(decision, indent=2))
    return decision


def execute_training(force: bool = False) -> Dict:
    """Stop trading, run fine-tune, restart trading.

    Args:
        force: If True, skip decision check and train immediately.
    """
    result = {"status": "skipped", "duration_s": 0, "error": None}

    if not force:
        decision = evaluate()
        if not decision["can_train"]:
            result["reasons"] = decision["reasons"]
            logger.info(f"Training skipped: score={decision['score']:.2f}")
            return result

    # ── Graceful pause ──
    logger.info("Training scheduled — pausing trading...")
    TRAINING_LOCK.touch()  # signal harness to HOLD mode

    # Wait for the harness to acknowledge (it writes training_hold_ack when
    # it enters HOLD, up to one cycle later — harness cycles are >=60s).
    ack_deadline = time.time() + 240
    while not HOLD_ACK.exists() and time.time() < ack_deadline:
        time.sleep(5)
    if HOLD_ACK.exists():
        logger.info("Harness acknowledged HOLD (training_hold_ack present)")
        HOLD_ACK.unlink(missing_ok=True)
    else:
        logger.warning("No HOLD ack from harness within 240s — proceeding anyway")
        # The scheduler gate (server_quiet on :5802) is the real safety net;
        # the harness reads training.lock itself and will HOLD on its next cycle.

    # ── Drain: wait for in-flight inference to finish ──
    logger.info("Draining in-flight requests on :5802...")
    drain_deadline = time.time() + 120
    while time.time() < drain_deadline:
        if not gpu_activity.server_busy(gpu_activity.GPU1_PORT):
            break
        time.sleep(5)
    if gpu_activity.server_busy(gpu_activity.GPU1_PORT):
        logger.warning("Requests still in flight after 120s drain — proceeding anyway")
    else:
        logger.info("GPU1 quiet — drain complete")

    # ── Stop the serving llama-server (systemd) to free VRAM ──
    t0 = time.time()
    try:
        subprocess.run(["systemctl", "--user", "stop", LLAMA_SERVER_UNIT], timeout=30, check=True)
        time.sleep(5)
        logger.info("llama-server (:5802) stopped via systemd")
    except Exception as e:
        logger.warning(f"llama-server stop failed: {e}")

    # ── VRAM preflight BEFORE loading the model: with the serving server
    #    stopped, the card must still have room for the QLoRA base. ──
    free_gb = gpu_activity.vram_free_gb("gpu1")
    if free_gb < gpu_activity.MIN_GPU1_FREE_GB:
        logger.error(
            f"VRAM preflight FAILED: {free_gb:.1f}GiB free on GPU1 "
            f"(need >= {gpu_activity.MIN_GPU1_FREE_GB}GiB) — aborting training"
        )
        result["status"] = "no_vram"
        result["error"] = f"only {free_gb:.1f}GiB free on GPU1"
        _restore_gpu1_server()
        if TRAINING_LOCK.exists():
            TRAINING_LOCK.unlink()
        result["duration_s"] = round(time.time() - t0, 1)
        return result
    logger.info(f"VRAM preflight OK: {free_gb:.1f}GiB free on GPU1")

    # ── Run fine-tune ──
    try:
        from training.finetune_cycle import run_finetune
        logger.info("Starting fine-tune...")
        ft_result = run_finetune(
            state_dir=str(STATE_DIR),
            data_path=os.environ.get("OPENTRADER_TRAIN_DATA") or None,
        )
        result["ft_result"] = ft_result
        if ft_result.get("status") == "completed":
            result["status"] = "trained"
        else:
            result["status"] = "ft_error"
            result["error"] = ft_result.get("error", "unknown")
    except Exception as e:
        result["status"] = "ft_error"
        result["error"] = str(e)
        logger.error(f"Fine-tune failed: {e}")

    # ── Restart llama-server on the SAME port + alias it had before ──
    try:
        _restore_gpu1_server()
    except Exception as e:
        logger.error(f"llama-server restart failed: {e}")
        result["error"] = (result["error"] or "") + f"; server restart: {e}"

    # ── Resume trading ──
    if TRAINING_LOCK.exists():
        TRAINING_LOCK.unlink()
    logger.info("Trading resumed")

    result["duration_s"] = round(time.time() - t0, 1)
    return result


def _restore_gpu1_server() -> None:
    """Restore the GPU1 serving server on :5802 via systemd.

    The unit opentrader-llama-gpu1.service already carries the serving
    model/alias/ctx (DeepSeek-V4-Pro-Qwen3.5-9B-MTP, ctx 16384, --kv-unified).
    Never launch llama-server by hand — a stray process would fight systemd
    for :5802 and break gpu-sync routing.
    """
    subprocess.run(["systemctl", "--user", "start", LLAMA_SERVER_UNIT], timeout=30, check=False)
    time.sleep(15)  # wait for model to load
    logger.info("llama-server restarted on :5802 via systemd")


# ── CLI ──
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    p = argparse.ArgumentParser()
    p.add_argument("--evaluate", action="store_true", help="Check if training is warranted")
    p.add_argument("--force", action="store_true", help="Train immediately, skip decision")
    p.add_argument("--dry-run", action="store_true", help="Evaluate but don't train")
    args = p.parse_args()

    if args.evaluate or args.dry_run:
        d = evaluate()
        print(f"Score: {d['score']:.2f} | Can train: {d['can_train']}")
        for r in d["reasons"]:
            print(f"  {r}")
        print(f"Metrics: {d['metrics']}")
    elif args.force:
        r = execute_training(force=True)
        print(f"Result: {r['status']} ({r['duration_s']}s)")
    else:
        r = execute_training()
        print(f"Result: {r['status']} ({r['duration_s']}s)")
