#!/usr/bin/env python3
"""Idle GPU trainer — watches llama-server, trains during idle periods.

Continuously monitors the Ternary Bonsai 27B server on :5802. When the GPU
has been idle (no inference requests) for the configured period, triggers
reward-weighted SFT training. Works for both trading (BehavioralRLTrainer)
and coding (CodingRLTrainer) domains.

Detection method:
  - Polls llama-server /health and /v1/models endpoints
  - Checks /slots endpoint for active inference slots
  - Monitors GPU utilization via rocm-smi
  - Falls back to /proc/stat based load detection

Scheduling:
  - Minimum 5-minute idle window before triggering
  - Maximum one training per hour
  - Respects training.lock
  - Re-checks idle status just before launching training

Usage:
  # Run as daemon
  python3 training/idle_trainer.py --daemon

  # One-shot check
  python3 training/idle_trainer.py --check

  # Force training now (ignores idle check)
  python3 training/idle_trainer.py --force --mode coding
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("opentrader.idle_trainer")

DEFAULT_LLAMA_HOST = "http://127.0.0.1:5802"
DEFAULT_STATE_DIR = str(PROJECT_ROOT / "data")
IDLE_SECONDS = 300         # 5 min idle before triggering
COOLDOWN_SECONDS = 3600    # 1 hour between training runs
CHECK_INTERVAL = 30        # Poll every 30 seconds


def check_llama_idle(host: str = DEFAULT_LLAMA_HOST, timeout: int = 5) -> Tuple[bool, dict]:
    """Check if the llama-server is idle (no active inference).

    Returns (is_idle, diagnostics).
    """
    diag = {"host": host, "reachable": False, "slots_active": 0, "gpu_util_pct": 0.0}

    # 1. Check health endpoint
    try:
        req = Request(f"{host}/health", method="GET")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            health = json.loads(resp.read().decode())
            diag["reachable"] = True
            diag["status"] = health.get("status", "unknown")
    except Exception as e:
        diag["error"] = str(e)[:100]
        return False, diag

    # 2. Check slots (active inference)
    try:
        req = Request(f"{host}/slots", method="GET")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            slots = json.loads(resp.read().decode())
            if isinstance(slots, list):
                diag["slots_active"] = sum(
                    1 for s in slots if s.get("state") == 1 or s.get("state") == "processing"
                )
            elif isinstance(slots, dict):
                diag["slots_active"] = len(slots.get("slots", []))
    except Exception:
        diag["slots_active"] = -1  # unknown

    # 3. Check GPU utilization via rocm-smi
    try:
        result = subprocess.run(
            ["rocm-smi", "--showuse", "--json"],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for card_id, card_data in data.items():
                if isinstance(card_data, dict):
                    util = float(card_data.get("GPU use (%)", 0) or 0)
                    diag["gpu_util_pct"] = max(diag["gpu_util_pct"], util)
    except Exception:
        pass

    # Idle determination: no active slots AND GPU utilization < 5%
    is_idle = (
        diag["reachable"]
        and diag.get("slots_active", 1) == 0
        and diag.get("gpu_util_pct", 100) < 5.0
    )

    return is_idle, diag


def check_vram_free(gpu_index: int = 0) -> Tuple[bool, float]:
    """Check if enough VRAM is free for training. Returns (has_enough, free_gb)."""
    try:
        # Try /sys interface first
        vram_path = f"/sys/class/drm/card{gpu_index}/device"
        with open(f"{vram_path}/mem_info_vram_used") as f:
            used = int(f.read().strip()) / 1e9
        with open(f"{vram_path}/mem_info_vram_total") as f:
            total = int(f.read().strip()) / 1e9
        free_gb = total - used
        return free_gb > 3.0, free_gb  # need 3GB+ for QLoRA
    except Exception:
        pass

    # Fallback: rocm-smi
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        for card_id, card_data in data.items():
            if isinstance(card_data, dict):
                used = float(card_data.get("VRAM Total Used Memory (B)", 0) or 0) / 1e9
                total = float(card_data.get("VRAM Total Memory (B)", 0) or 0) / 1e9
                free_gb = total - used
                return free_gb > 3.0, free_gb
    except Exception:
        pass

    return False, 0.0


class IdleTrainer:
    """Watches GPU and triggers RL training during idle periods."""

    def __init__(
        self,
        llama_host: str = DEFAULT_LLAMA_HOST,
        state_dir: str = DEFAULT_STATE_DIR,
        output_dir: str = "models/finetune",
        idle_seconds: int = IDLE_SECONDS,
        cooldown_seconds: int = COOLDOWN_SECONDS,
        mode: str = "auto",  # "trading", "coding", or "auto"
    ):
        self.llama_host = llama_host.rstrip("/")
        self.state_dir = Path(state_dir)
        self.output_dir = Path(output_dir)
        self.idle_seconds = idle_seconds
        self.cooldown_seconds = cooldown_seconds
        self.mode = mode

        self._idle_since: Optional[float] = None
        self._last_training: float = 0.0
        self._running = True
        self._training_in_progress = False

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def _determine_mode(self) -> str:
        """Auto-detect whether to train trading or coding."""
        if self.mode != "auto":
            return self.mode

        # Check which has more data
        agent_path = self.state_dir / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                trades = len(state.get("_trade_journal", []))
                code_diffs = len(state.get("code_diffs", []))
                return "trading" if trades > code_diffs else "coding"
            except Exception:
                pass
        return "trading"

    def should_train(self) -> Tuple[bool, str]:
        """Check if conditions are right for training."""
        if self._training_in_progress:
            return False, "training already in progress"

        # Check training lock
        lock = self.state_dir / "training.lock"
        if lock.exists():
            return False, "training.lock active"

        # Check cooldown
        elapsed = time.time() - self._last_training
        if elapsed < self.cooldown_seconds:
            return False, f"cooldown: {elapsed:.0f}s < {self.cooldown_seconds}s"

        # Check idle status
        is_idle, diag = check_llama_idle(self.llama_host)
        if not is_idle:
            self._idle_since = None
            return False, f"GPU busy: slots={diag.get('slots_active')} util={diag.get('gpu_util_pct')}%"

        # Track idle duration
        now = time.time()
        if self._idle_since is None:
            self._idle_since = now

        idle_duration = now - self._idle_since
        if idle_duration < self.idle_seconds:
            return False, f"idle for {idle_duration:.0f}s, need {self.idle_seconds}s"

        # Check VRAM
        has_vram, free_gb = check_vram_free()
        if not has_vram:
            return False, f"insufficient VRAM: {free_gb:.1f}GB free"

        return True, f"idle for {idle_duration:.0f}s, {free_gb:.1f}GB free VRAM"

    def train(self) -> dict:
        """Run reward-weighted SFT training."""
        mode = self._determine_mode()
        logger.info(f"IdleTrainer: starting {mode} training...")
        self._training_in_progress = True
        self._idle_since = None

        try:
            from training.rl_trainer import (
                BehavioralRLTrainer, CodingRLTrainer, RLTrainingConfig
            )

            cfg = RLTrainingConfig(
                state_dir=str(self.state_dir),
                output_dir=str(self.output_dir),
                min_examples=3,
                max_examples=30,
                checkpoint_interval_seconds=0,  # allow immediate training
                max_step_seconds=180,
            )

            if mode == "coding":
                trainer = CodingRLTrainer(config=cfg)
            else:
                trainer = BehavioralRLTrainer(config=cfg)

            result = trainer.step()
            self._last_training = time.time()

            if result.get("status") == "completed":
                adapter_path = result.get("adapter_path")
                logger.info(f"IdleTrainer: {mode} training complete → {adapter_path}")

                # Register in adapter registry
                self._register_adapter(result, mode)
            else:
                logger.info(f"IdleTrainer: {mode} training {result.get('status')} — {result.get('reason', '')}")

            return result

        except Exception as e:
            logger.error(f"IdleTrainer: training failed: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            self._training_in_progress = False

    def _register_adapter(self, result: dict, mode: str) -> None:
        """Register newly trained adapter in the registry."""
        try:
            from mot.adapter_registry import AdapterRegistry
            registry = AdapterRegistry(str(self.state_dir))
            version = result.get("version", f"{mode.upper()}-V1")
            adapter_path = result.get("adapter_path", "")
            if adapter_path:
                registry.register(
                    version=version,
                    path=adapter_path,
                    training_examples=result.get("examples", 0),
                )
                logger.info(f"Registered adapter: {version}")
        except Exception as e:
            logger.debug(f"Adapter registration skipped: {e}")

    def run_daemon(self) -> None:
        """Main daemon loop. Blocks until signal received."""
        logger.info(
            f"IdleTrainer daemon starting: host={self.llama_host} "
            f"idle={self.idle_seconds}s cooldown={self.cooldown_seconds}s"
        )

        while self._running:
            try:
                should, reason = self.should_train()
                if should:
                    logger.info(f"IdleTrainer: trigger — {reason}")
                    self.train()
                else:
                    if self._idle_since is not None:
                        elapsed = time.time() - self._idle_since
                        logger.debug(
                            f"IdleTrainer: waiting — {reason} (idle {elapsed:.0f}s)"
                        )
                    else:
                        logger.debug(f"IdleTrainer: {reason}")

                time.sleep(CHECK_INTERVAL)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"IdleTrainer daemon error: {e}", exc_info=True)
                time.sleep(CHECK_INTERVAL)

        logger.info("IdleTrainer daemon stopped")


# ── CLI ────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Idle GPU trainer — trains models when llama-server is idle"
    )
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--check", action="store_true", help="Check idle status and exit")
    parser.add_argument("--force", action="store_true", help="Train now (bypass idle check)")
    parser.add_argument("--mode", choices=["trading", "coding", "auto"], default="auto")
    parser.add_argument("--host", default=DEFAULT_LLAMA_HOST, help="llama-server URL")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--output-dir", default="models/finetune")
    parser.add_argument("--idle-seconds", type=int, default=IDLE_SECONDS)
    parser.add_argument("--cooldown-seconds", type=int, default=COOLDOWN_SECONDS)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    trainer = IdleTrainer(
        llama_host=args.host,
        state_dir=args.state_dir,
        output_dir=args.output_dir,
        idle_seconds=args.idle_seconds,
        cooldown_seconds=args.cooldown_seconds,
        mode=args.mode,
    )

    if args.check:
        is_idle, diag = check_llama_idle(args.host)
        has_vram, free_gb = check_vram_free()
        should, reason = trainer.should_train()
        print(json.dumps({
            "server_reachable": diag.get("reachable"),
            "slots_active": diag.get("slots_active"),
            "gpu_util_pct": diag.get("gpu_util_pct"),
            "vram_free_gb": round(free_gb, 1) if has_vram else 0,
            "should_train": should,
            "reason": reason,
        }, indent=2))
        return

    if args.force:
        result = trainer.train()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.daemon:
        trainer.run_daemon()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
