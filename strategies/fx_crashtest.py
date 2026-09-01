#!/usr/bin/env python3
"""fx_crashtest — max-margin crash-test book (demo only).

Purpose (human decision 2026-09-01): answer "what does a liquidity crisis /
gap event actually do to an aggressive account" with data instead of a real
funeral. This lane runs MAX-MARGIN sizing — 5,000-unit positions, the
exposure a ~$300 account would hold at ~33:1 effective leverage — with the
same H1 momentum logic as the intraday lane, and tracks the equity curve a
$300 account would have experienced (realized + unrealized, plus peak
drawdown). Slippage is measured per fill: the mid captured immediately
before the order vs the fill price ("spread+slippage paid").

The book is UNPROTECTED BY DESIGN: the watchdog skips tag "crash" so that
gap events hit it the way they would hit an unprotected real account. Server
SL/TP (1x/1.5x ATR-H1) are still attached — that is what an aggressive
retail account would have. When a shock event occurs, the fills here are
the evidence.

State:   data/fx_crashtest.json   (sole writer; hypothetical-$300 tracker)
Fills:   data/fx_ledger.jsonl     (shared, tag crash, rows carry mid_before)
Usage:   python3 -m strategies.fx_crashtest [--once]   (default: dry)
Cron:    hourly at :30 (FX weekdays)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402
from strategies.fx_runner import (_venue_book, _venue_net, _digits,  # noqa: E402
                                  _append_ledger, atr14, PROJECT)

STATE = PROJECT / "data" / "fx_crashtest.json"
LOCK = PROJECT / "data" / "fx_crashtest.lock"

TAG = "crash"
UNITS = 5_000                 # ~$5k notional = the $300-account-at-max-margin model
MAX_POS, TOP_N = 2, 2
MAX_HOLD_H = 12
HYPOTHETICAL_CASH = 300.0     # the notional account this book crash-tests


def _load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"realized": 0.0, "peak_equity": HYPOTHETICAL_CASH,
            "max_dd": 0.0, "positions": {}}


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[crash] connect failed")
    book_all = _venue_book(ex)
    mine = {s: i for s, i in book_all.items() if i["owner"] == TAG}
    held = set(book_all)
    pool = [s for s in ex.discover_symbols() if s not in held]
    print(f"[crash] max-margin book (tag {TAG}) — pool: {pool}")

    state = _load_state()
    fills = []
    now = datetime.now(timezone.utc)

    # 1. exits: 12h hold or venue-closed (SL/TP) — measure stop slippage via
    #    reconciliation gap (venue fill price vs recorded SL)
    for sym in list(mine):
        info = mine[sym]
        opened = datetime.fromisoformat(info["opened"])
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        age_h = (now - opened).total_seconds() / 3600
        net = _venue_net(ex, sym)
        if abs(net - UNITS) > 1e-9 and net:
            print(f"[crash] !! {sym} venue net {net} != ours {UNITS} — deferred")
            continue
        if not net:
            state["positions"].pop(sym, None)
            print(f"[crash] {sym} venue-closed (SL/TP) — slippage visible in ledger reconciliation")
            continue
        if age_h >= MAX_HOLD_H:
            close_side = "SELL" if net > 0 else "BUY"
            if dry:
                print(f"[crash] (dry) would CLOSE {sym} (12h hold)")
                continue
            r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
            if r.status != "filled":
                print(f"[crash] CLOSE {sym} REJECTED — retry next cycle")
                continue
            pnl = (r.price - info["entry"]) * net if net > 0 else (info["entry"] - r.price) * abs(net)
            state["realized"] += pnl
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                          "reason": "crash-12h-hold", "pnl": round(pnl, 2),
                          "paper": True, "tag": TAG})
            print(f"[crash] CLOSE {sym} (12h) -> filled @ {r.price} pnl {pnl:+.2f}")
            mine.pop(sym, None)

    # 2. entries: top-2 H1 momentum, max-margin
    mom, atrs = {}, {}
    for sym in pool:
        bars = ex.get_bars(sym, "1h", 20)
        if len(bars) < 10:
            continue
        mom[sym] = bars[-1].close / bars[-9].close - 1.0
        trs = [max(bars[i].high - bars[i].low, abs(bars[i].high - bars[i - 1].close),
                   abs(bars[i].low - bars[i - 1].close)) for i in range(1, len(bars))]
        atrs[sym] = sum(trs) / len(trs)
    ranked = sorted(mom.items(), key=lambda kv: -kv[1])[:TOP_N]
    for sym, m in ranked:
        if m <= 0 or sym in mine or len(mine) >= MAX_POS:
            continue
        atr = atrs[sym]
        px_mid = ex.get_current_price(sym)
        prec = _digits(sym)
        sl, tp = round(px_mid - atr, prec), round(px_mid + 1.5 * atr, prec)
        if dry:
            print(f"[crash] (dry) would OPEN {sym} {UNITS}u @ ~{px_mid:.5f} SL {sl} TP {tp}")
            continue
        r = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp,
                           tag=TAG)
        if r.status != "filled":
            print(f"[crash] OPEN {sym} REJECTED")
            continue
        slip = r.price - px_mid  # positive = paid up (spread + slippage)
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "crash-entry", "paper": True, "tag": TAG,
                      "mid_before": px_mid, "slippage": round(slip, 6)})
        mine[sym] = {"units": UNITS, "opened": now.isoformat(), "entry": r.price}
        print(f"[crash] OPEN  {sym} {UNITS}u -> filled @ {r.price:.5f} "
              f"(spread+slippage {slip:+.6f}) SL {sl} TP {tp}")

    # 3. hypothetical $300 account equity
    unrealized = 0.0
    for sym, info in mine.items():
        net = _venue_net(ex, sym) or UNITS
        px = ex.get_current_price(sym)
        unrealized += (px - info["entry"]) * net if net > 0 else (info["entry"] - px) * abs(net)
    equity = HYPOTHETICAL_CASH + state["realized"] + unrealized
    state["peak_equity"] = max(state.get("peak_equity", HYPOTHETICAL_CASH), equity)
    state["max_dd"] = max(state.get("max_dd", 0.0),
                          state["peak_equity"] - equity)
    state["positions"] = {s: {"units": i["units"], "opened": i["opened"],
                              "entry": i["entry"]} for s, i in mine.items()}
    print(f"[crash] hypothetical ${HYPOTHETICAL_CASH:.0f} account: equity ${equity:,.2f} "
          f"(realized {state['realized']:+.2f}, unrealized {unrealized:+.2f}) | "
          f"peak ${state['peak_equity']:,.2f} max DD ${state['max_dd']:,.2f}")

    # 4. persist
    _append_ledger(fills)
    if not dry:
        STATE.write_text(json.dumps(state, indent=2, default=str))
        print(f"[crash] state written ({len(mine)} crash positions)")
    else:
        print("[crash] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
    except FileExistsError:
        raise SystemExit("[crash] another crashtest instance is running — exiting")
    try:
        run(dry=dry)
    finally:
        os.close(fd)
        os.unlink(LOCK)


if __name__ == "__main__":
    main()
