#!/usr/bin/env python3
"""OpenTrader harness health check. READ-ONLY.

Verifies, for MAIN and SHADOW:
  1. service active          (systemctl --user is-active)
  2. state JSON valid        (paper_state.json parses)
  3. prices fresh            (state timestamp within MAX_AGE_MIN)
  4. cycles advancing        (cycle > last-seen cycle, persisted in health_state.json)
  5. no error spikes         (no Python Tracebacks in the last 30 min of journal)

Writes one status line to health_status.log, prints a summary, and exits
0 (healthy) or 1 (problem) so a timer/cron can react.

Run:  /home/mrc/rocm_venv/bin/python3 health_check.py
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/mrc/opentrader/data")
BOOKS = {
    "MAIN": (BASE / "paper_state.json", "opentrader-harness"),
    "SHADOW": (BASE / "shadow_scaled" / "paper_state.json", "opentrader-shadow"),
}
STATE = BASE / "shadow_scaled" / "health_state.json"
LOG = BASE / "shadow_scaled" / "health_status.log"
MAX_AGE_MIN = 5      # harness writes state every ~60s; >5 min old = stale
JOURNAL_MIN = 30     # look back this many minutes for tracebacks


def svc_active(name):
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", name],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def journal_tracebacks(name):
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", name, "--since",
             f"{JOURNAL_MIN} min ago", "-q", "--no-pager"],
            capture_output=True, text=True, timeout=20)
        return r.stdout.count("Traceback")
    except Exception:
        return -1  # unknown (journal unavailable) -- do not treat as a failure


def check_book(label, path, svc):
    issues = []
    info = {"cycle": None, "value": None, "ts": None}
    if not svc_active(svc):
        issues.append(f"service {svc} NOT active")
    try:
        d = json.load(open(path))
    except Exception as e:
        issues.append(f"state JSON invalid: {e}")
        return issues, info
    ts = d.get("timestamp")
    if ts:
        try:
            t = datetime.fromisoformat(ts)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60
            if age_min > MAX_AGE_MIN:
                issues.append(f"prices STALE ({age_min:.0f} min old)")
        except Exception:
            issues.append(f"unparseable timestamp {ts!r}")
    info["cycle"] = d.get("cycle")
    info["value"] = d.get("portfolio_value")
    info["ts"] = ts
    return issues, info


def main():
    problems = []
    results = {}
    for label, (path, svc) in BOOKS.items():
        issues, info = check_book(label, path, svc)
        results[label] = (issues, info)
        problems += [f"{label}: {i}" for i in issues]

    # cycle-advance check against last run
    prev = {}
    if STATE.exists():
        try:
            prev = json.load(open(STATE))
        except Exception:
            prev = {}
    newstate = {}
    for label, (issues, info) in results.items():
        c = info.get("cycle")
        if c is None:
            continue
        pc = (prev.get(label) or {}).get("cycle")
        if pc is not None and c <= pc:
            problems.append(f"{label}: cycle NOT advancing (stuck at {c})")
        newstate[label] = {"cycle": c, "ts": info.get("ts")}
    try:
        STATE.write_text(json.dumps(newstate))
    except Exception:
        pass

    # journal error spikes
    for label, (path, svc) in BOOKS.items():
        tb = journal_tracebacks(svc)
        if tb > 0:
            problems.append(f"{label}: {tb} traceback(s) in last {JOURNAL_MIN} min")

    status = "HEALTHY" if not problems else "PROBLEM"
    line = f"{datetime.now(timezone.utc).isoformat()} {status} " + (
        "; ".join(problems) if problems else "all checks pass")
    print(line)
    for label, (issues, info) in results.items():
        print(f"  {label}: cycle={info.get('cycle')} "
              f"value={info.get('value')} ts={info.get('ts')}")
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
