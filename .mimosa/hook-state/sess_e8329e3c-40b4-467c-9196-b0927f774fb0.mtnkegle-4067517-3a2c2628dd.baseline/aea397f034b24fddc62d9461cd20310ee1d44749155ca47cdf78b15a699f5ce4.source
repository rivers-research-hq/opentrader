#!/usr/bin/env python3
"""fx_watchdog — fast shock-response lane (15-minute cron).

The daily/weekly lanes are blind between runs; their only protection is the
server-side stop, which does nothing against GAPS (a gapped stop fills at the
next available price, not at the stop — SNB-2015 class events). The watchdog
closes that gap: it watches every open position and flattens at market when a
SHOCK SIGNATURE appears — a fast adverse move (last 2 H1 bars against the
position by >= 0.75x D1 ATR) while the position is already meaningfully
underwater (>= 0.5x D1 ATR). Acting during the shock beats waiting for a
slippage-prone stop fill.

Authority (deliberate override, documented): the watchdog may CLOSE any
tagged position — mom-k5, c08-fade, h1-mom — but NEVER opens. Exception: it
skips the "crash" tag, because the crash-test book exists to measure
UNPROTECTED outcomes.

Signature semantics: this is emergency response, not strategy — it will
sometimes flatten a position the SL would have saved. That is accepted: the
watchdog only fires on velocity + depth together, and a move this fast is
more likely to gap the stop than to reverse.

Usage:   python3 -m strategies.fx_watchdog [--once]   (default: dry)
Cron:    */15 (24/7 — shocks do not keep market hours)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402
from strategies.fx_runner import (_venue_book, _venue_net, _digits,  # noqa: E402
                                  _append_ledger, atr14, LEDGER, PROJECT)

STATE = PROJECT / "data" / "fx_watchdog_state.json"
LOCK = PROJECT / "data" / "fx_watchdog.lock"

SKIP_TAGS = {"crash"}          # the crash-test book measures unprotected outcomes
VELOCITY_ATR = 0.75            # 2-H1-bar adverse move >= 0.75x D1 ATR
DEPTH_ATR = 0.5                # ...while adverse excursion >= 0.5x D1 ATR


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[wd] connect failed")
    book = _venue_book(ex)
    if not book:
        print("[wd] book flat — nothing to watch")
        return
    print(f"[wd] watching {len(book)} position(s): "
          f"{ {s: i['owner'] for s, i in book.items()} }")
    fills = []
    now = datetime.now(timezone.utc)

    for sym, info in book.items():
        if info["owner"] in SKIP_TAGS:
            print(f"[wd] {sym}: skipped (tag {info['owner']} — unprotected by design)")
            continue
        net = _venue_net(ex, sym)
        if not net or abs(net - info["units"]) > 1e-9:
            print(f"[wd] {sym}: venue net {net} != book {info['units']} — deferred")
            continue
        d1 = ex.get_bars(sym, "1d", 20)
        h1 = ex.get_bars(sym, "1h", 5)
        if len(d1) < 16 or len(h1) < 3:
            print(f"[wd] {sym}: insufficient bars — skipped")
            continue
        atr = atr14(d1)
        if not atr or atr <= 0:
            continue
        px = ex.get_current_price(sym)
        long = net > 0
        adverse = (info["entry"] - px) if long else (px - info["entry"])
        velocity = (h1[-2].close - h1[-1].close) if long else (h1[-1].close - h1[-2].close)
        depth_ratio = adverse / atr
        vel_ratio = velocity / atr
        status = (f"{sym} ({info['owner']}) {'long' if long else 'short'} "
                  f"adverse {depth_ratio:.2f}xATR, 2h velocity {vel_ratio:+.2f}xATR")
        if adverse > 0 and depth_ratio >= DEPTH_ATR and vel_ratio >= VELOCITY_ATR:
            print(f"[wd] SHOCK SIGNATURE — flattening {status}")
            if dry:
                print(f"[wd] (dry) would CLOSE {sym} {abs(net)}u")
                continue
            close_side = "SELL" if long else "BUY"
            r = ex.place_order(sym, close_side, abs(net), "market", tag=info["owner"])
            if r.status != "filled":
                print(f"[wd] flatten {sym} REJECTED — will retry next cycle")
                continue
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price,
                          "order_id": r.order_id, "reason": "watchdog-shock-flatten",
                          "owner": info["owner"],
                          "depth_atr": round(depth_ratio, 3),
                          "velocity_atr": round(vel_ratio, 3)})
        else:
            print(f"[wd] {status} — ok")

    _append_ledger(fills)
    if not dry:
        STATE.write_text(json.dumps({"checked": now.isoformat(),
                                     "flattened": len(fills)}, indent=2))
    print(f"[wd] cycle done: {len(fills)} flattening(s)")


def main():
    dry = "--once" not in sys.argv
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
    except FileExistsError:
        raise SystemExit("[wd] another watchdog instance is running — exiting")
    try:
        run(dry=dry)
    finally:
        os.close(fd)
        os.unlink(LOCK)


if __name__ == "__main__":
    main()
