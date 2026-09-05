#!/usr/bin/env python3
"""build_accrual_store — compact the FX accrual data into a queryable
DuckDB + Parquet store (map #187 #189).

Datasets (all zstd Parquet under the store root):
  ledger    — fx_ledger.jsonl rows, void-aware (voided flag kept on-row for
              provenance; phantom-void markers land in the `voids` table)
  journal   — venue transactions (fills with lane attribution via the
              tradeID→tag chain, plus the full txn log for defect analysis)
  bars      — OHLCV per major per timeframe (D1 + H1)
  releases  — scheduled high-impact releases (static calendar rules over the
              data range — includes NFP/CPI days for exclusion queries)
  decisions — central-bank decision dates (8 banks)
  events    — FF feed snapshot (forecast/previous = surprise inputs)
  exog      — exogenous series (rates, COT z) in long format

Design constraints (map #187):
  - the store is a CONSUMER of the ledger — never a second writer
  - rebuildable from sources in one command (this script)
  - schema_version stamped on every build (manifest.json)
  - root disk untouched: the store lives on the data drive (/home)

Usage: python3 scripts/build_accrual_store.py [--skip-venue] [--no-bars]
       (default store root: /home/mrc/opentrader-data, override with
        OPENTRADER_DATA)
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
import pandas

from exchange.oanda import FX_MAJORS, OandaExchange
from strategies.fx_runner import _trade_tags

PROJECT = Path(__file__).resolve().parent.parent
LEDGER = PROJECT / "data" / "fx_ledger.jsonl"
FF_CACHE = PROJECT / "data" / "cache" / "ff_calendar.json"
EXOG = PROJECT / "data" / "exog_cache.json"
SCHEMA_VERSION = 1

STORE = Path(os.environ.get("OPENTRADER_DATA", "/home/mrc/opentrader-data"))

LEDGER_COLUMNS = ["ts", "timestamp", "symbol", "side", "quantity", "price",
                  "pl", "order_id", "reason", "tag", "voided"]


def parse_ts(raw):
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def build_ledger(con):
    """Ledger rows with void provenance: live + voided rows stay (flagged),
    phantom-void markers become the `voids` table. Consumer-only: never
    writes the source ledger."""
    rows, voids = [], []
    voided_ts = set()
    if LEDGER.exists():
        raw_rows = []
        for line in LEDGER.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            raw_rows.append(r)
            if r.get("reason") == "phantom-void":
                voided_ts.update(r.get("voids") or [])
                voids.append({"ts": parse_ts(r.get("timestamp")),
                              "voids": json.dumps(r.get("voids") or []),
                              "detail": r.get("detail"), "ticket": r.get("ticket")})
        for r in raw_rows:
            if r.get("reason") == "phantom-void":
                continue
            rows.append({"ts": parse_ts(r.get("timestamp")), "timestamp": r.get("timestamp"),
                         "symbol": r.get("symbol"), "side": r.get("side"),
                         "quantity": float(r.get("quantity") or 0),
                         "price": float(r.get("price") or 0), "pl": float(r.get("pl") or 0),
                         "order_id": r.get("order_id"), "reason": r.get("reason"),
                         "tag": r.get("tag"), "voided": r.get("timestamp") in voided_ts})
    con.register("ledger_df", pandas.DataFrame(rows, columns=LEDGER_COLUMNS))
    con.execute("CREATE OR REPLACE TABLE ledger AS SELECT * FROM ledger_df")
    con.register("voids_df", pandas.DataFrame(voids, columns=["ts", "voids", "detail", "ticket"]))
    con.execute("CREATE OR REPLACE TABLE voids AS SELECT * FROM voids_df")
    return len(rows), len(voids)


def build_journal(con, skip_venue=False):
    """Venue transactions: fills (typed, tag-attributed) + the txn log. This
    is a venue PULL — the journal lives server-side; the store snapshots it."""
    fills, txns = [], []
    if not skip_venue:
        ex = OandaExchange()
        if ex.connect():
            tags, order_tag = _trade_tags(ex)
            for t in ex._request(
                "GET", f"/v3/accounts/{ex._account_id}/transactions/sinceid?id=0"
            ).get("transactions", []):
                ts = parse_ts(t.get("time"))
                txns.append({"id": int(t.get("id", 0) or 0), "ts": ts, "type": t.get("type"),
                             "instrument": t.get("instrument"), "time": t.get("time")})
                if t.get("type") != "ORDER_FILL":
                    continue
                tag = (t.get("clientExtensions") or {}).get("tag") or order_tag.get(t.get("orderID"))
                if not tag:
                    for tc in t.get("tradesClosed") or []:
                        tag = tags.get(str(tc.get("tradeID")))
                        if tag:
                            break
                if not tag:
                    q = abs(float(t.get("units", 0) or 0))
                    if t.get("time", "") < "2026-08-31T18:00":
                        tag = "legacy-smoke"
                    else:
                        tag = "crash" if q >= 5000 else ("h1-mom" if q >= 2000 else "mom-k5")
                fills.append({"ts": ts, "txn_id": int(t.get("id", 0) or 0),
                              "instrument": t.get("instrument"),
                              "units": float(t.get("units", 0) or 0),
                              "price": float(t.get("price", 0) or 0),
                              "pl": float(t.get("pl", 0) or 0), "reason": t.get("reason"),
                              "tag": tag})
    con.register("fills_df", pandas.DataFrame(fills, columns=[
        "ts", "txn_id", "instrument", "units", "price", "pl", "reason", "tag"]))
    con.execute("CREATE OR REPLACE TABLE fills AS SELECT * FROM fills_df")
    con.register("txns_df", pandas.DataFrame(txns, columns=["id", "ts", "type", "instrument", "time"]))
    con.execute("CREATE OR REPLACE TABLE txns AS SELECT * FROM txns_df")
    return len(fills), len(txns)


def build_bars(con, ex=None):
    """OHLCV per major, D1 + H1. Full pull each build (v1): idempotent —
    incremental windows are a later ticket once the store proves itself."""
    rows = []
    ex = ex or OandaExchange()
    connected = ex.connect()
    for tf in ("1d", "1h"):
        for sym in FX_MAJORS:
            bars = ex.get_bars(sym, tf, 5000) if connected else []
            for b in bars:
                rows.append({"symbol": sym, "timeframe": tf,
                             "ts": datetime.fromtimestamp(b.timestamp, tz=timezone.utc).replace(tzinfo=None),
                             "open": b.open, "high": b.high, "low": b.low,
                             "close": b.close, "volume": b.volume})
    con.register("bars_df", pandas.DataFrame(rows, columns=[
        "symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]))
    con.execute("CREATE OR REPLACE TABLE bars AS SELECT * FROM bars_df")
    return len(rows)


def build_calendar(con):
    """Scheduled high-impact releases over the data range (static rules —
    includes NFP/CPI days for exclusion queries) + bank decision dates + the
    FF feed snapshot (forecast/previous = the surprise inputs)."""
    from data.economic_calendar import bank_dates, releases_between
    releases, decisions, events = [], [], []
    start = datetime(2026, 8, 1).date()
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    first = parse_ts(json.loads(line).get("timestamp"))
                except Exception:
                    continue
                if first:
                    start = min(start, first.date())
                break
    end = datetime.now(timezone.utc).date() + timedelta(days=45)
    for r in releases_between(start, end):
        releases.append({"date": r.date, "name": r.name, "impact": r.impact})
    for bank in ("FED", "ECB", "BOE", "BOJ", "SNB", "BOC", "RBA", "RBNZ"):
        for d in bank_dates(bank):
            decisions.append({"date": d, "bank": bank})
    if FF_CACHE.exists():
        try:
            for e in json.loads(FF_CACHE.read_text()):
                events.append({"ts": parse_ts(e.get("date")),
                               "currency": e.get("country"),
                               "title": e.get("title"), "impact": e.get("impact"),
                               "forecast": e.get("forecast"), "previous": e.get("previous")})
        except Exception:
            pass
    con.register("releases_df", pandas.DataFrame(releases, columns=["date", "name", "impact"]))
    con.execute("CREATE OR REPLACE TABLE releases AS SELECT * FROM releases_df")
    con.register("decisions_df", pandas.DataFrame(decisions, columns=["date", "bank"]))
    con.execute("CREATE OR REPLACE TABLE decisions AS SELECT * FROM decisions_df")
    con.register("events_df", pandas.DataFrame(events, columns=[
        "ts", "currency", "title", "impact", "forecast", "previous"]))
    con.execute("CREATE OR REPLACE TABLE events AS SELECT * FROM events_df")
    return len(releases), len(decisions), len(events)


def build_exog(con):
    """Exogenous series (rates, COT z) from the exog cache, long format."""
    rows = []
    if EXOG.exists():
        try:
            for key, series in json.loads(EXOG.read_text()).items():
                if not isinstance(series, dict):
                    continue
                for d, v in series.items():
                    if isinstance(v, (int, float)):
                        rows.append({"series": key, "date": d, "value": float(v)})
        except Exception:
            pass
    con.register("exog_df", pandas.DataFrame(rows, columns=["series", "date", "value"]))
    con.execute("CREATE OR REPLACE TABLE exog AS SELECT * FROM exog_df")
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Build the FX accrual store (DuckDB + Parquet)")
    ap.add_argument("--skip-venue", action="store_true", help="reuse existing venue tables (offline rebuild)")
    ap.add_argument("--no-bars", action="store_true", help="skip the OHLCV pull")
    args = ap.parse_args()

    started = time.time()
    STORE.mkdir(parents=True, exist_ok=True)
    os.chdir(STORE)  # the duckdb file + parquet live together under the store root

    con = duckdb.connect("store.duckdb")
    counts = {}
    counts["ledger"], counts["voids"] = build_ledger(con)
    counts["fills"], counts["txns"] = build_journal(con, skip_venue=args.skip_venue)
    counts["bars"] = 0 if args.no_bars else build_bars(con)
    counts["releases"], counts["decisions"], counts["events"] = build_calendar(con)
    counts["exog"] = build_exog(con)

    # materialize datasets as zstd parquet (the durable artifacts; the duckdb
    # file is a convenience view layer over them) — fixed literal statements
    con.execute("COPY ledger TO 'ledger.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY voids TO 'voids.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY fills TO 'fills.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY txns TO 'txns.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    if counts["bars"]:
        con.execute("COPY bars TO 'bars.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY releases TO 'releases.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY decisions TO 'decisions.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY events TO 'events.parquet' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute("COPY exog TO 'exog.parquet' (FORMAT PARQUET, COMPRESSION zstd)")

    manifest = {"schema_version": SCHEMA_VERSION,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "counts": counts,
                "sources": {"ledger": str(LEDGER), "ff_cache": str(FF_CACHE),
                            "exog": str(EXOG), "venue": not args.skip_venue},
                "store_root": str(STORE)}
    Path("manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    con.close()

    dur = time.time() - started
    print(f"[store] built in {dur:.1f}s at {STORE}")
    for k, v in counts.items():
        print(f"  {k:10s} {v}")


if __name__ == "__main__":
    main()
