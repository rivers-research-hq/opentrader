#!/usr/bin/env python3
"""fx_runner — Track B daily trading loop on OANDA practice (demo money).

Strategy v0 (momentum port, momtrend/laggard DNA): rank the FX majors by
5-day return on D1 candles; go long the top-2 with positive momentum;
server-side stop-loss and take-profit attached on every fill (1.5x / 2.5x
ATR-14); 14-day max hold. Instruments that fall out of the top-2 are closed.

This is the DEMO proving ground for the Track B book (platform timeline):
its fills/positions accrue ADR-0002 clause-1 evidence through real venue
plumbing. Not live order flow; demo money.

State:   data/fx_state.json   (positions, entries, opened dates — fx_runner sole writer)
Fills:   data/fx_ledger.jsonl (append-only, composite dedup, real OANDA ids)
Usage:   python3 -m strategies.fx_runner [--dry] [--once]
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_state.json"
LEDGER = PROJECT / "data" / "fx_ledger.jsonl"

TOP_N = 2          # long the top-2 majors by momentum
K = 5              # momentum lookback (days)
UNITS = 100        # demo size per instrument
ATR_STOP = 1.5     # stop = entry - 1.5 * ATR14
ATR_TP = 2.5       # target = entry + 2.5 * ATR14
MAX_HOLD_DAYS = 14


def _fill_key(f):
    return (str(f.get("timestamp", "")), f.get("symbol", ""), (f.get("side") or "").lower(),
            f.get("quantity", 0), f.get("price", 0))


def _append_ledger(fills):
    if not fills:
        return
    seen = set()
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    seen.add(_fill_key(json.loads(line)))
                except Exception:
                    pass
    with LEDGER.open("a") as f:
        for fill in fills:
            if _fill_key(fill) in seen:
                continue
            seen.add(_fill_key(fill))
            f.write(json.dumps(fill, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def atr14(bars):
    tail = bars[-15:]
    trs = []
    for i in range(1, len(tail)):
        h, l, pc = tail[i].high, tail[i].low, tail[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[fx] connect failed — check config/oanda_keys.json")
    bal = ex.get_balance()
    print(f"[fx] connected: balance ${bal.cash:,.2f} | instruments {ex.discover_symbols()}")

    # 1. momentum rank
    mom = {}
    atrs = {}
    for sym in ex.discover_symbols():
        bars = ex.get_bars(sym, "1d", 20)
        if len(bars) < K + 2:
            continue
        mom[sym] = bars[-1].close / bars[-1 - K].close - 1.0
        atrs[sym] = atr14(bars)
    ranked = sorted(mom.items(), key=lambda kv: -kv[1])
    print("[fx] momentum (5d):")
    for sym, m in ranked:
        print(f"  {sym.ljust(10)} {m:+.4%}")

    target = {sym for sym, m in ranked[:TOP_N] if m > 0}
    print(f"[fx] target book: {sorted(target) or '(flat — no positive momentum)'}")

    state = json.loads(STATE.read_text()) if STATE.exists() else {"positions": {}}
    book = state.setdefault("positions", {})
    fills = []

    # 2. close: positions no longer in target or beyond max hold
    today = datetime.now(timezone.utc)
    for sym in list(book):
        age_days = (today - datetime.fromisoformat(book[sym]["opened"])).days
        if sym in target and age_days < MAX_HOLD_DAYS:
            continue
        reason = "max-hold" if age_days >= MAX_HOLD_DAYS else "out-of-target"
        net = bal.positions.get(sym, 0) or book[sym].get("units", 0)
        if not net:
            book.pop(sym, None)
            continue
        close_side = "SELL" if net > 0 else "BUY"
        if dry:
            print(f"[fx] (dry) would CLOSE {sym} ({reason}) {abs(net)} units")
            continue
        r = ex.place_order(sym, close_side, abs(net), "market")
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                      "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                      "reason": reason})
        print(f"[fx] CLOSE {sym} ({reason}) -> {r.status} @ {r.price}")
        book.pop(sym, None)

    # 3. open: target instruments not in book
    for sym in sorted(target):
        if sym in book:
            continue
        atr = atrs.get(sym, 0.0)
        px = ex.get_current_price(sym)
        sl = px - ATR_STOP * atr if atr else None
        tp = px + ATR_TP * atr if atr else None
        if dry:
            print(f"[fx] (dry) would OPEN  {sym} 100 units SL {sl and round(sl, 5)} TP {tp and round(tp, 5)}")
            continue
        r = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp)
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "momentum-entry", "sl": sl, "tp": tp})
        if r.status == "filled":
            book[sym] = {"units": UNITS, "opened": today.isoformat(), "entry": r.price,
                         "sl": sl, "tp": tp}
        print(f"[fx] OPEN  {sym} 100 units -> {r.status} @ {r.price:.5f} "
              f"SL {sl and round(sl, 5)} TP {tp and round(tp, 5)}")

    # 4. persist
    _append_ledger(fills)
    if not dry:
        STATE.write_text(json.dumps({"positions": book, "updated": today.isoformat()}, indent=2))
        print(f"[fx] state written: {STATE} ({len(book)} positions)")
    else:
        print("[fx] dry run — no state write")
    bal2 = ex.get_balance()
    print(f"[fx] book after: ${bal2.cash:,.2f} cash | positions {bal2.positions}")
    return book


def main():
    dry = "--once" not in sys.argv
    run(dry=dry)


if __name__ == "__main__":
    main()
