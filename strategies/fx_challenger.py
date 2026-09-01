#!/usr/bin/env python3
"""fx_challenger — practice-book sleeve for the epoch-registry challenger
fx_mr_fade_ma20_cot (ADR-0009 §4 human signoff: 2026-09-01, "Do it").

The signal is loaded DIRECTLY from the signal gym's candidate file (single
source of truth — the same code fx_shadow paper-trades), evaluated on real
OANDA D1 candles with the gym-faithful before-bar MA/ATR conventions via
ShadowCtx. Entries are REAL practice-account orders: 100 units per position,
server-side SL/TP (1.5x/2.5x ATR-14), max 2 concurrent positions, 14-bar max
hold, one entry per day. Every order is stamped tag="c08-fade" — ownership
is the venue trade's client tag, so this sleeve, the momentum runner
(mom-k5) and the intraday lane (h1-mom) share one account and can never
close each other's positions.

Promotion semantics: this is the shadow->order-flow boundary. The registry
entry (fx_mr_fade_ma20_cot) accrues venue evidence from data/fx_ledger.jsonl
(reason-tagged c08-*); promotion to real money stays a separate human gate.

State:   data/fx_challenger_state.json (cache only — venue is authoritative)
Fills:   data/fx_ledger.jsonl (shared, reason-tagged)
Usage:   python3 -m strategies.fx_challenger [--once]   (default: dry)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402
from data.economic_calendar import blackout as econ_blackout  # noqa: E402
from strategies.fx_shadow import ShadowCtx, load_candidate  # noqa: E402
from strategies.fx_runner import (_venue_book, _venue_net, _digits,  # noqa: E402
                                  _append_ledger, LEDGER, _ensure_protection)

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_challenger_state.json"
LOCK = PROJECT / "data" / "fx_challenger.lock"

TAG = "c08-fade"
UNITS = 100
MAX_POS, TOP_N = 2, 2
ATR_STOP, ATR_TP, MAX_HOLD_DAYS = 1.5, 2.5, 14
CANDIDATE = "c08_mr_fade_cot"


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[c08] connect failed")
    cand = load_candidate(CANDIDATE)
    print(f"[c08] challenger sleeve ({cand.NAME}, practice) — tag {TAG}")

    book_all = _venue_book(ex)
    mine = {s: i for s, i in book_all.items() if i["owner"] == TAG}
    exog = {}
    exog_p = PROJECT / "data" / "exog_cache.json"
    if exog_p.exists():
        exog = json.load(open(exog_p))

    # series + point-in-time ctx (gym-faithful before-bar MA/ATR)
    series = {}
    for sym in ex.discover_symbols():
        bars = ex.get_bars(sym, "1d", 60)
        if len(bars) < 22:
            continue
        series[sym] = {b.timestamp: (b.open, b.high, b.low, b.close) for b in bars}
    alldates = sorted({ts for s in series.values() for ts in s})

    def _ctx(sym):
        d = max(series[sym])
        return ShadowCtx(series, alldates, alldates.index(d), [sym], exog_series=exog)

    atrs = {sym: _ctx(sym).atr(sym, 14) for sym in series}
    fills = []
    today = datetime.now(timezone.utc)

    # 1. protection self-heal on open sleeve positions
    for sym, info in mine.items():
        _ensure_protection(ex, sym, {**info, "trade_id": info["trade_id"]}, {}, atrs)

    # 2. exits: 14-bar max hold (SL/TP exits happen server-side and are
    #    reconciled into the ledger by the daily runner)
    for sym in list(mine):
        opened = datetime.fromisoformat(mine[sym]["opened"])
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        age_days = (today - opened).days
        if age_days < MAX_HOLD_DAYS:
            print(f"[c08] holding {sym} ({age_days}d)")
            continue
        net = _venue_net(ex, sym)
        if abs(net - mine[sym]["units"]) > 1e-9:
            print(f"[c08] !! {sym} venue net {net} != ours {mine[sym]['units']} — deferred")
            continue
        if not net:
            print(f"[c08] {sym} venue-closed (SL/TP) — reconciled by daily run")
            mine.pop(sym, None)
            continue
        close_side = "SELL" if net > 0 else "BUY"
        if dry:
            print(f"[c08] (dry) would CLOSE {sym} (max-hold) {abs(net)}u")
            continue
        r = ex.place_order(sym, close_side, abs(net), "market", tag=TAG)
        if r.status != "filled":
            print(f"[c08] CLOSE {sym} REJECTED — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                      "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                      "reason": "c08-maxhold"})
        print(f"[c08] CLOSE {sym} (max-hold) -> filled @ {r.price}")
        mine.pop(sym, None)

    # 3. entries: candidate signal, top-2 stable order, cap 2 concurrent
    alld = alldates
    by_date = {}
    for sym in series:
        ts = max(series[sym])
        by_date.setdefault(ts, []).append(sym)
    proposals = []
    for d, syms in sorted(by_date.items()):
        i = alld.index(d)
        ctx = ShadowCtx(series, alld, i, syms, exog_series=exog)
        try:
            picks = cand.entry(ctx)
            assert isinstance(picks, dict)
        except Exception as e:
            print(f"[c08] ! candidate entry failed on {d}: {e}")
            continue
        ordered = [s for s, _w in sorted(picks.items(), key=lambda kv: -kv[1])]
        proposals = [s for s in ordered if s not in mine][:TOP_N]
    slots = MAX_POS - len(mine)
    targets = proposals[:max(0, slots)]
    if not targets:
        print(f"[c08] no entries today ({len(proposals)} signal(s), {len(mine)} held)")

    # 4. opens (event-gated: no entries into central-bank decision windows)
    for sym in targets:
        blocked, why = econ_blackout(today, sym)
        if blocked:
            print(f"[c08] {sym} entry BLOCKED — {why}")
            continue
        px = ex.get_current_price(sym)
        ctx_atr = _ctx(sym).atr(sym, 14)
        if not px or not ctx_atr or ctx_atr <= 0:
            print(f"[c08] !! {sym} no ATR — skipped")
            continue
        prec = _digits(sym)
        sl = round(px - ATR_STOP * ctx_atr, prec)
        tp = round(px + ATR_TP * ctx_atr, prec)
        if dry:
            print(f"[c08] (dry) would OPEN {sym} {UNITS}u SL {sl} TP {tp}")
            continue
        r = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp,
                           tag=TAG)
        if r.status != "filled":
            print(f"[c08] OPEN {sym} REJECTED ({r.status})")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "c08-entry", "sl": sl, "tp": tp})
        print(f"[c08] OPEN  {sym} {UNITS}u -> filled @ {r.price:.5f} SL {sl} TP {tp}")

    # 5. persist
    _append_ledger(fills)
    if not dry:
        mine_now = {s: i for s, i in _venue_book(ex).items() if i["owner"] == TAG}
        STATE.write_text(json.dumps(
            {"positions": {s: {"trade_id": i["trade_id"], "units": i["units"],
                               "opened": i["opened"], "protected": i["protected"]}
                           for s, i in mine_now.items()},
             "updated": today.isoformat(),
             "note": "cache only — venue is authoritative"}, indent=2))
        print(f"[c08] sleeve book (venue): {len(mine_now)}/{MAX_POS} positions, "
              f"protection { {s: i['protected'] for s, i in mine_now.items()} }")
    else:
        print("[c08] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
    except FileExistsError:
        raise SystemExit("[c08] another challenger instance is running — exiting")
    try:
        run(dry=dry)
    finally:
        os.close(fd)
        os.unlink(LOCK)


if __name__ == "__main__":
    main()
