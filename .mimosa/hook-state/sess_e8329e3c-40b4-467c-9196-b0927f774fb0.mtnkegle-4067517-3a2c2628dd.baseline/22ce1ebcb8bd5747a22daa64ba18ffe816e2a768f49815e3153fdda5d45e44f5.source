#!/usr/bin/env python3
"""Training Watchdog — continuous improvement loop for Opentrader.

Runs as a background daemon. Periodically:
  1. Rebuilds training data from cycle history + trade journal
  2. Launches LoRA training when new data exceeds threshold
  3. Saves adapters to models/finetune/{version}/adapter/

The harness auto-detects new adapters via _check_adapter_lifecycle()
and can activate them (requires llama-server to be idle on GPU).

Usage:
    rocm_venv/bin/python3 training/watchdog.py \
        --data data --output models/finetune \
        --min-new-examples 50 --check-interval 300

If --background flag is set, runs as daemon until trading stops.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("opentrader.watchdog")


def count_examples(history_dir: Path) -> int:
    """Count how many cycle files exist as a proxy for available training data."""
    if not history_dir.exists():
        return 0
    return len([f for f in os.listdir(str(history_dir))
                if f.startswith("cycle_") and f.endswith(".json")])


def get_last_training_count(status_file: Path) -> int:
    """Read the example count from last training run."""
    if not status_file.exists():
        return 0
    try:
        data = json.loads(status_file.read_text())
        return data.get("examples_count", 0)
    except Exception:
        return 0


def write_status(status_file: Path, version: str, examples_count: int,
                 result: dict = None):
    """Write training status after a run."""
    status = {
        "status": "success" if result else "pending",
        "version": version,
        "last_run": datetime.utcnow().isoformat() + "Z",
        "examples_count": examples_count,
    }
    if result:
        status.update(result)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status, indent=2))


def find_rocm_python() -> Optional[str]:
    """Find the ROCm venv Python interpreter."""
    candidates = [
        "/home/mrc/rocm_venv/bin/python3",
        "/home/mrc/rocm_venv/bin/python",
    ]
    for path in candidates:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return sys.executable


def launch_training(data_file: str, output: str, version: str,
                    rocm_python: str, timeout: int = 900) -> Optional[dict]:
    """Launch train_rocm.py as a subprocess and wait for completion."""
    train_script = Path(__file__).parent / "train_rocm.py"
    cmd = [
        rocm_python, str(train_script),
        "--data", data_file,
        "--output", os.path.join(output, version),
        "--no-4bit",
        "--epochs", "2",
    ]

    logger.info(f"Launching training: {' '.join(cmd)}")
    start = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).parent.parent),
        )
        elapsed = time.time() - start

        if proc.returncode == 0:
            logger.info(f"Training succeeded in {elapsed:.0f}s")
            return {
                "elapsed_s": round(elapsed, 1),
                "exit_code": 0,
            }
        else:
            logger.warning(
                f"Training failed (exit {proc.returncode}): "
                f"{proc.stderr[-300:] if proc.stderr else 'no stderr'}"
            )
            return {
                "elapsed_s": round(elapsed, 1),
                "exit_code": proc.returncode,
                "error": (proc.stderr or "unknown error")[-500:],
            }

    except subprocess.TimeoutExpired:
        logger.warning(f"Training timed out after {timeout}s")
        return {"elapsed_s": timeout, "exit_code": -1, "error": "timeout"}
    except FileNotFoundError:
        logger.error(f"Training script not found: {train_script}")
        return {"exit_code": -2, "error": "train_rocm.py not found"}


def main():
    parser = argparse.ArgumentParser(description="Opentrader Training Watchdog")
    parser.add_argument("--data", default="data",
                        help="State directory with cycle history")
    parser.add_argument("--output", default="models/finetune",
                        help="Output directory for adapters")
    parser.add_argument("--min-new-examples", type=int, default=50,
                        help="Minimum new examples to trigger retraining")
    parser.add_argument("--check-interval", type=int, default=300,
                        help="Seconds between training checks")
    parser.add_argument("--timeout", type=int, default=900,
                        help="Max seconds for each training run")
    parser.add_argument("--background", action="store_true",
                        help="Run continuously in background")
    parser.add_argument("--once", action="store_true",
                        help="Run one training check and exit")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    state_dir = Path(args.data)
    output_dir = Path(args.output)
    history_dir = state_dir / "history"
    trade_file = state_dir / "trade_journal.jsonl"
    # Fallback: count trade references from paper_state.json
    if not trade_file.exists():
        trade_file = state_dir / "paper_state.json"
    status_file = output_dir / "watchdog_status.json"

    rocm_python = find_rocm_python()
    if not rocm_python:
        logger.error("No ROCm Python found. Install ROCm PyTorch first.")
        sys.exit(1)
    logger.info(f"Using ROCm Python: {rocm_python}")

    version_counter = 1

    while True:
        logger.debug(f"Checking for new training data...")

        # Count available trades/examples
        try:
            current_count = 0
            if trade_file.exists() and trade_file.suffix == ".json":
                data = json.loads(trade_file.read_text())
                if isinstance(data, dict):
                    current_count = len(data.get("trades", [])) or len(data.get("fills", []))
            if not current_count:
                # Count cycle history files as proxy
                if history_dir.exists():
                    current_count = len([f for f in os.listdir(str(history_dir))
                                        if f.startswith("cycle_") and f.endswith(".json")])
            last_count = get_last_training_count(status_file)
            new_examples = current_count - last_count

            logger.info(
                f"Trade lines: {current_count}, last trained: {last_count}, "
                f"new: {new_examples} (threshold: {args.min_new_examples})"
            )

            if new_examples < args.min_new_examples:
                if args.once:
                    logger.info(
                        f"Not enough new examples ({new_examples}/{args.min_new_examples}). "
                        "Use --background for continuous monitoring."
                    )
                    break
                logger.debug(
                    f"Insufficient new data ({new_examples}/{args.min_new_examples}), "
                    f"sleeping {args.check_interval}s..."
                )
                time.sleep(args.check_interval)
                continue

            # Rebuild training data
            logger.info(f"Rebuilding training data ({current_count} cycle files)...")
            data_file = str(output_dir / "training" / "training_data_current.jsonl")
            os.makedirs(os.path.dirname(data_file), exist_ok=True)

            try:
                from training.legacy_data_builder import build_legacy_training_data
                build_legacy_training_data(
                    state_dir=str(state_dir),
                    output_path=data_file,
                    balance="equal",
                )
                if os.path.getsize(data_file) > 0:
                    with open(data_file) as f:
                        examples = [json.loads(l) for l in f if l.strip()]
                    logger.info(f"Built dataset: {len(examples)} examples → {data_file}")
                else:
                    examples = []
            except Exception as e:
                logger.warning(f"Data builder failed: {e}")
                if args.once:
                    break
                time.sleep(args.check_interval)
                continue

            # Launch training
            version = f"Ptolemy-{version_counter}"
            logger.info(f"Launching training run {version} ({len(examples) if examples else 0} examples)...")

            result = launch_training(
                data_file=data_file,
                output=str(output_dir),
                version=version,
                rocm_python=rocm_python,
                timeout=args.timeout,
            )

            write_status(status_file, version, current_count, result)
            version_counter += 1

            if result and result.get("exit_code") == 0:
                logger.info(f"Training complete: adapter saved to {output_dir}/{version}/")
            else:
                logger.warning(f"Training failed: {result}")

        except Exception as e:
            logger.error(f"Watchdog error: {e}")

        if args.once:
            break

        logger.info(f"Sleeping {args.check_interval}s until next check...")
        time.sleep(args.check_interval)


if __name__ == "__main__":
    main()
