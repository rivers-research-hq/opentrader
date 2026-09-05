#!/usr/bin/env python3
"""fetch_ff_upcoming — fetch the next N weeks of ForexFactory calendar pages
and emit upcoming-release rows for /api/calendar + the avoidance layer
(map #187 #204).

Replaces the dead nextweek JSON feed: the week-view HTML pages (proven in
#194's backfill) render FUTURE weeks too, with the same embedded per-event
JSON (forecast fields included).

Output: /home/mrc/opentrader-data/feeds/ff_upcoming.json — rows
{date_label, time_label, country, name, impact, forecast, previous, week_token}
The dashboard's /api/calendar consumes this file (UTC normalization at
render — same America/Chicago convention as the store, verified in #195).

Usage: python3 scripts/fetch_ff_upcoming.py [--weeks 3]
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security.guards import guarded_urlopen  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STORE = Path("/home/mrc/opentrader-data/feeds")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
      "Accept": "text/html,application/xhtml+xml"}

EVENT_RE = re.compile(
    r'\{[^{}]*?"name":"[^"]{3,80}?"[^{}]*?"country":"[A-Z]{2}"'
    r'[^{}]*?"forecast":"[^"]*"[^{}]*?\}')


def week_token(d: date) -> str:
    return d.strftime("%b%d.%Y").lower()


def fetch_week_html(token: str) -> str:
    from urllib.request import Request
    req = Request(f"https://www.forexfactory.com/calendar?week={token}", headers=UA)
    with guarded_urlopen(req, timeout=30) as r:
        return r.read().decode("utf8", "replace")


def parse_events(html: str, week_iso: str) -> list:
    rows = []
    for m in EVENT_RE.finditer(html):
        try:
            e = json.loads(m.group(0))
        except Exception:
            continue
        if e.get("name") and e.get("country"):
            rows.append({
                "week": token_of(week_mon(week_iso)),
                "date_label": e.get("date"), "time_label": e.get("timeLabel"),
                "country": e.get("country"), "name": e.get("name"),
                "impact": (e.get("impactName") or "").lower() or None,
                "forecast": e.get("forecast"), "previous": e.get("previous"),
                "actual": e.get("actual"),
            })
    return rows


def week_mon(week_iso):
    return date.fromisoformat(week_iso)


def token_of(mon):
    return mon.strftime("%b%d.%Y").lower()


def main():
    ap = argparse.ArgumentParser(description="Fetch upcoming FF calendar weeks")
    ap.add_argument("--weeks", type=int, default=3, help="weeks ahead (default 3)")
    args = ap.parse_args()

    STORE.mkdir(parents=True, exist_ok=True)
    today = date.today()
    this_mon = today - timedelta(days=today.weekday())
    rows, seen = [], set()
    for i in range(args.weeks):
        mon = this_mon + timedelta(weeks=i)
        token = mon.strftime("%b%d.%Y").lower()
        try:
            html = fetch_week_html(token)
        except Exception as e:
            print(f"[ff-up] week {mon} fetch failed: {type(e).__name__} — continuing", flush=True)
            time.sleep(8)
            continue
        for r in parse_events(html, mon.isoformat()):
            k = (r["date_label"], r["time_label"], r["country"], r["name"])
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
        time.sleep(8)

    STORE.mkdir(parents=True, exist_ok=True)
    out = STORE / "ff_upcoming.json"
    out.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(),
                               "weeks": args.weeks, "events": rows}, default=str))
    hi = sum(1 for r in rows if r.get("impact") == "high")
    fc = sum(1 for r in rows if r.get("forecast") not in (None, "", "-"))
    print(f"[ff] upcoming: {len(rows)} events ({hi} high-impact, {fc} with forecast) -> {out}")


def fetch_week_html(token: str) -> str:
    from urllib.request import Request
    if not re.match(r"^[a-z]{3}\d{1,2}\.\d{4}$", token):
        raise ValueError(f"bad week token {token!r}")
    url = "https://www.forexfactory.com/calendar?week=" + token
    with guarded_urlopen(Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf8", "replace")


if __name__ == "__main__":
    main()
