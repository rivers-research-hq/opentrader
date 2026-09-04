#!/usr/bin/env python3
"""fx_h4brk — H4 Donchian-20 breakout lane (map #174 #180).

Enter long when an H4 close exceeds the prior 20-bar channel high (long-only
v1, consistent with the book's other lanes). 2000u. Exit is the system's
native one: a close below the prior 20-bar channel low — NO fixed take-profit,
because a Donchian system's edge is the skew (few large winners, many small
losers) and a fixed TP amputates exactly the tail that pays for the churn.
Server SL at 2x ATR-H4 caps single-trade damage; 48h max hold bounds
exposure. One concurrent position.

Arbitration (map #174 #176): entry pool excludes symbols held by any other
lane; a pre-order re-check guards staggered-cron races. Reconciliation is
NOT done here — fx_runner owns the ledger cursor (≤1h bound).

State:   data/fx_h4brk.json   (cache only — venue is authoritative)
Fills:   data/fx_ledger.jsonl (shared, tag h4-brk)
Cron:    every 4h at :30 (FX weekdays)
Usage:   python3 -m strategies.fx_h4brk [--once]   (default: dry)
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
STATE = PROJECT / "data" / "fx_h4brk.json"

TAG = "h4-brk"
UNITS = 2000
CHANNEL = 20
ATR_STOP = 2.0      # stop = entry - 2.0 * ATR-H4
MAX_HOLD_H = 48


def channel(bars, n=CHANNEL):
    """Prior n-bar Donchian channel, EXCLUDING the latest bar (the signal
    bar): a close at exactly the prior high is not a breakout."""
    window = bars[-(n + 1):-1]
    return max(b.high for b in window), min(b.low for b in window)


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[h4-brk] connect failed")
    now = datetime.now(timezone.utc)
    book = {s: i for s, i in _venue_book(ex).items() if i["owner"] == TAG}
    fills = []

    # close: opposite-channel breach or stale hold (48h)
    for sym in list(book):
        net = _venue_net(ex, sym)
        if not net:
            book.pop(sym, None)
            print(f"[h4-brk] {sym} venue-closed (SL) — reconciled by fx_runner")
            continue
        opened = _parse_opened(book[sym].get("opened"))
        age_h = (now - opened).total_seconds() / 3600 if opened else 0.0
        if abs(net - UNITS) > 1e-9:
            print(f"[h4-brk] !! {sym} venue net {net} != ours {UNITS} — close deferred")
            continue
        bars = ex.get_bars(sym, "4h", CHANNEL + 2)
        _, ch_low = channel(bars) if len(bars) >= CHANNEL + 1 else (None, None)
        breach = ch_low is not None and bars[-1].close < ch_low
        if breach or age_h >= MAX_HOLD_H:
            reason = "h4-brk-exit" if breach else "h4-brk-maxhold"
            if dry:
                print(f"[h4-brk] (dry) would CLOSE {sym} ({reason})")
                continue
            close_side = "SELL" if net > 0 else "BUY"
            r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
            if r.status != "filled":
                print(f"[h4-brk] CLOSE {sym} REJECTED ({r.status}) — retried next run")
                continue
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                          "reason": reason})
            print(f"[h4-brk] CLOSE {sym} ({reason}) -> filled @ {r.price}")
            book.pop(sym, None)
        else:
            print(f"[h4-brk] holding {sym} ({age_h:.1f}h, net {net})")

    # entry: strongest fresh breakout, one concurrent position
    others = held_by_other_tags(ex, TAG)
    signals = {}
    for sym in ex.discover_symbols():
        if sym in book or sym in others:
            continue
        bars = ex.get_bars(sym, "4h", CHANNEL + 2)
        if len(bars) < CHANNEL + 1:
            continue
        ch_high, _ = channel(bars)
        margin = bars[-1].close / ch_high - 1.0 if ch_high else 0.0
        if bars[-1].close > ch_high:
            signals[sym] = margin
    ranked = sorted(signals.items(), key=lambda kv: -kv[1])[:1]
    if not ranked:
        print(f"[h4-brk] no entries ({len(signals)} breakout(s) pool-wide, {len(book)} held)")
    for sym, margin in ranked:
        if dry:
            print(f"[h4-brk] (dry) would OPEN {sym} {UNITS}u — breakout +{margin:.4%}")
            continue
        if foreign_holds(ex, sym, TAG):
            print(f"[h4-brk] {sym} held by another lane at order time — skipped (arbitration)")
            continue
        blocked, why = econ_blackout(now, sym)  # hour-lane news gate (map #174)
        if blocked:
            print(f"[h4-brk] {sym} entry BLOCKED — {why}")
            continue
        bars = ex.get_bars(sym, "4h", CHANNEL + 2)
        px = ex.get_current_price(sym)
        atr = atr14(bars) if len(bars) >= 15 else 0.0
        if not px or not atr:
            print(f"[h4-brk] !! {sym} no price/ATR — skipped")
            continue
        sl = round(px - ATR_STOP * atr, _digits(sym))
        o = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, tag=TAG)
        if o.status != "filled":
            print(f"[h4-brk] OPEN {sym} REJECTED ({o.status}) — retried next run")
            continue
        fills.append({"timestamp": o.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": o.price, "order_id": o.order_id,
                      "reason": "h4-brk-donchian20", "sl": sl})
        book[sym] = {"units": UNITS, "opened": now.isoformat(), "entry": o.price, "sl": sl}
        print(f"[h4-brk] OPEN {sym} {UNITS}u -> filled @ {o.price:.5f} breakout +{margin:.4%} SL {sl}")

    _append_ledger(fills)
    if not dry:
        STATE.write_text(json.dumps({"positions": book, "updated": now.isoformat()}, indent=2))
        print(f"[h4-brk] state written ({len(book)} positions)")
    else:
        print("[h4-brk] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    run(dry)


if __name__ == "__main__":
    main()
