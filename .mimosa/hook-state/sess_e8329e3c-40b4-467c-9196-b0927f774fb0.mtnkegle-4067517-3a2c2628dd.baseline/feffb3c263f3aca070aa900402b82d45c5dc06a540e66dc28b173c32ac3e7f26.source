#!/usr/bin/env python3
"""Dev-mode auto-reloader for the trading harness.

Watches opentrader source files for changes. On any .py change:
  1. Kills the running harness (SIGTERM, then SIGKILL after 5s)
  2. Wipes all __pycache__ directories to prevent stale bytecode
  3. Restarts the harness with identical arguments
  4. Catches startup crashes and retries after next file change

Usage:
    python3 tools/dev_reload.py -- python3 harness.py --live --stage 2 ...
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCH_DIRS = [
    PROJECT_ROOT,
    PROJECT_ROOT / "agent",
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "exchange",
    PROJECT_ROOT / "mot",
    PROJECT_ROOT / "rbi",
    PROJECT_ROOT / "risk",
    PROJECT_ROOT / "state",
    PROJECT_ROOT / "tools",
]

EXCLUDE_PATTERNS = [
    "*.pyc",
    "__pycache__",
    ".git",
    ".venv",
    "rocm_venv",
    "data/history",
    "data/training",
    "data/checkpoints",
    ".mypy_cache",
    ".pytest_cache",
]

DEBOUNCE_SECONDS = 2.0
TERM_TIMEOUT = 5.0
RESTART_DELAY = 3.0


def clear_pycache() -> tuple[int, int]:
    """Remove all __pycache__ directories and .pyc files. Returns (dirs_removed, files_removed)."""
    dirs = 0
    files = 0
    for pycache in PROJECT_ROOT.rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(pycache, ignore_errors=True)
            dirs += 1
        except Exception:
            pass
    for pyc in PROJECT_ROOT.rglob("*.pyc"):
        try:
            pyc.unlink(missing_ok=True)
            files += 1
        except Exception:
            pass
    return dirs, files


def kill_process(proc: subprocess.Popen) -> bool:
    """Gracefully terminate a process, force-kill if needed. Returns True if dead."""
    if proc is None or proc.poll() is not None:
        return True

    try:
        proc.terminate()
    except Exception:
        return True

    try:
        proc.wait(timeout=TERM_TIMEOUT)
        return True
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
        return True


def start_harness(cmd: list[str]) -> subprocess.Popen | None:
    """Start the harness subprocess. Returns Popen or None on failure."""
    try:
        env = os.environ.copy()
        # Prevent the harness from inheriting its own watcher
        env["OPENTRADER_RELOAD_ACTIVE"] = "1"
        return subprocess.Popen(
            cmd,
            env=env,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[dev_reload] failed to start harness: {e}", flush=True)
        return None


def watch_and_reload(cmd: list[str]):
    """Main loop: watch files, restart harness on changes."""
    try:
        from watchfiles import watch
    except ImportError:
        print("[dev_reload] watchfiles not installed. Install with: pip install watchfiles", flush=True)
        sys.exit(1)

    proc = None
    last_change = 0.0
    needs_restart = False
    startup_failed = False

    # Build watch directories + exclude patterns
    watch_paths = [str(d) for d in WATCH_DIRS if d.exists()]

    print(f"[dev_reload] watching {len(watch_paths)} directories for .py changes", flush=True)
    print(f"[dev_reload] command: {' '.join(cmd)}", flush=True)

    # Start harness immediately
    dirs, files = clear_pycache()
    print(f"[dev_reload] cleared {dirs} __pycache__ dirs, {files} .pyc files", flush=True)
    proc = start_harness(cmd)
    if proc:
        print(f"[dev_reload] harness started (PID={proc.pid})", flush=True)
    else:
        print("[dev_reload] harness failed to start — will retry on next change", flush=True)
        startup_failed = True

    try:
        for changes in watch(*watch_paths, watch_filter=None, debounce=DEBOUNCE_SECONDS * 1000):
            # Filter: only .py files, exclude patterns
            py_changes = []
            for _, path_str in changes:
                # Skip excluded patterns
                path_lower = path_str.lower()
                if any(pat.replace("*", "") in path_lower for pat in
                       ["__pycache__", ".pyc", ".git", ".venv", "rocm_venv",
                        "data/history", "data/training", "data/checkpoints"]):
                    continue
                if path_str.endswith(".py"):
                    py_changes.append(path_str)

            if not py_changes:
                continue

            now = time.time()
            if now - last_change < DEBOUNCE_SECONDS:
                continue
            last_change = now

            changed_short = [os.path.relpath(p, str(PROJECT_ROOT)) for p in py_changes[:5]]
            print(f"[dev_reload] {time.strftime('%H:%M:%S')} — {len(py_changes)} file(s) changed: {', '.join(changed_short)}", flush=True)

            # Kill current harness
            if proc and proc.poll() is None:
                print(f"[dev_reload] stopping harness (PID={proc.pid})...", flush=True)
                kill_process(proc)

            # Wipe bytecode cache
            dirs, files = clear_pycache()
            if dirs > 0 or files > 0:
                print(f"[dev_reload] cleared {dirs} __pycache__ dirs, {files} .pyc files", flush=True)

            # Brief pause to let OS release sockets
            time.sleep(RESTART_DELAY)

            # Restart
            proc = start_harness(cmd)
            if proc:
                print(f"[dev_reload] harness restarted (PID={proc.pid})", flush=True)
                startup_failed = False
            else:
                print("[dev_reload] harness failed to start — will retry on next change", flush=True)
                startup_failed = True

    except KeyboardInterrupt:
        print("\n[dev_reload] shutting down...", flush=True)
    finally:
        if proc and proc.poll() is None:
            print(f"[dev_reload] stopping harness (PID={proc.pid})", flush=True)
            kill_process(proc)
        print("[dev_reload] stopped", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Dev-mode auto-reloader")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="Command to run (e.g.: python3 harness.py --live)")
    args = parser.parse_args()

    if not args.command:
        print("[dev_reload] no command specified. Usage: python3 tools/dev_reload.py -- <command>",
              flush=True)
        sys.exit(1)

    watch_and_reload(args.command)


if __name__ == "__main__":
    main()
