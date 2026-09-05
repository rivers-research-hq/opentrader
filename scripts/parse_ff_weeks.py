#!/usr/bin/env python3
"""parse_ff_weeks — parse cached ForexFactory week pages into the releases
dataset rows (map #191 #194).

This module deliberately contains NO network code: fetching is a separate
concern (curl one-liners or a cron job the human owns — FF rate-limits hard,
and the security policy rejects dynamic-URL request modules). The caller
drops week HTML into data/cache/ff_history/*.html; this script parses the
embedded per-event JSON, normalizes, dedups, and writes dataset rows for the
accrual store's releases_history table.

Input : data/cache/ff_history/*.html  (raw week pages, any naming)
Output: data/cache/ff_history/releases_rows.jsonl
        one row per event: {week, country, name, date, time_label, impact,
                            actual, forecast, previous, revision}

Surprise = actual - forecast is computed at store-import time (build_accrual_store.py),
after UTC normalization — parsing keeps the raw labels for provenance.

Usage:
  python3 scripts/parse_ff_weeks.py            # parse all cached weeks
  python3 scripts/parse_ff_weeks.py --file X   # one file
"""

import argparse
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "cache" / "ff_history"

EVENT_RE = re.compile(
    r'\{[^{}]*?"name":"[^"]{3,80}?"[^{}]*?"country":"[A-Z]{2}"'
    r'[^{}]*?"forecast":"[^"]*"[^{}]*?\}'
)


def parse_week_file(path: Path) -> list:
    html = path.read_text(encoding="utf8", errors="replace")
    rows = []
    for m in EVENT_RE.finditer(html):
        try:
            e = json.loads(m.group(0))
        except Exception:
            continue
        if not (e.get("name") and e.get("country")):
            continue
        rows.append({
            "week": path.stem.replace("week_", ""),
            "country": e.get("country"),
            "name": e.get("name"),
            "date_label": e.get("date"),
            "time_label": e.get("timeLabel") or e.get("time"),
            "impact": (e.get("impactName") or "").lower() or None,
            "actual": e.get("actual"),
            "forecast": e.get("forecast"),
            "previous": e.get("previous"),
            "revision": e.get("revision"),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Parse cached FF week pages into dataset rows")
    ap.add_argument("--file", default=None, help="single .html file; default = all cached")
    args = ap.parse_args()

    if args.file:
        files = [Path(args.file)]
    else:
        files = sorted(CACHE.glob("week_*.html")) if CACHE.exists() else []
        if not files:
            print(f"[ff-parse] no cached week files in {CACHE} — fetch some first "
                  f"(curl -A '<browser UA>' 'https://www.forexfactory.com/calendar?week=sep4.2020' -o week_sep4.2020.html)")
            return

    seen, rows, dup = set(), [], 0
    for f in files:
        for r in parse_week_file(f):
            k = (r["week"], r["country"], r["name"], r["date_label"], r["time_label"])
            if k in seen:
                dup += 1
                continue
            seen.add(k)
            rows.append(r)

    out = CACHE / "releases_rows.json"
    existing = json.loads(out.read_text()) if out.exists() else []
    merged = {json.dumps(r, sort_keys=True): r for r in existing}
    for r in rows:
        merged[json.dumps({k: r[k] for k in sorted(r)}, sort_keys=True)] = r
    final = list(merged.values())
    out.write_text(json.dumps(final, indent=1))

    hi = sum(1 for r in final if r.get("impact") == "high")
    fc = sum(1 for r in final if r.get("forecast"))
    print(f"[ff-parse] weeks parsed this pass: {len(rows)} rows ({dup} dups skipped) | "
          f"merged total: {len(final)} rows ({hi} high-impact) -> {out}")


if __name__ == "__main__":
    main()
