#!/usr/bin/env python3
"""Weekly runway review bundle — the deployability gate's review rhythm.

Runs, in order:
1. shadow_mot (all universes) — the edge evidence engine (per-regime impacts,
   router picks);
2. runway_review — the defect log + runway trade stats;
and assembles a dated Markdown summary into data/reviews/weekly-YYYYMMDD.md.

Scheduled weekly via the systemd user timer opentrader-weekly-review.timer.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

REVIEWS = PROJECT / "data" / "reviews"


def _run(cmd: list, timeout: int = 1800) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (out.stdout or "")[-4000:]
    except Exception as e:
        return f"(runner failed: {e})"


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    py = "/home/mrc/rocm_venv/bin/python3"
    shadow_out = _run([py, str(PROJECT / "setup_search" / "shadow_mot.py")], timeout=1200)
    review_out = _run([py, str(PROJECT / "tools" / "runway_review.py")], timeout=600)

    # pull the defect + stats picture from the log
    import json
    log = {}
    p = PROJECT / "data" / "defect_log.json"
    if p.exists():
        try:
            log = json.loads(p.read_text())
        except Exception:
            pass
    stats = log.get("stats", {})
    defects = log.get("defects", [])

    lines = [
        f"# Weekly runway review — {today}",
        "",
        "## Defect log",
        f"- defects: {len(defects)} total "
        f"({stats.get('fatal_defects', 0)} fatal, {stats.get('moderate_defects', 0)} moderate)",
        f"- days running: {stats.get('days_running')} | cycles: {stats.get('cycles')} "
        f"(avg {stats.get('avg_cycle_s')}s/cycle)",
        f"- closed paper trades since runway start: {stats.get('closed_trades', 0)} "
        f"(exit paths: {stats.get('exit_paths', {})})",
        "",
        "### Open defects",
    ]
    open_defects = [d for d in defects if d.get("status") != "fixed"]
    lines += [f"- {d['date']} {d['category']}: {d['description'][:80]}" for d in open_defects] or ["- none"]
    lines += [
        "",
        "## Shadow evidence (raw)",
        "```",
        shadow_out.strip()[-2500:],
        "```",
        "",
        "## Runway review (raw)",
        "```",
        review_out.strip()[-1500:],
        "```",
        "",
    ]
    REVIEWS.mkdir(parents=True, exist_ok=True)
    (REVIEWS / f"weekly-{today}.md").write_text("\n".join(lines))
    print(f"[weekly] review written to data/reviews/weekly-{today}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
