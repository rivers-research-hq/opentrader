#!/usr/bin/env python3
"""fetch_policy_rates — BIS daily central-bank policy rates into the exog layer.

Why: the fxexpert panel's carry block covers 6 of 58 pairs and its rate-block
join was dead (the rate table was keyed with FRED codes US/EA/GB/CA while
pairs use ISO USD/EUR/GBP/CAD). Carry is the classic FX cross-sectional
factor and the search has effectively never seen it. This script supplies the
missing input: daily policy rates for every currency in the traded universe
(SGD has no policy rate by design — MAS targets the S$NEER — so it is skipped
and stays masked downstream).

Source: BIS central-bank policy rates, dataflow WS_CBPOL, daily, "end of
period" values (i.e. the rate in effect that day — public knowledge on the
day; consumers still lag it 1 day for discipline).
  https://stats.bis.org/api/v1/data/WS_CBPOL/D.<AREA>/all?format=csv
Free with citation (BIS, "Central bank policy rates").

Cache: data/exog_cache_policy.json  {"RATEBIS:<AREA>": {date: value}}
Materialization: store `exog` series RATEBIS:<AREA> (idempotent — deletes only
the series it writes).

Usage: python3 scripts/fetch_policy_rates.py [--store PATH] [--no-store]
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security.guards import guarded_urlopen  # noqa: E402  (hardening layer)

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "exog_cache_policy.json"
DEFAULT_STORE = "/home/mrc/opentrader-data/store.duckdb"

BASE = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.{area}/all?format=csv"
AREAS = ["US", "XM", "GB", "JP", "AU", "NZ", "CA", "CH", "SE", "NO",
         "CZ", "HU", "PL", "TR", "ZA", "CN", "TH", "MX"]
START = "1990-01-01"


def fetch(area, start=START):
    url = BASE.format(area=area) + f"&startPeriod={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "opentrader-research/0.1"})
    with guarded_urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", errors="replace")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        d = (row.get("TIME_PERIOD") or "").strip()
        v = (row.get("OBS_VALUE") or "").strip()
        if not d or v in ("", "."):
            continue
        try:
            x = float(v)
        except ValueError:
            continue
        if x != x:  # BIS emits NaN on non-observation days; store gaps as
            continue  # gaps, never as NaN (DuckDB maps NaN -> NULL anyway)
        out[d] = x
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--no-store", action="store_true",
                    help="write the cache only, skip the store materialization")
    a = ap.parse_args()

    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    fetched = {}
    for area in AREAS:
        try:
            rows = fetch(area)
        except Exception as e:
            print(f"  RATEBIS:{area}: FETCH FAILED ({type(e).__name__}: {e}) — skipped")
            continue
        if len(rows) < 100:
            print(f"  RATEBIS:{area}: only {len(rows)} rows — skipped")
            continue
        key = f"RATEBIS:{area}"
        cache[key] = rows
        fetched[key] = len(rows)
        print(f"  {key:<14} {len(rows):>6} rows  {min(rows)} -> {max(rows)}")
    if not fetched:
        print("[policy] nothing fetched — cache/store untouched")
        return 1
    CACHE.write_text(json.dumps(cache, indent=0))

    if a.no_store:
        print(f"[policy] cache written: {CACHE}")
        return 0

    import duckdb
    import pandas
    con = duckdb.connect(a.store)
    ph = ",".join(["?"] * len(fetched))
    con.execute(f"DELETE FROM exog WHERE series IN ({ph})", list(fetched.keys()))
    rows = [{"series": s, "date": d, "value": float(v)}
            for s in fetched for d, v in cache[s].items()]
    con.register("pol_df", pandas.DataFrame(rows, columns=["series", "date", "value"]))
    con.execute("INSERT INTO exog SELECT * FROM pol_df")
    con.unregister("pol_df")
    con.close()
    print(f"[policy] materialized {len(rows)} rows into {a.store} (idempotent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
