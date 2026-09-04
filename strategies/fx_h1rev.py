#!/usr/bin/env python3
"""fx_h1rev — H1 mean-reversion lane (map #174 #179).

RSI(2) fade, long-only v1: enter when the last closed H1 bar's RSI(2) drops
below 10 — a deeply oversold reading — on majors not held by any other lane.
2000u, server SL/TP 1x / 1.5x ATR-H1 (h1-mom's convention), 12h max hold,
one concurrent position. Control twin to h1-mom: same bars, opposite thesis.
Shorts deferred (documented v1 boundary).

Arbitration (map #174 #176): the entry pool excludes symbols held by any
other lane, and a pre-order re-check guards the race between staggered
crons. Reconciliation is NOT done here: the hourly fx_runner --intraday
(:00) and the daily 17:10 run own the ledger cursor — one reconciler avoids
cursor races; the ≤1h ledger-lag bound holds.

State:   data/fx_h1rev.json   (cache only — venue is authoritative)
Fills:   data/fx_ledger.jsonl (shared, tag h1-rev)
Cron:    hourly at :15 (FX weekdays)
Usage:   python3 -m strategies.fx_h1rev [--once]   (default: dry)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402
from strategies.fx_runner import (_venue_book, _venue_net, _digits,  # noqa: E402
                                  _append_ledger, _parse_opened, atr14,
                                  econ_blackout, held_by_other_tags, foreign_holds)

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_h1rev.json"

TAG = "h1-rev"
UNITS = 2000
RSI_BUY = 10.0      # fade trigger: RSI(2) below 10
ATR_STOP = 1.0      # stop = entry - 1.0 * ATR-H1
ATR_TP = 1.5        # target = entry + 1.5 * ATR-H1
MAX_HOLD_H = 12


def rsi2(closes):
    """2-period RSI (Cutler form: mean of the last 2 gains/losses — with a
    period this short, Wilder smoothing and a simple mean coincide closely,
    and the simple form is unit-testable). None when there is no signal:
    fewer than 3 closes, or a perfectly flat window (avg gain == avg loss
    == 0 tells us nothing about mean reversion)."""
    if len(closes) < 3:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(len(closes) - 2, len(closes))]
    avg_gain = sum(max(d, 0.0) for d in deltas) / 2.0
    avg_loss = sum(max(-d, 0.0) for d in deltas) / 2.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else None
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[h1-rev] connect failed")
    now = datetime.now(timezone.utc)
    book = {s: i for s, i in _venue_book(ex).items() if i["owner"] == TAG}
    fills = []

    # close: stale holds (12h); venue-closed positions just drop out
    for sym in list(book):
        net = _venue_net(ex, sym)
        if not net:
            book.pop(sym, None)
            print(f"[h1-rev] {sym} venue-closed (SL/TP) — reconciled by fx_runner")
            continue
        opened = _parse_opened(book[sym].get("opened"))
        age_h = (now - opened).total_seconds() / 3600 if opened else 0.0
        if abs(net - UNITS) > 1e-9:
            print(f"[h1-rev] !! {sym} venue net {net} != ours {UNITS} — close deferred")
            continue
        if age_h >= MAX_HOLD_H:
            if dry:
                print(f"[h1-rev] (dry) would CLOSE {sym} (max-hold-12h)")
                continue
            close_side = "SELL" if net > 0 else "BUY"
            r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
            if r.status != "filled":
                print(f"[h1-rev] CLOSE {sym} REJECTED ({r.status}) — retried next run")
                continue
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                          "reason": "h1-rev-maxhold"})
            print(f"[h1-rev] CLOSE {sym} (max-hold-12h) -> filled @ {r.price}")
            book.pop(sym, None)
        else:
            print(f"[h1-rev] holding {sym} ({age_h:.1f}h, net {net})")

    # entry: most oversold RSI(2) below 10, one concurrent position
    others = held_by_other_tags(ex, TAG)
    signals = {}
    for sym in ex.discover_symbols():
        if sym in book or sym in others:
            continue
        bars = ex.get_bars(sym, "1h", 20)
        if len(bars) < 10:
            continue
        r = rsi2([b.close for b in bars])
        if r is not None and r < RSI_BUY:
            signals[sym] = r
    ranked = sorted(signals.items(), key=lambda kv: kv[1])[:1]
    if not ranked:
        print(f"[h1-rev] no entries ({len(signals)} signal(s) pool-wide, {len(book)} held)")
    for sym, r in ranked:
        if dry:
            print(f"[h1-rev] (dry) would OPEN {sym} {UNITS}u — RSI2 {r:.1f}")
            continue
        if foreign_holds(ex, sym, TAG):
            print(f"[h1-rev] {sym} held by another lane at order time — skipped (arbitration)")
            continue
        blocked, why = econ_blackout(now, sym)  # hour-lane news gate (map #174)
        if blocked:
            print(f"[h1-rev] {sym} entry BLOCKED — {why}")
            continue
        bars = ex.get_bars(sym, "1h", 20)
        px = ex.get_current_price(sym)
        atr = atr14(bars) if len(bars) >= 15 else 0.0
        if not px or not atr:
            print(f"[h1-rev] !! {sym} no price/ATR — skipped")
            continue
        d = _digits(sym)
        sl = round(px - ATR_STOP * atr, d)
        tp = round(px + ATR_TP * atr, d)
        o = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp, tag=TAG)
        if o.status != "filled":
            print(f"[h1-rev] OPEN {sym} REJECTED ({o.status}) — retried next run")
            continue
        fills.append({"timestamp": o.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": o.price, "order_id": o.order_id,
                      "reason": "h1-rev-rsi2", "sl": sl, "tp": tp})
        book[sym] = {"units": UNITS, "opened": now.isoformat(), "entry": o.price,
                     "sl": sl, "tp": tp}
        print(f"[h1-rev] OPEN {sym} {UNITS}u -> filled @ {o.price:.5f} RSI2 {r:.1f} SL {sl} TP {tp}")

    _append_ledger(fills)
    if not dry:
        STATE.write_text(json.dumps({"positions": book, "updated": now.isoformat()}, indent=2))
        print(f"[h1-rev] state written ({len(book)} positions)")
    else:
        print("[h1-rev] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    run(dry)


if __name__ == "__main__":
    main()
