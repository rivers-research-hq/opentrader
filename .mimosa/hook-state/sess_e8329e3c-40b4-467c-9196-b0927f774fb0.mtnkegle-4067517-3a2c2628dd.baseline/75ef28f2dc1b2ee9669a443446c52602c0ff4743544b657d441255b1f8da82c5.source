#!/usr/bin/env python3
"""OpenTrader Data Accumulator — the exogenous-data pipeline.

Mirrors the hedge-fund/ETF data strategy: continuously acquire many datasets,
normalize to the market calendar, store them in a uniform lake, refresh on
schedule, and run EVERY dataset through the session's falsifier battery so
the evidence accumulates in a ledger — instead of one-shot hunches.

Architecture:
  catalog/          — registry: every dataset, its acquirer, schedule, range, status
  data_lake/        — normalized daily series (parquet), one file per dataset
  evidence/         — falsifier results ledger (JSON): every test, every era
  acquire/          — one module per source (FRED, EIA, USDA, ETF, insider, ...)
  refresh.py        — run all due acquirers, update lake + catalog
  falsify.py        — run the regime-gate battery on a dataset, record evidence

The VIX gate (data/vix_gate.py) is a consumer; every future dataset that
survives the battery becomes a gate candidate. Datasets that fail accumulate
as negative evidence — that IS the strategy's value.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ACCUM = PROJECT / "data" / "accumulator"
CATALOG_DB = ACCUM / "catalog.db"
LAKE = ACCUM / "lake"
EVIDENCE = ACCUM / "evidence"
SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    name TEXT PRIMARY KEY,          -- dataset id, e.g. 'fred.T10Y2Y'
    source TEXT NOT NULL,           -- acquirer module, e.g. 'fred'
    description TEXT,
    frequency TEXT,                 -- daily | monthly | quarterly
    lag_days INTEGER DEFAULT 0,     -- publication lag (13F = 45)
    license TEXT DEFAULT 'free',
    status TEXT DEFAULT 'live',     -- live | stale | failed | dead
    first_seen TEXT,
    last_refresh TEXT,
    obs_start TEXT, obs_end TEXT,
    refresh_secs INTEGER DEFAULT 86400,  -- refresh cadence
    notes TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    dataset TEXT NOT NULL,
    tested_at TEXT,
    era INTEGER,                    -- window index
    direction INTEGER,              -- +1 / -1
    n_days INTEGER, n_hi INTEGER,
    diff_pp REAL, boot_pctile REAL,
    survived INTEGER DEFAULT 0,     -- 1 if >=95th in >=2 eras same sign
    PRIMARY KEY (dataset, tested_at, era, direction)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT, finished TEXT,
    datasets_refreshed INTEGER, datasets_tested INTEGER,
    survivors TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    ACCUM.mkdir(parents=True, exist_ok=True)
    for d in (LAKE, EVIDENCE):
        d.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CATALOG_DB)
    conn.executescript(SCHEMA)
    return conn


def register_dataset(conn, name, source, description, frequency="daily",
                     lag_days=0, license="free", refresh_secs=86400, notes=""):
    conn.execute(
        "INSERT OR IGNORE INTO datasets (name, source, description, frequency,"
        " lag_days, license, first_seen, refresh_secs, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        (name, source, description, frequency, lag_days, license, utcnow(),
         refresh_secs, notes))
    conn.commit()


def update_dataset(conn, name, **kw):
    cols = ", ".join(f"{k}=?" for k in kw)
    conn.execute(f"UPDATE datasets SET {cols} WHERE name=?", (*kw.values(), name))
    conn.commit()


def list_datasets(conn, status=None) -> list[dict]:
    q = "SELECT * FROM datasets" + (" WHERE status=?" if status else "")
    rows = conn.execute(q, (status,) if status else ()).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM datasets").description]
    return [dict(zip(cols, r)) for r in rows]


def record_evidence(conn, dataset, era, direction, n_days, n_hi, diff_pp,
                    boot_pctile, survived):
    conn.execute(
        "INSERT OR REPLACE INTO evidence (dataset, tested_at, era, direction,"
        " n_days, n_hi, diff_pp, boot_pctile, survived) VALUES (?,?,?,?,?,?,?,?,?)",
        (dataset, utcnow(), era, direction, n_days, n_hi, diff_pp, boot_pctile,
         int(survived)))
    conn.commit()


def dataset_evidence(conn, name) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM evidence WHERE dataset=? ORDER BY tested_at, era, direction",
        (name,)).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM evidence").description]
    return [dict(zip(cols, r)) for r in rows]


if __name__ == "__main__":
    conn = connect()
    print("catalog tables:", [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")])
    print("datasets:", len(list_datasets(conn)))
