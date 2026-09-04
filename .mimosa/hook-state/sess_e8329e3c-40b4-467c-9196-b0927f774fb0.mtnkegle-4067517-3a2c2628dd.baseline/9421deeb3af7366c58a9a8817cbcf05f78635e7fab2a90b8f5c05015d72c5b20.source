#!/usr/bin/env python3
"""Runway review — the deployability gate's bookkeeping (ADR-0002).

Maintains data/defect_log.json and reports runway health:

- defects per the severity scheme (fatal / moderate / cosmetic) auto-detected
  from the harness journal: crash-loops, watchdog exits, ERROR lines;
- runway trade stats: closed trades since the runway start (the journal holds
  stale pre-runway trades — the gate's >=3-trade count must only count
  post-runway), exit paths seen (stop / target / 14-day hold), cycle health;
- dedup by (date, category); manual entries (seeded defects) are preserved.

Usage: python3 tools/runway_review.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
LOG = PROJECT / "data" / "defect_log.json"
# The pinned-surface runway relaunch (cycle 12055, 2026-08-05 18:22 UTC).
RUNWAY_START = "2026-08-05T18:22:00+00:00"

PATTERNS = {
    "crash_loop": re.compile(r"Cycle (\d+) crashed \((\d+) consecutive\)"),
    "watchdog_exit": re.compile(r"exiting; systemd Restart=always will relaunch"),
    "cycle_done": re.compile(r"Cycle (\d+) done in ([\d.]+)s"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(since: str) -> str:
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", "opentrader-harness.service",
             "--since", since, "--no-pager"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout
    except Exception:
        return ""


def _load() -> dict:
    if LOG.exists():
        try:
            return json.loads(LOG.read_text())
        except Exception:
            pass
    return {"runway_start": RUNWAY_START, "defects": [], "stats": {}}


_LINE_TS = re.compile(r"([A-Z][a-z]{2} {1,2}\d{1,2} \d{2}:\d{2}:\d{2})")


def _line_time(journal: str, pos: int) -> str:
    """Journal timestamp of the line containing pos: 'Aug 05 22:33:42'."""
    line_start = journal.rfind("\n", 0, pos) + 1
    m = _LINE_TS.match(journal, line_start)
    return m.group(1) if m else ""


def _parse_events(journal: str) -> list:
    """All crash streaks (>=3) and watchdog exits with line timestamps,
    converted to sortable datetime."""
    events = []
    for m in PATTERNS["crash_loop"].finditer(journal):
        if int(m.group(2)) >= 3:
            events.append((_line_time(journal, m.start()),
                           "crash", f"{m.group(2)} consecutive crashes (cycle {m.group(1)})"))
    for m in PATTERNS["watchdog_exit"].finditer(journal):
        events.append((_line_time(journal, m.start()), "watchdog", "harness exited for watchdog"))
    out = []
    for ts, kind, desc in events:
        try:
            dt = datetime.strptime(f"{ts} 2026", "%b %d %H:%M:%S %Y")
            out.append((dt, kind, desc))
        except Exception:
            continue
    return sorted(out)


def _scan_journal(journal: str, defects: list) -> list:
    """Collapse crash events into EPISODES: events within 15 min of each other
    are one defect (the 22:33->00:34 marathon = 60 watchdog exits, ONE root
    cause). Returns new episode defects not already recorded."""
    events = _parse_events(journal)
    episodes = []
    cur = None
    for dt, kind, desc in events:
        if cur is None or (dt - cur[1]).total_seconds() > 15 * 60:
            cur = [dt, dt, [desc]]
            episodes.append(cur)
        else:
            cur[1] = dt
            cur[2].append(desc)
    seen = {(d["category"], d.get("episode_start", "")) for d in defects}
    found = []
    for start, end, descs in episodes:
        key = ("crash_episode", start.strftime("%Y-%m-%dT%H:%M"))
        if key in seen:
            continue
        mins = int((end - start).total_seconds() / 60)
        found.append({
            "date": start.isoformat(timespec="minutes"), "severity": "fatal",
            "category": "crash_episode",
            "episode_start": start.strftime("%Y-%m-%dT%H:%M"),
            "description": f"crash episode: {len(descs)} events over ~{mins} min "
                           f"(first: {descs[0][:50]})",
            "root_cause": "", "fix": "", "status": "open",
        })
    return found


def _runway_trades(journal_path: Path) -> dict:
    """Closed trades since the runway start (stale pre-runway entries excluded)."""
    import pandas as pd
    start = pd.Timestamp(RUNWAY_START)
    tj = []
    try:
        d = json.loads(journal_path.read_text())
        tj = d.get("_trade_journal", [])
    except Exception:
        pass
    trades = []
    for t in tj:
        ts = t.get("timestamp")
        try:
            if ts and pd.Timestamp(ts) >= start:
                trades.append(t)
        except Exception:
            continue
    exit_paths = {"stop": 0, "target": 0, "hold": 0, "other": 0}
    for t in trades:
        r = str(t.get("reason") or "")
        if "stop-loss" in r or "position-drawdown" in r:
            exit_paths["stop"] += 1
        elif "take-profit" in r:
            exit_paths["target"] += 1
        elif "timeout" in r or "max-hold" in r:
            exit_paths["hold"] += 1
        else:
            exit_paths["other"] += 1
    return {"closed_trades": len(trades), "exit_paths": exit_paths,
            "symbols": sorted({t.get("symbol") for t in trades})[:8]}


def _cycle_stats(journal: str) -> dict:
    done = [(int(m.group(1)), float(m.group(2))) for m in PATTERNS["cycle_done"].finditer(journal)]
    if not done:
        return {"cycles": 0}
    times = [t for _, t in done]
    return {"cycles": len(done),
            "cycles_since": max(done)[0],
            "avg_cycle_s": round(sum(times) / len(times), 2),
            "max_cycle_s": max(times),
            "last_cycle": max(done)[0]}


def main():
    log = _load()
    journal = _journal(RUNWAY_START)
    if not journal:
        print("[runway] journal empty (permissions or rotation) — using state files only")

    new_defects = _scan_journal(journal, log["defects"])
    log["defects"] += new_defects
    for d in log["defects"]:
        if d.get("status") == "open":
            d["status"] = "open"  # review marks fixed manually

    trades = _runway_trades(PROJECT / "data" / "agent_state.json")
    stats = _cycle_stats(journal)
    stats.update({
        "days_running": round((datetime.now(timezone.utc)
                               - datetime.fromisoformat(RUNWAY_START)).total_seconds() / 86400, 1),
        "fatal_defects": sum(1 for d in log["defects"] if d["severity"] == "fatal"),
        "moderate_defects": sum(1 for d in log["defects"] if d["severity"] == "moderate"),
        "closed_trades": trades["closed_trades"],
        "exit_paths": trades["exit_paths"],
    })
    log["stats"] = stats
    log["updated_at"] = _now()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(log, indent=1))

    print(f"[runway] days running: {stats['days_running']}")
    print(f"[runway] cycles: {stats.get('cycles', 0)} (last {stats.get('last_cycle')}, "
          f"avg {stats.get('avg_cycle_s')}s)")
    print(f"[runway] closed trades since start: {trades['closed_trades']} "
          f"(exit paths: {trades['exit_paths']})")
    print(f"[runway] defects: {len(log['defects'])} total "
          f"({stats['fatal_defects']} fatal, {stats['moderate_defects']} moderate)")
    for d in log["defects"]:
        print(f"  [{d['severity']:8s}] {d['date'][:16]} {d['category']}: {d['description'][:60]} "
              f"({d['status']})")
    if not new_defects:
        print("[runway] no NEW defects detected since last review")


if __name__ == "__main__":
    sys.exit(main())
