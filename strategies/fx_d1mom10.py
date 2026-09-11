#!/usr/bin/env python3
"""fx_d1mom10 — D1 momentum sibling lane, K=10 (map #174 #181).

A direct parameter-sensitivity A/B against the mom-k5 incumbent (K=5):
rank the majors by 10-day return, long the top-2 with positive momentum,
server SL/TP 1.5x/2.5x ATR-14, 14-day max hold, econ_blackout gate —
identical structure, one parameter moved. Known confound (per ticket #181):
the standing decision sizes new lanes at 2000u while mom-k5 trades 100u, so
size is a second factor; a 100u clean-A/B variant is a later ticket if the
human wants one.

Arbitration (map #174 #176): the entry pool excludes symbols held by any
other lane, with a pre-order re-check. Shares the ledger cursor: this lane
also calls _reconcile (idempotent via the sinceid cursor + tolerance dedup).

State:   data/fx_d1mom10.json (cache only — venue is authoritative)
Fills:   data/fx_ledger.jsonl (shared, tag d1-mom10)
Cron:    daily at 17:30 (FX weekdays, after mom-k5's 17:10)
Usage:   python3 -m strategies.fx_d1mom10 [--once]   (default: dry)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402
from data.economic_calendar import blackout as econ_blackout  # noqa: E402
from strategies.fx_runner import (_venue_book, _venue_net, _digits,  # noqa: E402
                                  _append_ledger, _parse_opened, atr14,
                                  _reconcile, _ensure_protection,
                                  held_by_other_tags, foreign_holds)

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_d1mom10.json"

TAG = "d1-mom10"
TOP_N = 2          # long the top-2 majors by momentum
K = 10             # momentum lookback (days) — the one moved parameter vs mom-k5
UNITS = 2000       # standing decision: new lanes at 2000u (confound vs mom-k5's 100u, documented)
ATR_STOP = 1.5
ATR_TP = 2.5
MAX_HOLD_DAYS = 14


def rank_momentum(bars_by_sym, k):
    """(sym, momentum) for symbols with enough bars, sorted descending.
    Isolated from run() so the K boundary is unit-testable; the incumbent
    fx_runner.run() keeps its inline version untouched."""
    mom = {}
    for sym, bars in bars_by_sym.items():
        if len(bars) < k + 2:
            continue
        mom[sym] = bars[-1].close / bars[-1 - k].close - 1.0
    return sorted(mom.items(), key=lambda kv: -kv[1])


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[d1-mom10] connect failed")
    today = datetime.now(timezone.utc)
    if not dry:
        _reconcile(ex)

    # 1. momentum rank (K=10)
    bars_by_sym = {}
    for sym in ex.discover_symbols():
        bars = ex.get_bars(sym, "1d", K + 12)
        if len(bars) >= K + 2:
            bars_by_sym[sym] = bars
    ranked = rank_momentum(bars_by_sym, K)
    print(f"[d1-mom10] momentum ({K}d):")
    for sym, m in ranked:
        print(f"  {sym.ljust(10)} {m:+.4%}")
    atrs = {sym: atr14(bars) for sym, bars in bars_by_sym.items()}

    target = {sym for sym, m in ranked[:TOP_N] if m > 0}
    print(f"[d1-mom10] target book: {sorted(target) or '(flat — no positive momentum)'}")

    # 2. venue-authoritative book + protection self-heal
    book = {s: i for s, i in _venue_book(ex).items() if i["owner"] == TAG}
    hint = {}
    if STATE.exists():
        try:
            for sym, pos in json.loads(STATE.read_text()).get("positions", {}).items():
                for e in (pos.get("entries") or [pos]) if isinstance(pos, dict) else []:
                    if isinstance(e, dict) and e.get("sl") and e.get("tp"):
                        hint[sym] = (e["sl"], e["tp"])
        except Exception:
            pass
    for sym, info in book.items():
        _ensure_protection(ex, sym, info, hint, atrs)
        print(f"[d1-mom10] {sym}: {info['units']}u @ {info['entry']:.5f} "
              f"protected={info['protected']} (opened {info['opened']})")
    fills = []

    # 3. close: out-of-target or max hold — only when venue net is exactly ours
    for sym in list(book):
        opened = _parse_opened(book[sym].get("opened"))
        age_days = (today - opened).days if opened else 0
        if sym in target and age_days < MAX_HOLD_DAYS:
            continue
        reason = "max-hold" if age_days >= MAX_HOLD_DAYS else "out-of-target"
        net = _venue_net(ex, sym)
        if not net:
            continue
        if abs(net - book[sym]["units"]) > 1e-9:
            print(f"[d1-mom10] !! {sym} venue net {net} != book {book[sym]['units']} — close deferred")
            continue
        if dry:
            print(f"[d1-mom10] (dry) would CLOSE {sym} ({reason}) {abs(net)}u")
            continue
        close_side = "SELL" if net > 0 else "BUY"
        r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
        if r.status != "filled":
            print(f"[d1-mom10] CLOSE {sym} REJECTED ({r.status}) — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                      "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                      "reason": reason})
        print(f"[d1-mom10] CLOSE {sym} ({reason}) -> filled @ {r.price}")
        book.pop(sym, None)

    # 4. open: event-gated, arbitration-aware
    others = held_by_other_tags(ex, TAG)
    for sym in sorted(target):
        if sym in book or sym in others:
            if sym in others:
                print(f"[d1-mom10] {sym} held by another lane — skipped (arbitration)")
            continue
        blocked, why = econ_blackout(today, sym)
        if blocked:
            print(f"[d1-mom10] {sym} entry BLOCKED — {why}")
            continue
        atr = atrs.get(sym, 0.0)
        px = ex.get_current_price(sym)
        if not px:
            print(f"[d1-mom10] {sym} no price — skipped")
            continue
        if foreign_holds(ex, sym, TAG):
            print(f"[d1-mom10] {sym} held by another lane at order time — skipped (arbitration)")
            continue
        d = _digits(sym)
        sl = round(px - ATR_STOP * atr, d) if atr else None
        tp = round(px + ATR_TP * atr, d) if atr else None
        if dry:
            print(f"[d1-mom10] (dry) would OPEN {sym} {UNITS}u SL {sl} TP {tp}")
            continue
        r = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp, tag=TAG)
        if r.status != "filled":
            print(f"[d1-mom10] OPEN {sym} REJECTED ({r.status}) — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "momentum-entry-k10", "sl": sl, "tp": tp})
        opened_info = _venue_book(ex).get(sym) or {}
        book[sym] = {"units": UNITS, "opened": today.isoformat(), "entry": r.price,
                     "sl": sl, "tp": tp,
                     "trade_id": opened_info.get("trade_id"),
                     "protected": opened_info.get("protected", False)}
        print(f"[d1-mom10] OPEN {sym} {UNITS}u -> filled @ {r.price:.5f} SL {sl} TP {tp}")

    # 5. persist (ledger always; state is a cache)
    _append_ledger(fills)
    if not dry:
        cache = {sym: {"units": info["units"], "opened": info["opened"],
                       "entry": info["entry"], "trade_id": info.get("trade_id"),
                       "protected": info.get("protected", False)}
                 for sym, info in book.items()}
        STATE.write_text(json.dumps({"positions": cache, "updated": today.isoformat(),
                                     "note": "cache only — venue is authoritative"}, indent=2))
        print(f"[d1-mom10] state cache written ({len(cache)} positions)")
    else:
        print("[d1-mom10] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    run(dry)


if __name__ == "__main__":
    main()
