#!/usr/bin/env python3
"""Autonomous GPU scheduler v3 — two-stream request-activity gating (#114).

Fixes from v2 (journal gate, one-task-per-pass):

- Activity signal is a LIVE PORT PROBE on the actual serving unit
  (setup_search/gpu_activity.py), not the journal — the journal source is
  masked/disabled, so the v2 gate could never fire.
- Two independent streams: GPU0 gate and GPU1 gate are evaluated separately,
  and a GPU1 task does NOT block GPU0 tasks (removed the one-task-per-pass
  `break`). Each stream feeds its own highest-priority pending task.
- VRAM preflight before any GPU task (never load into an oversubscribed card).
- GPU1 tasks (training) get HOLD-ack coordination: the harness is expected to
  acknowledge training.lock (writes data/training_hold_ack) before the task
  is allowed to stop the serving server.

- GPU0 tasks (sentiment FinBERT / small ports): safe when the qwen server
  (:5803) has no processing slot; paused on activity, resumed when quiet.
- GPU1 tasks (Ptolemy retrain): start only in a quiet gap; the trainer
  itself drains + restores the serving server.
- CPU tasks (value-head): always run.

Retry policy: 2 retries then `failed`. `--dry-run` validates the signals
without running tasks.
"""

import argparse
import json
import logging
import signal
import subprocess
import time
from pathlib import Path

from setup_search import gpu_activity

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "gpu_scheduler"
MANIFEST = Path(__file__).resolve().parent / "auto_tasks.json"
HOLD_ACK = PROJECT / "data" / "training_hold_ack"
POLL_SEC = 10

OUT.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(OUT / "scheduler.log"),
                              logging.StreamHandler()])
log = logging.getLogger("gpu_scheduler")


def load_manifest():
    return json.loads(MANIFEST.read_text())["tasks"]


def save_manifest(tasks):
    MANIFEST.write_text(json.dumps({"tasks": tasks}, indent=1))


def task_safe(task) -> str:
    """Return '' if safe to run, else the reason it's gated.

    GPU0 gate (#47/#50 operating model): GPU0 no longer serves a llama-server
    (qwen masked) — its workload IS the research/arsenal task. The gate is
    VRAM-headroom only; the old `server_busy(:5803)` check is stale and would
    fail-closed forever (nothing listens on 5803).
    GPU1 gate stays fully fail-closed: live LLM serving on :5802 must never be
    disturbed by a task.
    """
    gpu = task.get("gpu", "cpu")
    if gpu == "gpu0":
        if gpu_activity.vram_free_gb("gpu0") < 0.5:
            return "GPU0 VRAM headroom too small (<0.5GiB)"
        return ""
    if gpu == "gpu1":
        if gpu_activity.vram_free_gb("gpu1") < gpu_activity.MIN_GPU1_FREE_GB:
            return f"GPU1 VRAM headroom too small (<{gpu_activity.MIN_GPU1_FREE_GB}GiB)"
        return "" if not gpu_activity.server_busy(gpu_activity.GPU1_PORT) \
            else "GPU1 busy (processing slot on :5802)"
    return ""


def _wait_hold_ack(task, timeout=180) -> bool:
    """GPU1 training: wait until the harness acknowledges training.lock."""
    if task.get("gpu") != "gpu1":
        return True
    start = time.time()
    while time.time() - start < timeout:
        if HOLD_ACK.exists():
            age = time.time() - HOLD_ACK.stat().st_mtime
            if age < 180:
                return True
        time.sleep(POLL_SEC)
    return False


def _spawn(task) -> subprocess.Popen:
    return subprocess.Popen(task["cmd"], shell=True, cwd=str(PROJECT),
                            stdout=open(OUT / f"{task['name']}.out", "w"),
                            stderr=subprocess.STDOUT)


def run_task(task, dry_run=False) -> str:
    """Legacy synchronous wrapper (used by tests); returns status."""
    if dry_run:
        return "dry-run-ok"
    if task.get("gpu") == "gpu1" and not _wait_hold_ack(task):
        log.warning(f"  {task['name']}: no HOLD ack from harness — aborting")
        return "no-hold-ack"
    proc = _spawn(task)
    paused = False
    start = time.time()
    busy_port = _busy_port(task)
    while proc.poll() is None:
        time.sleep(POLL_SEC)
        paused = _pause_or_resume(task, proc, busy_port, paused)
        if time.time() - start > task.get("timeout", 3600):
            proc.kill()
            return "timed_out"
    rc = proc.returncode
    if paused:
        try:
            proc.send_signal(signal.SIGCONT)
        except Exception:
            pass
    return "done" if rc == 0 else "failed"


def _busy_port(task):
    """Serving port whose activity gates a running task.

    GPU0 has no serving port under the #50 operating model (qwen masked) —
    nothing to pause against; the arsenal task runs to completion. GPU1
    pauses/resumes around live LLM traffic on :5802.
    """
    gpu = task.get("gpu", "cpu")
    if gpu == "gpu1":
        return gpu_activity.GPU1_PORT
    return None


def _pause_or_resume(task, proc, busy_port, paused) -> bool:
    if busy_port is None:
        return paused
    if gpu_activity.server_busy(busy_port) and not paused:
        proc.send_signal(signal.SIGSTOP)
        log.info(f"  {task['name']}: {task.get('gpu')} active -> paused")
        return True
    if paused and not gpu_activity.server_busy(busy_port):
        proc.send_signal(signal.SIGCONT)
        log.info(f"  {task['name']}: {task.get('gpu')} quiet -> resumed")
        return False
    return paused


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate signals + report what would run, run nothing")
    ap.add_argument("--once", action="store_true", help="Run one pass then exit")
    ap.add_argument("--timeout-s", type=float, default=0.0,
                    help="Exit after this many seconds (0 = run forever)")
    args = ap.parse_args()

    if args.dry_run:
        print(f"GPU0 (:5803) busy={gpu_activity.server_busy(gpu_activity.GPU0_PORT)} "
              f"vram_free={gpu_activity.vram_free_gb('gpu0'):.1f}GiB")
        print(f"GPU1 (:5802) busy={gpu_activity.server_busy(gpu_activity.GPU1_PORT)} "
              f"vram_free={gpu_activity.vram_free_gb('gpu1'):.1f}GiB")
        for t in load_manifest():
            print(f"  {t['name']} (gpu={t.get('gpu')}): "
                  f"{task_safe(t) or 'would run'}")
        return

    log.info("GPU scheduler v3 started (two-stream port-probe gating)")
    running: dict[str, dict] = {}  # gpu -> {"task": name, "proc": p, "paused": b, "start": t}
    start_wall = time.time()
    while True:
        try:
            tasks = {t["name"]: t for t in load_manifest()}

            # 1. Monitor running streams: poll, pause/resume, reap.
            for gpu in list(running):
                entry = running[gpu]
                proc = entry["proc"]
                task = tasks.get(entry["task"])
                if task is None:
                    log.warning(f"{entry['task']} vanished from manifest — reaping")
                    proc.kill()
                    del running[gpu]
                    continue
                if proc.poll() is None:
                    entry["paused"] = _pause_or_resume(
                        task, proc, _busy_port(task), entry["paused"])
                    if time.time() - entry["start"] > task.get("timeout", 3600):
                        proc.kill()
                        entry["done"] = "timed_out"
                    continue
                # finished — settle into the manifest
                entry["done"] = entry.get("done") or \
                    ("done" if proc.returncode == 0 else "failed")
                if entry["paused"]:
                    try:
                        proc.send_signal(signal.SIGCONT)
                    except Exception:
                        pass
                task["status"] = entry["done"]
                if entry["done"] == "failed":
                    task["retries"] = task.get("retries", 0) + 1
                    if task["retries"] < 2:
                        task["status"] = "pending"
                elif entry["done"] == "done" and task.get("recurring"):
                    task["status"] = "pending"
                    task["cooldown_until"] = time.time() + task.get("cooldown_sec", 1800)
                task["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                save_manifest(list(tasks.values()))
                log.info(f"DONE {task['name']}: {entry['done']} "
                         f"(retries={task.get('retries', 0)})")
                del running[gpu]

            # 2. Feed free streams — independent GPU0/GPU1/CPU gates.
            for task in sorted(tasks.values(), key=lambda t: t.get("priority", 99)):
                if task.get("status") not in ("pending", "failed"):
                    continue
                if task.get("retries", 0) >= 2:
                    continue
                if task.get("cooldown_until", 0) > time.time():
                    continue
                gpu = task.get("gpu", "cpu")
                if gpu in running:
                    continue  # stream already has an active task
                why = task_safe(task)
                if why:
                    log.debug(f"gated: {task['name']} ({why})")
                    continue
                if task.get("gpu") == "gpu1":
                    # Handshake: signal the harness (training.lock), then wait
                    # for its HOLD acknowledgment before spawning training.
                    gpu_activity.logger.info(f"{task['name']}: touching training.lock")
                    (PROJECT / "data" / "training.lock").touch()
                    if not _wait_hold_ack(task):
                        (PROJECT / "data" / "training.lock").unlink(missing_ok=True)
                        task["status"] = "failed"
                        task["retries"] = task.get("retries", 0) + 1
                        save_manifest(list(tasks.values()))
                        log.warning(f"HOLD-ACK MISSING: {task['name']} marked failed")
                        continue
                    (PROJECT / "data" / "training_hold_ack").unlink(missing_ok=True)
                log.info(f"RUN {task['name']} (gpu={gpu})")
                task["status"] = "running"
                save_manifest(list(tasks.values()))
                running[gpu] = {
                    "task": task["name"], "proc": _spawn(task),
                    "paused": False, "start": time.time(),
                }
            if args.once:
                return

            if args.timeout_s > 0 and time.time() - start_wall >= args.timeout_s:
                log.info(f"Wall-clock budget {args.timeout_s}s reached — exiting")
                return

            time.sleep(POLL_SEC)
        except Exception as e:
            log.error(f"scheduler error: {e}")
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
