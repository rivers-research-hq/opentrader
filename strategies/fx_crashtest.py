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

Accounting (fixed 2026-09-02, ticket #163): `realized` is RECOMPUTED each
run from the venue transaction journal over the FULL lane history
(ORDER_FILL rows closing a 5,000-unit position; their `pl` field is the
venue-authoritative USD PnL) — SL/TP closes previously booked zero because
only our own 12h-hold closes were counted. `unrealized` comes from the
venue's own unrealizedPL on openTrades, not local price snapshots — a
one-cycle stale mark printed equity −$212 on a $300 account (max DD $572)
on 2026-09-02 while actual venue damage was pennies. Both drift sources
self-heal by construction: state values are derived, the venue is
authoritative.

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
                                  _append_ledger, _parse_opened, _txns_since,
                                  atr14, PROJECT)

STATE = PROJECT / "data" / "fx_crashtest.json"
LOCK = PROJECT / "data" / "fx_crashtest.lock"

TAG = "crash"
UNITS = 5_000                 # ~$5k notional = the $300-account-at-max-margin model
MAX_POS, TOP_N = 2, 2
MAX_HOLD_H = 12
HYPOTHETICAL_CASH = 300.0     # the notional account this book crash-tests
LANE_EPOCH = "2026-09-01T00:00:00Z"  # venue journal scan start (lane began 09-01)


def _load_state():
    if STATE.exists():
        state = json.loads(STATE.read_text())
        if "last_venue_sync" not in state:
            # First run under venue-derived accounting: the old peak/max_dd
            # series carried phantom marks (one-cycle equity −$212 → DD $572
            # on 2026-09-02), and maxima persist forever once recorded.
            # Restart the series clean; realized self-heals from the venue.
            state["peak_equity"] = HYPOTHETICAL_CASH
            state["max_dd"] = 0.0
        return state
    return {"realized": 0.0, "peak_equity": HYPOTHETICAL_CASH,
            "max_dd": 0.0, "positions": {}, "last_venue_sync": None}


def _venue_crash_pnl(ex, since_iso):
    """Venue-authoritative crash-lane realized PnL: sum the `pl` of every
    ORDER_FILL closing a 5,000-unit position since `since_iso`. Crash
    entries are always BUY UNITS=5000, so exits are fills with units < 0 and
    abs(units) == UNITS. (Other lanes on this account trade 100-unit sizes;
    if another lane ever trades 5000, this matcher must grow a tag filter.)"""
    total, closes = 0.0, []
    for t in _txns_since(ex, since_iso):
        if t.get("type") != "ORDER_FILL":
            continue
        units = float(t.get("units", 0))
        if 0 < abs(units) != UNITS or units >= 0:
            continue
        total += float(t.get("pl", 0) or 0)
        closes.append({"time": t.get("time"), "instrument": t.get("instrument"),
                       "price": float(t.get("price", 0)), "pl": float(t.get("pl", 0))})
    return total, closes


def _venue_unrealized(ex, my_syms):
    """Per-symbol unrealized from the venue's own mark (openTrades
    unrealizedPL, account currency). Returns ({sym: upl}, missing_syms)."""
    upl = {}
    missing = []
    ot = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    for t in ot:
        sym = t.get("instrument")
        if sym in my_syms:
            upl[sym] = float(t.get("unrealizedPL", 0))
    for sym in my_syms:
        if sym not in upl:
            missing.append(sym)
    return upl, missing


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

    # 0. realized: recompute from the venue journal over the FULL lane
    #    history (covers SL/TP closes that never produced a ledger row, and
    #    self-heals any prior drift). NOT bounded by last_venue_sync — a
    #    since-cursor window would replace the cumulative total with just
    #    the last hour's closes (that bug reset realized to 0.00 at 16:30).
    realized_venue, closes = _venue_crash_pnl(ex, LANE_EPOCH)
    state["realized"] = round(realized_venue, 2)
    since = state.get("last_venue_sync")
    recent = [c for c in closes if not since or str(c["time"])[:19] > since[:19]]
    if recent:
        print(f"[crash] venue-closed since last sync: "
              + ", ".join(f"{c['instrument']} {c['pl']:+.2f}" for c in recent))
    print(f"[crash] realized synced from venue (since {LANE_EPOCH[:10]}): "
          f"{state['realized']:+.2f}")

    # 1. exits: 12h hold or venue-closed (SL/TP) — the venue booking above
    #    owns the PnL; this loop only handles our own 12h market closes
    for sym in list(mine):
        info = mine[sym]
        opened = _parse_opened(info.get("opened"))
        if opened is None:
            print(f"[crash] !! {sym} unparseable opened stamp "
                  f"{info.get('opened')!r} — hold-age logic skipped this run")
            continue
        net = _venue_net(ex, sym)
        if abs(abs(net) - UNITS) > 1e-9 and net:
            print(f"[crash] !! {sym} venue net {net} != ours {UNITS} — deferred")
            continue
        if not net:
            state["positions"].pop(sym, None)
            print(f"[crash] {sym} venue-closed (SL/TP) — realized booked from venue journal")
            continue
        age_h = (now - opened).total_seconds() / 3600
        if age_h >= MAX_HOLD_H:
            close_side = "SELL" if net > 0 else "BUY"
            if dry:
                print(f"[crash] (dry) would CLOSE {sym} (12h hold)")
                continue
            r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
            if r.status != "filled":
                print(f"[crash] CLOSE {sym} REJECTED — retry next cycle")
                continue
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                          "reason": "crash-12h-hold", "paper": True, "tag": TAG})
            print(f"[crash] CLOSE {sym} (12h) -> filled @ {r.price} "
                  f"(PnL lands via venue sync)")
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
            print(f"[crash] OPEN {sym} REJECTED ({r.raw.get('reason') if r.raw else ''})")
            continue
        slip = r.price - px_mid  # positive = paid up (spread + slippage)
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "crash-entry", "paper": True, "tag": TAG,
                      "mid_before": px_mid, "slippage": round(slip, 6)})
        mine[sym] = {"units": UNITS, "opened": now.isoformat(), "entry": r.price}
        print(f"[crash] OPEN  {sym} {UNITS}u -> filled @ {r.price:.5f} "
              f"(spread+slippage {slip:+.6f}) SL {sl} TP {tp}")

    # 3. hypothetical $300 account equity — marks from the venue's own
    #    unrealizedPL (a stale local snapshot printed a phantom −$512 DD on
    #    2026-09-02; the venue mark is authoritative)
    held_syms = set(mine)
    upl_map, missing = _venue_unrealized(ex, held_syms)
    unrealized = sum(upl_map.values())
    for sym in missing:
        info = mine.get(sym, {})
        net = _venue_net(ex, sym) or UNITS
        px = ex.get_current_price(sym)
        if px and info.get("entry"):
            u = (px - info["entry"]) * net if net > 0 else (info["entry"] - px) * abs(net)
            unrealized += u
            print(f"[crash] !! {sym} no venue uPL — fell back to local mark {u:+.2f}")
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
        state["last_venue_sync"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
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
