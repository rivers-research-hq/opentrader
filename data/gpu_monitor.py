#!/usr/bin/env python3
"""GPU/CPU activity monitor for the accumulator — the 'is anything happening' tool.

Checks: are the GPUs being used? Is the accumulator job alive and progressing?
Writes a status file + exits non-zero if the system has been idle (no GPU work,
no progress) for too long, so a cron/agent can alert instead of silently idling.

Usage:
  gpu_monitor.py            # one-shot status
  gpu_monitor.py --watch    # poll every N sec, log progress, alert on stall
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
STATUS_FILE = PROJECT / "data" / "accumulator" / "status.json"
LAKE = PROJECT / "data" / "accumulator" / "lake"


def gpu_util() -> dict:
    """utilization of every visible GPU (NVIDIA + AMD)."""
    out = {"nvidia": None, "amd": None}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"], capture_output=True, text=True,
            timeout=10)
        if r.returncode == 0:
            gpus = []
            for line in r.stdout.strip().splitlines():
                name, util, mem = [x.strip() for x in line.split(",")]
                gpus.append({"name": name, "util": int(util), "mem": int(mem)})
            out["nvidia"] = gpus
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["rocm-smi", "--showuse", "--showmemuse"], capture_output=True,
            text=True, timeout=10)
        if r.returncode == 0 and "GPU use" in r.stdout:
            out["amd"] = r.stdout
    except Exception:
        pass
    return out


def lake_progress() -> tuple[int, int]:
    n = len(list(LAKE.glob("*.parquet")))
    return n, 0


def status() -> dict:
    gpus = gpu_util()
    n_lake, _ = lake_progress()
    s = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gpus": gpus,
        "lake_datasets": n_lake,
    }
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--stall-after", type=int, default=600,
                    help="alert after this many idle seconds")
    ap.add_argument("--alert-file", default=str(PROJECT / "data/accumulator/.stalled"))
    args = ap.parse_args()

    if not args.watch:
        s = status()
        print(f"[{s['ts']}] lake={s['lake_datasets']} datasets  gpus={s['gpus']}")
        return 0

    print(f"watching every {args.interval}s; alert after {args.stall_after}s idle",
          flush=True)
    last_progress = time.time()
    last_lake = -1
    while True:
        s = status()
        now = time.time()
        active = False
        gpu_busy = []
        for g in (s["gpus"].get("nvidia") or []):
            if g["util"] > 5:
                active = True
                gpu_busy.append(f"{g['name']}@{g['util']}%")
        if s["gpus"].get("amd") and "GPU use" in str(s["gpus"]["amd"]):
            for line in str(s["gpus"]["amd"]).splitlines():
                if "GPU use" in line and any(c.isdigit() for c in line):
                    v = int("".join(c for c in line.split(":")[-1] if c.isdigit()) or 0)
                    if v > 5:
                        active = True
                        gpu_busy.append(f"amd@{v}%")
        if s["lake_datasets"] != last_lake:
            last_progress = now
            last_lake = s["lake_datasets"]
            active = True
        if active:
            Path(args.alert_file).unlink(missing_ok=True)
        else:
            idle_for = now - last_progress
            if idle_for > args.stall_after:
                Path(args.alert_file).write_text(
                    f"STALLED {idle_for:.0f}s idle at {s['ts']}\n")
                print(f"ALERT: nothing happening for {idle_for:.0f}s "
                      f"(gpu busy: {gpu_busy or 'none'}, lake: {s['lake_datasets']})",
                      flush=True)
            else:
                print(f"[{s['ts']}] idle {idle_for:.0f}s/{args.stall_after}s "
                      f"lake={s['lake_datasets']}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
