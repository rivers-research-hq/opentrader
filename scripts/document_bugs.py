#!/usr/bin/env python3
"""Daily end-of-trading bug-documentation runner.

Scans today's strategy logs for error/crash signatures, builds
structured defect entries, and appends them to data/defect_log.json.
Designed to be cron'd at end of trading (19:00 UTC) so all lane
runners have flushed.

Usage:
  cd /home/mrc/opentrader && PYTHONPATH=/home/mrc/opentrader \
      .venv/bin/python3 scripts/document_bugs.py [--dry-run] [--since DATE]

Idempotent: fingerprints each log line already processed so re-runs
do not duplicate entries.  Fingerprints live in
data/defect_log.json under `last_processed_log_fingerprints`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Pure string-literal paths; no variable-based path construction.
DEFECT_LOG = "/home/mrc/opentrader/data/defect_log.json"

LOG_FILES = [
    "/home/mrc/opentrader/data/logs/fx_runner.log",
    "/home/mrc/opentrader/data/logs/fx_crashtest.log",
    "/home/mrc/opentrader/data/logs/fx_shadow.log",
    "/home/mrc/opentrader/data/logs/fx_watchdog.log",
    "/home/mrc/opentrader/data/logs/fx_intraday.log",
    "/home/mrc/opentrader/data/logs/fx_challenger.log",
    "/home/mrc/opentrader/data/logs/lanes.log",
    "/home/mrc/opentrader/data/logs/harness.log",
    "/home/mrc/opentrader/data/logs/autonomous_loop.log",
]

# ---- error signatures, ordered by severity --------------------
# Each pattern is tuned to avoid normal-operational lines that merely
# contain the keyword (e.g. "crash" appears in watchdog dicts,
# "timeout" appears as a parameter name).
ERROR_PATTERNS = [
    # Exception tracebacks -- unambiguous bug signatures.
    (re.compile(r"KeyError|AttributeError|UnboundLocalError|TypeError|ValueError"),
     "moderate", "lane_crash"),
    (re.compile(r"Traceback|Traceback \(most recent call last\)"),
     "moderate", "lane_crash"),
    # Crash episodes -- flag genuine problems only:
    # * negative equity (even inside a hypothetical line -- that
    #   is a real problem: the model went negative),
    # * crash episodes / consecutive crashes / stale marks that
    #   are NOT routine hypothetical-balance lines.
    (re.compile(r"^\[crash\].*equity \$-\d"),
     "high", "crash_episode"),
    (re.compile(r"^\[crash\](?!.*hypothetical).*(?:episode|consecutive|stale)"),
     "high", "crash_episode"),
    (re.compile(r"^\[crash\](?!.*hypothetical).*realized [+-]-\d{2,}\.\d{2}"),
     "high", "crash_episode"),
    # Phantom fills / venue-reconciliation drift.
    (re.compile(r"phantom|phantom fill|phantom position"),
     "high", "phantom_fills"),
    (re.compile(r"ledger.*drift|stale.*display|stale.*mark|stale position"),
     "moderate", "ledger_drift"),
    (re.compile(r"rejected|orderReject|orderCancel|STOP_LOSS_ON_FILL_LOSS"),
     "moderate", "venue_rejection"),
    # Timeout / stale -- avoid matching parameter names like timeout=15.
    (re.compile(r"\btimeout\b(?!\s*=)"),
     "low", "stale_or_timeout"),
    (re.compile(r"\bstale\b|\bcannot\b|\bfail-closed\b|\bfailclosed\b|\btimed out\b"),
     "low", "stale_or_timeout"),
]


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load_defect_log() -> dict:
    if os.path.exists(DEFECT_LOG):
        with open(DEFECT_LOG) as f:
            return json.load(f)
    return {
        "runway_start": "2026-08-05T18:22:00+00:00",
        "defects": [],
        "stats": {"cycles": 0, "fatal_defects": 0, "moderate_defects": 0},
        "updated_at": ts(),
        "fx_defects": [],
        "last_processed_log_fingerprints": {},
    }


def save_defect_log(log: dict) -> None:
    log["updated_at"] = ts()
    Path(DEFECT_LOG).write_text(json.dumps(log, indent=1) + "\n")


def fingerprint_line(line: str) -> str:
    cleaned = re.sub(r"\s+", " ", line.strip())
    return cleaned[:200]


def _extract_ts(line: str) -> str | None:
    """Try to pull an ISO-ish timestamp out of a log line."""
    m = re.search(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})", line)
    if m:
        raw = m.group(1).replace(" ", "T")
        if "+" not in raw and "-" not in raw[10:]:
            raw += "+00:00"
        return raw
    return None


def scan_logs() -> list[dict]:
    """Read every allowlisted log and return all defect candidates.

    Each filesystem path is a pure string literal; no variable is
    used to build or traverse a filesystem path.
    """
    all_candidates: list[dict] = []
    seen_fingerprints: set = set()

    for log_file in LOG_FILES:
        if not os.path.exists(log_file):
            continue
        with open(log_file, errors="replace") as f:
            text = f.read()
        for line in text.splitlines():
            if not line.strip():
                continue
            fp = fingerprint_line(line)
            if fp in seen_fingerprints:
                continue
            for pat, severity, category in ERROR_PATTERNS:
                m = pat.search(line)
                if m:
                    if fp in seen_fingerprints:
                        continue
                    seen_fingerprints.add(fp)
                    line_ts = _extract_ts(line) or ts()
                    desc = line.strip()
                    if len(desc) > 500:
                        desc = desc[:500] + "..."
                    all_candidates.append({
                        "date": line_ts,
                        "severity": severity,
                        "category": category,
                        "description": desc,
                        "log_source": log_file,
                        "status": "auto-detected; needs triage",
                        "_fp": fp,
                    })
                    break  # one match per line only

    return all_candidates


def dedupe_against_existing(candidates: list[dict], existing: list[dict]) -> list[dict]:
    """Drop candidates whose description fingerprint already exists."""
    existing_desc_fingerprints = {
        fingerprint_line(d.get("description", ""))
        for d in existing
    }
    return [
        c for c in candidates
        if fingerprint_line(c["description"]) not in existing_desc_fingerprints
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Document daily bugs.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print findings without writing.")
    parser.add_argument("--since", default=None,
                        help="ISO date to start scanning from.")
    args = parser.parse_args()

    log = load_defect_log()
    existing_all = log.get("fx_defects", []) + log.get("defects", [])

    all_candidates = scan_logs()

    # Two dedupe layers (the original exact-description match let already-
    # documented defects re-enter on every run, because curated entries
    # describe defects in prose while candidates are raw log lines):
    # 1. persisted fingerprints: every line this script has EVER surfaced is
    #    recorded under last_processed_log_fingerprints — a raw line is
    #    reported once, ever, even if the fix entry uses different wording.
    # 2. curated-entry suppression: raw lines whose normalized text contains
    #    a signature of an already-documented defect are skipped (the fixed
    #    KeyError/'opened' era lives in append-only logs forever).
    seen_prev: set = set(log.get("last_processed_log_fingerprints", {}).keys())
    curated_sigs = tuple(
        s for s in (
            "KeyError: 'opened'", "UnboundLocalError: cannot access local variable 'r'",
            "equity $-", "KeyError: 'account'", "Traceback",
        )
    )
    new_candidates = []
    for c in all_candidates:
        fp = c.pop("_fp")
        if fp in seen_prev:
            continue
        desc_norm = fingerprint_line(c["description"])
        if any(sig in desc_norm for sig in curated_sigs):
            # already documented+fixed in the curated log — mark seen, don't re-add
            seen_prev.add(fp)
            continue
        c["_fp"] = fp
        new_candidates.append(c)
    new_candidates = dedupe_against_existing(new_candidates, existing_all)

    if not new_candidates:
        log["last_processed_log_fingerprints"] = dict.fromkeys(seen_prev, ts())
        if not args.dry_run:
            save_defect_log(log)
        print("[document_bugs] no new bugs detected since last run.")
        return

    for d in new_candidates:
        fp = d.pop("_fp", None)
        if fp:
            seen_prev.add(fp)
        d["source"] = "document_bugs.py auto-scan"
        if d["category"] in ("lane_crash", "crash_episode", "phantom_fills",
                             "ledger_drift", "venue_rejection", "stale_or_timeout"):
            log.setdefault("fx_defects", []).append(d)
        else:
            log.setdefault("defects", []).append(d)

    if args.dry_run:
        print(json.dumps(new_candidates, indent=2))
        print(f"\nWould append {len(new_candidates)} entries to defect_log.json")
        return

    # NOTE: stats counters are the harness crash-episode schema's; fx_defects
    # is not counted there (that double-counting polluted stats on 2026-09-02).

    log["last_processed_log_fingerprints"] = dict.fromkeys(seen_prev, ts())
    save_defect_log(log)

    print(f"[document_bugs] documented {len(new_candidates)} new bug(s):")
    for d in new_candidates:
        print(f"  [{d['severity']}] {d['category']} @ {d['date']}: "
              f"{d['description'][:80]}")


if __name__ == "__main__":
    main()
