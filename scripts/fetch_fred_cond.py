#!/usr/bin/env python3
"""fetch_fred_cond — pull the FRED macro-conditioning panel (alt-data
inventory §"integrate first", ticket #206) into the exog cache and
materialize it into the accrual store's exog table.

Series (all free, no key, fred.stlouisfed.org/graph/fredgraph.csv):
  VIXCLS       equity vol — global risk appetite state
  BAMLH0A0HYM2 ICE BofA HY OAS — credit stress state
  USEPUINDXD   daily US economic-policy uncertainty
  DCOILWTI     WTI spot — CAD terms of trade
  PIORECRUSDM  iron ore 62% Fe — AUD terms of trade (monthly)
  PNGASEUUSDM  TTF gas — EUR/CHF energy shock (monthly)

Z-scoring happens at the consumer (fxexpert.data, causal rolling window).
Publication-lag discipline is applied at the consumer: daily series lagged
1 day, monthly series 15 days — a monthly print for month M is public
mid-M+1, so lag-15d is conservative.

Cache: appends data/exog_cache.json["FRED:<id>"] = {date: value} (the
durable form; build_accrual_store.build_exog ingests it on rebuild). The
store INSERT below is an idempotent incremental materialization of exactly
what build_exog would produce — documented deviation from single-writer to
avoid a full venue re-pull mid-session.

Usage: python3 scripts/fetch_fred_cond.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from security.guards import guarded_urlopen  # noqa: E402  (hardening layer)

import csv
import io
import json
import urllib.request
from datetime import datetime, timezone

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "exog_cache.json"
STORE = "/home/mrc/opentrader-data/store.duckdb"
BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

SERIES = ["VIXCLS", "BAMLH0A0HYM2", "USEPUINDXD", "DCOILWTICO",
          "PIORECRUSDM", "PNGASEUUSDM",
          # instability watch v0.2: sovereign/curve/corporate stress
          "DGS10",          # US 10Y treasury yield (govt)
          "T10Y2Y",         # 2s10s curve (recession/stress shape)
          "BAMLEMHYHYLCRPIOAS"]  # EM corporate HY OAS (brewing EM stress)


def fetch(sid):
    url = BASE.format(sid=sid)
    req = urllib.request.Request(url, headers={"User-Agent": "opentrader-research/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", errors="replace")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        d = (row.get("DATE") or row.get("observation_date") or "").strip()
        v = (row.get(sid) or "").strip()
        if not d or v in ("", "."):
            continue
        try:
            out[d] = float(v)
        except ValueError:
            continue
    return out


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    fetched = {}
    for sid in SERIES:
        try:
            rows = fetch(sid)
        except Exception as e:
            print(f"  FRED:{sid}: FETCH FAILED ({e}) — skipped")
            continue
        if len(rows) < 100:
            print(f"  FRED:{sid}: only {len(rows)} rows — skipped")
            continue
        cache[f"FRED:{sid}"] = rows
        fetched[f"FRED:{sid}"] = len(rows)
        print(f"  FRED:{sid}: {len(rows)} rows "
              f"({min(rows)} -> {max(rows)})")
    if not fetched:
        print("[fred] nothing fetched — store untouched")
        return 1
    CACHE.write_text(json.dumps(cache, indent=0))

    con = duckdb.connect(STORE)
    # Replace only the series actually fetched. The old `DELETE ... LIKE
    # 'FRED:%'` wiped every FRED series in the store, including ~8 this
    # script's SERIES list never restores (e.g. the EM-HY OAS the warden
    # reads) — silent data loss on every run.
    ph = ",".join(["?"] * len(fetched))
    con.execute(f"DELETE FROM exog WHERE series IN ({ph})", list(fetched.keys()))
    rows = [{"series": s, "date": d, "value": float(v)}
            for s, vals in fetched_rows(cache, fetched)
            for d, v in vals.items()]
    con.register("fred_df", __import__("pandas").DataFrame(
        rows, columns=["series", "date", "value"]))
    con.execute("INSERT INTO exog SELECT * FROM fred_df")
    con.unregister("fred_df")
    con.close()
    print(f"[fred] materialized {len(rows)} rows into {STORE} "
          f"(idempotent; build_exog reproduces from cache)")
    return 0


def fetched_rows(cache, fetched):
    for s in fetched:
        yield s, cache[s]


if __name__ == "__main__":
    sys.exit(main())
