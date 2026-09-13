#!/usr/bin/env python3
"""materialize_exog — cache → store materializer for COT z-scores.

The v2 pipeline's COT path had a gap: scripts/fetch_exog.py refreshes
data/exog_cache.json, but nothing carried COT:* into the store's exog table
(the panel's exog_series() reads the store). This script closes that loop:
idempotent (delete-then-insert per series for dates after the existing max),
schema-matched (series VARCHAR, date VARCHAR, value DOUBLE).

Usage: python3 scripts/materialize_exog.py
"""

import json
import sys
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
STORE = "/home/mrc/opentrader-data/store.duckdb"
CACHE = PROJECT / "data" / "exog_cache.json"


def main():
    if not CACHE.exists():
        raise SystemExit(f"[exog] no cache at {CACHE} — run fetch_exog.py first")
    cache = json.loads(CACHE.read_text())
    rows = []
    for series, zs in cache.items():
        if series == "meta" or not isinstance(zs, dict):
            continue  # meta block: fetched/source, not a series
        for d, v in zs.items():
            rows.append((series, d, float(v)))
    if not rows:
        raise SystemExit("[exog] cache empty")
    con = duckdb.connect(STORE)
    n_by_series = {}
    for s, d, v in rows:
        n_by_series[s] = n_by_series.get(s, 0) + 1
    for s, n in n_by_series.items():
        mx = con.execute("SELECT MAX(date) FROM exog WHERE series = ?", [s]).fetchone()[0]
        if mx:
            con.execute("DELETE FROM exog WHERE series = ? AND date > ?", [s, mx])
    # last-writer-wins dedupe on (series, date)
    con.execute("DELETE FROM exog WHERE rowid IN (SELECT rowid FROM (SELECT rowid, ROW_NUMBER() OVER (PARTITION BY series, date ORDER BY rowid DESC) rn FROM exog WHERE series LIKE 'COT:%') WHERE rn > 1)")
    con.execute("DELETE FROM exog WHERE series LIKE 'COT:%'")
    con.execute("INSERT INTO exog SELECT * FROM (VALUES " + ",".join(
        f"('{s}', '{d}', {v})" for s, d, v in rows) + ") t(series, date, value)")
    con.close()
    print(f"[exog] materialized {len(rows)} rows over {len(n_by_series)} COT series -> {STORE}")


if __name__ == "__main__":
    main()
