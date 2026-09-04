#!/usr/bin/env python3
"""Accumulator refresh — the continuous acquisition cadence.

Runs every due dataset's acquirer, updates the lake + catalog, then runs the
falsifier battery on anything new or stale. This is the machine that keeps
the data lake growing and the evidence ledger current — the actual
'data accumulation strategy' applied.

Cron-friendly: run hourly/daily; each acquirer refreshes on its own cadence.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from data.acquire import ACQUIRERS, save_to_lake  # noqa: E402
from data.accumulator import (  # noqa: E402
    connect, list_datasets, update_dataset, utcnow, register_dataset,
    ACCUM, EVIDENCE,
)
from data.falsify import falsify_dataset, summarize  # noqa: E402

# default portfolio: (dataset, source, mode)
PORTFOLIO = [
    ("fred.VIXCLS", "fred", "level"),
    ("fred.T10Y2Y", "fred", "level"),
    ("fred.BAA", "fred", "level"),
    ("fred.AAA", "fred", "level"),
    ("fred.DTWEXBGS", "fred", "pct"),
    ("fred.DFF", "fred", "level"),
    ("fred.DCOILWTICO", "fred", "pct"),
    ("fred.PPIACO", "fred", "pct"),
    ("fred.T10YIE", "fred", "level"),
    ("sec.form4", "insider", "count_pct"),
    ("etf.SPY", "etf", "mom12_1"),
    ("etf.TLT", "etf", "level"),
    ("etf.IEF", "etf", "level"),
    ("etf.HYG", "etf", "level"),
    ("etf.LQD", "etf", "level"),
    ("etf.GLD", "etf", "level"),
    ("etf.DBC", "etf", "level"),
    ("etf.EEM", "etf", "level"),
    ("etf.VNQ", "etf", "level"),
]

SOURCE_OF = {name: src for name, src, _ in PORTFOLIO}
MODE_OF = {name: mode for name, _, mode in PORTFOLIO}


def _refresh_one(ds, force, now):
    """Refresh + falsify a single dataset (called concurrently)."""
    from data.accumulator import connect as acc_connect
    name = ds["name"]
    src = SOURCE_OF.get(name) or ds["source"]
    acquirer = ACQUIRERS.get(src)
    if acquirer is None:
        return None
    # each thread gets its own sqlite connection (sqlite is thread-local)
    conn = acc_connect()
    ds = {**ds, "conn": conn}
    last = ds.get("last_refresh")
    age = (now - datetime.fromisoformat(last).timestamp()) if last else 1e18
    cadence = ds.get("refresh_secs") or 86400
    if not force and age < cadence:
        conn.close()
        return None
    try:
        t0 = time.time()
        # acquirers take the BARE series id (strip the 'source.' prefix)
        bare = name.split(".", 1)[1] if "." in name else name
        series = acquirer(bare)
        start, end, n = save_to_lake(name, series)
        update_dataset(ds["conn"], name, last_refresh=utcnow(), status="live",
                       obs_start=start, obs_end=end)
        print(f"[refresh] {name}: {n} obs ({start}->{end}) in "
              f"{time.time()-t0:.1f}s", flush=True)
    except Exception as e:
        update_dataset(ds["conn"], name, status="failed",
                       notes=f"last error: {e}")
        print(f"[refresh] {name}: FAILED {e}", flush=True)
        return None
    tested = ds["conn"].execute(
        "SELECT COUNT(*) FROM evidence WHERE dataset=?", (name,)).fetchone()[0]
    if tested == 0 or force:
        try:
            with _FALSIFY_SEM:  # each falsify loads the 2.7M registry (~1.5GB)
                res = falsify_dataset(name, ds["conn"],
                                      mode=MODE_OF.get(name, "level"))
            summary = summarize(ds["conn"], name)
            print(f"[falsify] {name}: {len(res)} era-results "
                  f"survivor={summary['survivor']}", flush=True)
            return (name, summary["survivor"])
        except Exception as e:
            print(f"[falsify] {name}: FAILED {e}", flush=True)
    return None


import threading
_FALSIFY_SEM = threading.Semaphore(1)


def refresh(conn, force=False, max_age_secs=86400, workers=4) -> dict:
    """Refresh due datasets in parallel (thread pool); falsify each with its
    own process pool. Returns stats."""
    from concurrent.futures import ThreadPoolExecutor
    stats = {"refreshed": 0, "tested": 0, "survivors": []}
    now = time.time()
    due = list_datasets(conn)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for out in ex.map(lambda d: _refresh_one(d, force, now), due):
            if out is None:
                continue
            name, survived = out
            stats["refreshed"] += 1
            stats["tested"] += 1
            if survived:
                stats["survivors"].append(name)
    return stats


def ensure_portfolio(conn):
    for name, src, mode in PORTFOLIO:
        desc = {"fred": "FRED economic series", "insider": "SEC insider filings",
                "etf": "cross-asset ETF close"}.get(src, src)
        register_dataset(conn, name, src, desc, notes=f"falsify mode={mode}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    conn = connect()
    ensure_portfolio(conn)
    t0 = time.time()
    stats = refresh(conn, force=force)
    print("=" * 60)
    print(f"refresh: {stats['refreshed']} refreshed, {stats['tested']} tested, "
          f"{len(stats['survivors'])} survivors in {time.time()-t0:.0f}s")
    print("survivors:", stats["survivors"] or "none (VIX is the known one)")
    print(f"evidence ledger: {EVIDENCE}")
