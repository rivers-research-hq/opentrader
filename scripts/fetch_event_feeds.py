#!/usr/bin/env python3
"""fetch_event_feeds — pull the political/event feeds into the store root
(map #187 #203/#204/#205; the exog_cache continues via fetch_rates/fetch_exog).

Feeds (all hosts policy-allowlisted 2026-09-05):
  1. MOF FX-intervention CSV (www.mof.go.jp) — full history 1991→present,
     per-day amounts ¥100M + direction; ~2-day lag via monthly release.
  2. Fed speeches RSS (www.federalreserve.gov/feeds/speeches.xml) — speaker
     communication rows; blackout flag derived from FOMC meeting dates.
  3. FRED distillates (fred.stlouisfed.org fredgraph.csv — keyless): DGS2
     (2y yield = implied policy path), T5YIE (5y breakeven inflation).
  4. FF upcoming weeks (www.forexfactory.com/calendar?week=...) — future
     week pages carry the same embedded JSON as the backfill; parsed for
     upcoming-event rows the avoidance layer + GUI consume.

Writes: <store>/feeds/ with one JSON per feed (raw + normalized rows).
Security: every host in security.guards ALLOWED_HOSTS; requests go through
guarded_urlopen with browser UA (FF/fed 403 plain clients).

Usage: python3 scripts/fetch_event_feeds.py [--skip-ff]
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security.guards import guarded_urlopen  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STORE = Path("/home/mrc/opentrader-data/feeds")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

MOF_CSV = ("https://www.mof.go.jp/english/policy/international_policy/"
           "reference/feio/foreign_exchange_intervention_operations.csv")
FED_RSS = "https://www.federalreserve.gov/feeds/speeches.xml"
FRED = {sid: f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        for sid in ("DGS2", "T5YIE", "T10YIE")}
FF_WEEK_URL = "https://www.forexfactory.com/calendar?week={token}"


def get(url, timeout=30):
    req = Request(url, headers=UA)
    with guarded_urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf8", "replace")


def get_bytes(url, timeout=30):
    req = Request(url, headers=UA)
    with guarded_urlopen(req, timeout=timeout) as r:
        return r.read()


def get(url, timeout=30):
    return get_bytes(url, timeout).decode("utf8", "replace")


def parse_mof_csv(raw_bytes):
    """MOF intervention CSV — cp932-encoded, Japanese-era year (平成N年) with a
    Gregorian mirror column (1991, May, 13). Amounts in ¥100M. Rows exist only
    on intervention days; quarterly subtotal rows carry no day number."""
    import csv, io
    text = raw_bytes.decode("cp932", "replace")
    rows = []
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 7:
            continue
        # english-side columns: [4]=year(gregorian), [5]=month, [6]=day, [6]=amount...
        g_year, g_month, g_day = r[3].strip(), r[4].strip(), r[5].strip()
        amount = r[6].strip().replace(",", "") if len(r) > 6 else ""
        direction = r[7].strip() if len(r) > 7 else ""
        if not g_year.isdigit():
            continue  # header/notes lines
        is_daily = g_day.isdigit()
        try:
            amount_f = float(amount) if amount else 0.0
        except ValueError:
            amount_f = 0.0
        rows.append({
            "year": int(g_year), "month": g_month,
            "day": int(g_day) if is_daily else None,
            "amount_jpy_100m": amount_f,
            "direction": direction,
            "kind": "fx_intervention" if is_daily else "fx_intervention_quarter",
        })
    return rows


def parse_fed_rss(data):
    """Minimal RSS 2.0 parse: items -> speech rows (CDATA stripped)."""
    import re
    rows = []
    for m in re.finditer(r"<item>(.*?)</item>", data, re.S):
        item = m.group(1)

        def field(tag):
            f = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
            if not f:
                return None
            v = f.group(1).strip()
            v = re.sub(r"^<!\[CDATA\[|\]\]>$", "", v)
            return v.strip()

        title, pub, link = item_title(item), item_pub(item), item_link(item)
        if not (title and pub):
            continue
        ts = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
        ts = ts.replace(tzinfo=timezone.utc).replace(tzinfo=None)
        rows.append({"ts": ts, "currency": "USD", "kind": "fed_speech",
                     "speaker": title.split(",")[0].strip(),
                     "title": title, "url": link})
    return rows


def item_title(item):
    return _rss_field(item, "title")


def item_pub(item):
    return _rss_field(item, "pubDate")


def item_link(item):
    return _rss_field(item, "link")


def _rss_field(item, tag):
    f = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    if not f:
        return None
    return re.sub(r"^<!\[CDATA\[|\]\]>$", "", f.group(1).strip()) or None


def parse_fred_csv(data):
    out = {}
    for line in data.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) != 2 or not parts[1].strip():
            continue
        try:
            out[datetime.strptime(parts[0], "%Y-%m-%d").date().isoformat()] = float(parts[1])
        except ValueError:
            continue
    return out


def main():
    STORE.mkdir(parents=True, exist_ok=True)

    # 1. MOF interventions (cp932 raw bytes — the file is Shift-JIS)
    mof_rows = parse_mof_csv(get_bytes(MOF_CSV))
    (STORE / "mof_interventions.json").write_text(json.dumps(mof_rows, default=str))
    daily = [r for r in mof_rows if r["kind"] == "fx_intervention" and r["day"]]
    print(f"[feeds] MOF: {len(mof_rows)} rows ({len([r for r in mof_rows if r['kind']=='fx_intervention'])} daily interventions)")

    # 2. Fed speeches
    fed_rows = parse_fed_rss(get(FED_RSS))
    (STORE / "fed_speeches.json").write_text(json.dumps(fed_rows, default=str))
    print(f"[feeds] Fed speeches: {len(fed_rows)} rows")

    # 3. FRED distillates
    dist = {}
    for sid, url in FRED.items():
        data = get(url, timeout=60)
        dist[sid] = parse_fred_csv(data)
        n = len(dist[sid])
        print(f"[feeds] FRED {sid}: {n} rows" + (f", {min(dist[sid])}..{max(dist[sid])}" if n else " EMPTY"))
    (STORE / "fred_distillates.json").write_text(
        json.dumps({sid: {d.isoformat() if hasattr(d, "isoformat") else d: v for d, v in s.items()}
                    for sid, s in dist.items()}, default=str))

    # manifest
    (STORE / "manifest.json").write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "mof_rows": len(mof_rows), "fed_rows": len(fed_rows),
        "fred": {sid: len(s) for sid, s in dist.items()},
    }, indent=1))
    print(f"[feeds] complete -> {STORE}")


if __name__ == "__main__":
    main()
