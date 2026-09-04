#!/usr/bin/env python3
"""OpenTrader Operate-phase watchdog — cron-safe, idempotent, no VRAM use.

Runs every 5 min via cron. Detects and recovers:
  - Stale flock locks (eval_gate)
  - SIGSTOP'd harness (stuck eval freed VRAM then died)
  - Dead harness (process crashed)
  - Stale ATDL scheduler (Intent bucket dead)
  - Orphaned llama-server on :5805

Writes data/health.json for TUI/dashboard consumption.
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path("/home/mrc/opentrader")
PYTHON = "/home/mrc/venv/bin/python3"
HEALTH = PROJECT / "data" / "health.json"
LOCKFILE = Path("/tmp/opentrader_eval_gate.lock")
SCHEDULER_STATE = PROJECT / "data" / "scheduler_state.json"
HARNESS_CMD = PROJECT / "data" / "harness_cmd.txt"
LOG_FILE = PROJECT / "data" / "watchdog.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchdog] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("watchdog")


def _pgrep(pattern: str) -> list:
    """Return list of PIDs matching pattern. Empty if none."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [int(p) for p in result.stdout.strip().split("\n") if p]
    except Exception:
        pass
    return []


def check_lock() -> dict:
    """3a. Stale flock lock stewardship."""
    result = {"eval_lock": "absent"}
    if not LOCKFILE.exists():
        return result

    # Check if any process holds the lock
    holders = []
    try:
        r = subprocess.run(
            ["fuser", str(LOCKFILE)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for part in r.stdout.strip().split():
            try:
                holders.append(int(part))
            except ValueError:
                pass
    except Exception:
        pass

    if not holders:
        # Stale — check mtime
        try:
            mtime = LOCKFILE.stat().st_mtime
            age_h = (time.time() - mtime) / 3600
            if age_h > 2:
                LOCKFILE.unlink(missing_ok=True)
                result["eval_lock"] = "stale_cleared"
                logger.info(f"Stale lock cleared (age={age_h:.1f}h)")
            else:
                result["eval_lock"] = "held_no_holder"
                logger.warning(f"Lock has no holder but is fresh ({age_h:.1f}h)")
        except OSError:
            result["eval_lock"] = "absent"
    else:
        result["eval_lock"] = "held"
    return result


def check_harness() -> dict:
    """3b. SIGSTOP'd harness recovery. 3c. Dead harness restart (systemd).

    Since the harness now runs as a systemd user unit (Restart=always),
    the watchdog no longer restarts it directly — it only resumes a
    SIGSTOP'd harness (eval gate pauses it to free VRAM).
    """
    result = {"harness_state": "absent", "harness_pid": None, "harness_restart": None}

    pids = _pgrep("harness.py")
    if not pids:
        # 3c. Dead harness — systemd Restart= handles relaunching. Only
        # report; do not duplicate-restart (would fight systemd).
        result["harness_state"] = "dead"
        result["harness_restart"] = "systemd-managed"
        return result

    # Harness is alive — check for SIGSTOP'd state
    for pid in pids:
        try:
            status = (Path("/proc") / str(pid) / "status").read_text()
            if "T (stopped)" in status or "t (tracing" in status:
                os.kill(pid, 18)  # SIGCONT
                result["harness_state"] = "stopped_and_resumed"
                result["harness_pid"] = pid
                logger.info(f"Harness PID {pid} was SIGSTOP'd — resumed")
                return result
        except OSError:
            pass

    result["harness_state"] = "running"
    result["harness_pid"] = pids[0]
    return result


def check_scheduler() -> dict:
    """3d. Scheduler staleness."""
    result = {"scheduler": "absent"}
    if not SCHEDULER_STATE.exists():
        return result

    try:
        mtime = SCHEDULER_STATE.stat().st_mtime
        age_h = (time.time() - mtime) / 3600
    except OSError:
        return result

    if age_h > 12:
        sp = _pgrep("harness_scheduler")
        if sp:
            result["scheduler"] = "running"
        else:
            logger.info(f"Scheduler stale ({age_h:.1f}h) — triggering auto tick")
            try:
                subprocess.run(
                    [PYTHON, "-m", "training.harness_scheduler", "auto"],
                    cwd=str(PROJECT),
                    capture_output=True,
                    timeout=600,
                )
                result["scheduler"] = "stale_triggered"
                logger.info("Scheduler auto tick completed")
            except subprocess.TimeoutExpired:
                result["scheduler"] = "failed"
                logger.warning("Scheduler auto tick timed out")
            except Exception as e:
                result["scheduler"] = "failed"
                logger.warning(f"Scheduler auto tick error: {e}")
    else:
        result["scheduler"] = "fresh"
    return result


def check_eval_server() -> dict:
    """3e. Orphaned eval llama-server on :5805."""
    result = {"eval_server": "clean"}
    srv_pids = _pgrep("llama-server.*5805")
    if not srv_pids:
        return result

    eval_pids = _pgrep("eval_gate.sh")
    if not eval_pids:
        for pid in srv_pids:
            try:
                os.kill(pid, 9)
                result["eval_server"] = f"orphan_killed:{pid}"
                logger.info(f"Orphaned eval server killed: PID {pid}")
            except OSError:
                pass
    else:
        result["eval_server"] = "serving"
    return result


def write_health(checks: dict) -> None:
    """3f. Write health.json atomically."""
    health = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "warnings": [],
    }
    tmp = HEALTH.with_suffix(".tmp")
    tmp.write_text(json.dumps(health, indent=2))
    os.replace(tmp, HEALTH)


def main():
    results = {}
    results.update(check_lock())
    results.update(check_harness())
    results.update(check_scheduler())
    results.update(check_eval_server())
    write_health(results)
    for k, v in results.items():
        logger.info(f"  {k}: {v}")
    logger.info("Watchdog tick complete")


if __name__ == "__main__":
    main()
