#!/usr/bin/env python3
"""fx_expand_universe — add OANDA practice FX pairs to the accrual store's
bars table (the fxexpert loop's data engine, loop decision 2026-09-06 "1").

The 16-pair panel converged to an information-limited plateau (IC ~0.021 /
PF ~1.02 vs gate 1.05 — see fx-expert-loop doc §v0.3); this widens the
cross-section with every tradable pure-FX practice pair not already in the
store. Read-only venue pulls (mid prices, incomplete bars dropped), same
endpoints as build_accrual_store.build_bars. Additive and idempotent per
symbol (DELETE+INSERT per pair); the full builder reproduces the same rows
on its next run. Resumable: pairs with >1000 stored D1 bars are skipped.

Usage: python3 scripts/fx_expand_universe.py [--h1]   (default D1 only)
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

STORE = "/home/mrc/opentrader-data/store.duckdb"
CCYS = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "MXN",
        "ZAR", "TRY", "NOK", "SEK", "CZK", "HUF", "PLN", "SGD", "CNH", "THB"}


def main(do_h1=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("oanda connect failed")
    inst = ex._request("GET",
                       f"/v3/accounts/{ex._account_id}/instruments?state=ENABLED"
                       ).get("instruments", [])
    names = sorted(i["name"] for i in inst
                   if i.get("type") == "CURRENCY" and len(i["name"]) == 7
                   and i["name"][3] == "_")
    existing = {r[0] for r in duckdb.connect(STORE, read_only=True).execute(
        "SELECT DISTINCT symbol FROM bars").fetchall()}
    targets = sorted(
        s for s in names
        if s[:3] in CCYS and s[4:] in CCYS and s not in existing)
    print(f"[universe] {len(names)} practice instruments, {len(existing)} stored; "
          f"new FX pairs: {len(targets)}")
    print(f"[universe] {', '.join(targets)}")

    con = duckdb.connect(STORE)
    cols = ["symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]

    def write(sym, tf, rows):
        if not rows:
            print(f"  {sym} {tf}: 0 bars — skipped", flush=True)
            return
        df = pd.DataFrame(rows, columns=cols)
        con.execute("DELETE FROM bars WHERE symbol = ? AND timeframe = ?", [sym, tf])
        con.register("new_bars", df)
        con.execute("INSERT INTO bars SELECT * FROM new_bars")
        con.unregister("new_bars")
        print(f"  {sym} {tf}: {len(rows)} bars "
              f"({rows[0]['ts'].date()} -> {rows[-1]['ts'].date()})", flush=True)

    for sym in targets:
        done = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol = ? AND timeframe = '1d'",
            [sym]).fetchone()[0]
        if done > 1000:
            print(f"  {sym}: already present ({done} D1 rows) — skipped", flush=True)
            continue
        try:
            d1 = ex.get_bars(sym, "1d", 5000)
            rows = [{"symbol": sym, "timeframe": "1d",
                     "ts": datetime.fromtimestamp(b.timestamp, tz=timezone.utc).replace(tzinfo=None),
                     "open": b.open, "high": b.high, "low": b.low,
                     "close": b.close, "volume": b.volume} for b in d1]
            write(sym, "1d", rows)
        except Exception as e:
            print(f"  {sym} D1 FAILED: {e}", flush=True)
            continue
        if not do_h1:
            continue
        cursor = datetime(2008, 1, 1, tzinfo=timezone.utc)
        end = datetime.now(timezone.utc)
        calls = 0
        rows = []
        while cursor < end and calls < 40:
            try:
                r = ex._request('GET', f"/v3/instruments/{sym}/candles"
                                f"?granularity=H1&from={cursor.isoformat()}&count=5000&price=M")
            except Exception as e:
                print(f"  {sym} H1 page {calls} FAILED: {e}", flush=True)
                break
            calls += 1
            c = r.get('candles', [])
            if not c:
                break
            for b in c:
                if not b.get('complete', True):
                    continue
                m = b.get('mid') or {}
                if not m.get('c'):
                    continue
                ts = datetime.fromisoformat(b['time'].replace('Z', '+00:00')).replace(tzinfo=None)
                rows.append({"symbol": sym, "timeframe": "1h", "ts": ts,
                             "open": float(m['o']), "high": float(m['h']),
                             "low": float(m['l']), "close": float(m['c']),
                             "volume": float(b.get('volume', 0))})
            cursor = datetime.fromisoformat(c[-1]['time'].replace('Z', '+00:00'))
            time.sleep(0.3)
        write(sym, "1h", rows)
    con.close()
    total = duckdb.connect(STORE, read_only=True).execute(
        "SELECT timeframe, COUNT(DISTINCT symbol), COUNT(*) FROM bars GROUP BY 1").fetchall()
    print(f"[universe] store now: {total}")


if __name__ == "__main__":
    main("--h1" in sys.argv)
