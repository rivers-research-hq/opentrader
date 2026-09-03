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
from data.economic_calendar import blackout as econ_blackout  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_state.json"
LEDGER = PROJECT / "data" / "fx_ledger.jsonl"
CURSOR = PROJECT / "data" / "fx_reconcile_cursor.json"

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


def _parse_opened(raw):
    """Defensive parse of a book 'opened' stamp. A venue trade missing
    openTime (or a foreign-writer clobber of the state cache) produced an
    empty/garbage string and killed the whole run 2026-09-01 17:10
    (KeyError/ValueError at the fromisoformat call — ticket #162). Returns
    None when unparseable; callers treat None as 'age unknown' and degrade
    to out-of-target logic instead of crashing."""
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00")[:19])
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _venue_book(ex):
    """Rebuild the book from venue openTrades — venue is authoritative.
    fx_state.json is a write-through cache, NEVER a source of truth: a
    foreign writer clobbered it 2026-08-31 and crashed the next run.
    Protection state reads the NESTED stopLossOrder/takeProfitOrder objects
    (the top-level *OrderID fields are not present on this API surface)."""
    ot = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    book = {}
    for t in ot:
        sym = t.get("instrument")
        if sym not in ex.discover_symbols():
            continue
        book[sym] = {
            "units": abs(float(t.get("currentUnits", 0))),
            "opened": str(t.get("openTime", ""))[:19],
            "entry": float(t.get("price", 0)),
            "trade_id": t.get("id"),
            "owner": (t.get("clientExtensions") or {}).get("tag") or "unknown",
            "protected": bool(t.get("stopLossOrder") or t.get("takeProfitOrder")),
        }
    return book


def _venue_net(ex, sym):
    # .get with fallback: an error-shaped venue payload (no "account" key)
    # crashed the watchdog 2026-09-02 (documented as fx_defect). Net 0 from a
    # bad payload is safe here — callers defer closes on net==0/ambiguity.
    acc = ex._request("GET", f"/v3/accounts/{ex._account_id}").get("account") or {}
    for p in acc.get("positions", []):
        if p.get("instrument") == sym:
            lu = float(p.get("long", {}).get("units", 0))
            su = float(p.get("short", {}).get("units", 0))
            return lu + su
    return 0.0


def _digits(sym):
    """JPY pairs quote at 3 decimals; everything else at 5 (OANDA rejects
    over-precise attached orders — TAKE_PROFIT_ON_FILL_PRICE_PRECISION_EXCEEDED)."""
    return 3 if "JPY" in sym else 5


def _ensure_protection(ex, sym, info, hint, atrs):
    """Self-heal: if a book position lost its SL/TP (the 2026-09-01 FIFO
    incident stripped both), re-attach from the state hint or fresh ATR."""
    if info.get("protected"):
        return
    sl, tp = hint.get(sym, (None, None))
    if not sl or not tp:
        px = ex.get_current_price(sym)
        atr = atrs.get(sym, 0.0)
        if not px or not atr:
            print(f"[fx] !! {sym} UNPROTECTED and no levels available — manual attention")
            return
        d = _digits(sym)
        sl, tp = round(px - ATR_STOP * atr, d), round(px + ATR_TP * atr, d)
    r = ex._request("PUT", f"/v3/accounts/{ex._account_id}/trades/{info['trade_id']}/orders",
                    body={"stopLoss": {"price": f"{sl:.{_digits(sym)}f}", "timeInForce": "GTC"},
                          "takeProfit": {"price": f"{tp:.{_digits(sym)}f}", "timeInForce": "GTC"}})
    ok = "stopLossOrderTransaction" in r or "stopLossOrderRejectTransaction" not in r
    print(f"[fx] protection {'restored' if ok else 'FAILED'} on {sym} "
          f"(trade {info['trade_id']}) SL {sl:.5f} TP {tp:.5f}")


def _txns_since(ex, iso_from):
    """Venue transactions since iso_from (handles the paged response)."""
    from urllib.parse import quote
    r = ex._request("GET", f"/v3/accounts/{ex._account_id}/transactions"
                            f"?from={quote(iso_from)}&pageSize=1000")
    out = []
    for page in r.get("pages", []):
        path = "/v3/" + page.split("/v3/", 1)[-1]
        out += ex._request("GET", path).get("transactions", [])
    return out


def _txns_since_id(ex, since_id):
    """Venue transactions with id > since_id (monotonic journal cursor)."""
    r = ex._request(
        "GET", f"/v3/accounts/{ex._account_id}/transactions/sinceid?id={int(since_id)}"
    )
    return r.get("transactions", [])


def _reconcile(ex, dry=False):
    """Server-side SL/TP fills never produce ledger rows — replay them from
    the venue transaction journal. Cursor is the venue's own monotonic
    transaction id (data/fx_reconcile_cursor.json), NOT a timestamp in
    fx_state.json: run()'s state-cache write used to clobber last_reconciled
    every day, forcing a full-journal rescan. A missing/corrupt cursor falls
    back to id 0 (full rescan) — the tolerance-based dedup below makes that
    idempotent, so cursor loss is self-healing. Dedup is tolerance-based
    (same symbol, side, quantity, price within 5s) because the runner's own
    rows carry Python isoformat timestamps while the venue journal uses
    OANDA format — exact-string dedup double-counted every strategy fill
    (fixed 2026-09-01)."""
    from datetime import datetime as _dt
    since_id = 0
    if CURSOR.exists():
        try:
            since_id = int(json.loads(CURSOR.read_text()).get("last_id", 0))
        except Exception:
            since_id = 0
    existing = []
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    ts = _dt.fromisoformat(str(r.get("timestamp")).replace("Z", "+00:00"))
                    existing.append((r.get("symbol"), (r.get("side") or "").upper(),
                                     float(r.get("quantity", 0)), float(r.get("price", 0)), ts))
                except Exception:
                    pass

    def known(sym, side, qty, price, ts):
        return any(e[0] == sym and e[1] == side and abs(e[2] - qty) < 1e-9
                   and abs(e[3] - price) < 1e-9 and abs((e[4] - ts).total_seconds()) <= 5
                   for e in existing)

    fills = []
    syms = set(ex.discover_symbols())
    last_id = since_id
    for t in _txns_since_id(ex, since_id):
        tid = int(t.get("id", 0) or 0)
        last_id = max(last_id, tid)
        if t.get("type") != "ORDER_FILL" or t.get("instrument") not in syms:
            continue
        units = float(t.get("units", 0))
        side = "BUY" if units > 0 else "SELL"
        qty, price = abs(units), float(t.get("price", 0))
        ts = _dt.fromisoformat(str(t.get("time")).replace("Z", "+00:00"))
        if known(t["instrument"], side, qty, price, ts):
            continue  # the runner's own row — same fill, different timestamp format
        fills.append({"timestamp": t.get("time"), "symbol": t["instrument"],
                      "side": side, "quantity": qty,
                      "price": price, "order_id": t.get("transactionID"),
                      "reason": "venue-reconciliation"})
        existing.append((t["instrument"], side, qty, price, ts))
    _append_ledger(fills)
    if fills:
        print(f"[fx] reconciled {len(fills)} venue fill(s) into the ledger")
    if not dry:
        CURSOR.write_text(json.dumps({"last_id": last_id,
                                      "updated": datetime.now(timezone.utc).strftime(
                                          "%Y-%m-%dT%H:%M:%SZ")}))


def run(dry=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[fx] connect failed — check config/oanda_keys.json")
    bal = ex.get_balance()
    print(f"[fx] connected: balance ${bal.cash:,.2f} | instruments {ex.discover_symbols()}")

    if not dry:
        _reconcile(ex)

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

    # 2. venue-authoritative book + protection self-heal (this lane owns only
    # its tag — the c08 challenger sleeve and the intraday lane share the book)
    book = {s: i for s, i in _venue_book(ex).items() if i["owner"] == "mom-k5"}
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
        if info["protected"]:
            print(f"[fx] {sym}: {info['units']}u @ {info['entry']:.5f} protected "
                  f"(opened {info['opened']})")
        else:
            print(f"[fx] {sym}: {info['units']}u @ {info['entry']:.5f} "
                  f"(opened {info['opened']})")
    fills = []

    # 3. close: positions no longer in target or beyond max hold — only when
    # the venue net is EXACTLY ours (never touch netting-ambiguous positions)
    today = datetime.now(timezone.utc)
    for sym in list(book):
        opened = _parse_opened(book[sym].get("opened"))
        if opened is None:
            print(f"[fx] !! {sym} unparseable opened stamp "
                  f"{book[sym].get('opened')!r} — age logic skipped this run")
            age_days = 0
        else:
            age_days = (today - opened).days
        if sym in target and age_days < MAX_HOLD_DAYS:
            continue
        reason = "max-hold" if age_days >= MAX_HOLD_DAYS else "out-of-target"
        net = _venue_net(ex, sym)
        if abs(net - book[sym]["units"]) > 1e-9:
            print(f"[fx] !! {sym} venue net {net} != book {book[sym]['units']} "
                  f"— not ours alone, close deferred")
            continue
        if not net:
            continue
        close_side = "SELL" if net > 0 else "BUY"
        if dry:
            print(f"[fx] (dry) would CLOSE {sym} ({reason}) {abs(net)} units")
            continue
        r = ex.place_order(sym, close_side, abs(net), "market")
        if r.status != "filled":
            print(f"[fx] CLOSE {sym} REJECTED ({r.status}) — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                      "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                      "reason": reason})
        print(f"[fx] CLOSE {sym} ({reason}) -> {r.status} @ {r.price}")
        book.pop(sym, None)

    # 4. open: target instruments not in book (event-gate: no entries into
    #    central-bank decision windows — the book is blind intra-day, so
    #    scheduled shocks are avoided, not survived)
    for sym in sorted(target):
        if sym in book:
            continue
        blocked, why = econ_blackout(today, sym)
        if blocked:
            print(f"[fx] {sym} entry BLOCKED — {why}")
            continue
        atr = atrs.get(sym, 0.0)
        px = ex.get_current_price(sym)
        d = _digits(sym)
        sl = round(px - ATR_STOP * atr, d) if atr else None
        tp = round(px + ATR_TP * atr, d) if atr else None
        if dry:
            print(f"[fx] (dry) would OPEN  {sym} 100 units SL {sl and round(sl, 5)} TP {tp and round(tp, 5)}")
            continue
        r = ex.place_order(sym, "BUY", UNITS, "market", stop_loss=sl, take_profit=tp,
                           tag="mom-k5")
        if r.status != "filled":
            print(f"[fx] OPEN  {sym} REJECTED ({r.status}) — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": UNITS, "price": r.price, "order_id": r.order_id,
                      "reason": "momentum-entry", "sl": sl, "tp": tp})
        opened_info = _venue_book(ex).get(sym) or {}
        book[sym] = {"units": UNITS, "opened": today.isoformat(), "entry": r.price,
                     "sl": sl, "tp": tp,
                     "trade_id": opened_info.get("trade_id"),
                     "protected": opened_info.get("protected", False)}
        print(f"[fx] OPEN  {sym} 100 units -> {r.status} @ {r.price:.5f} "
              f"SL {sl and round(sl, 5)} TP {tp and round(tp, 5)}")

    # 5. persist (ledger always; state is a cache)
    _append_ledger(fills)
    if not dry:
        cache = {sym: {"units": info["units"], "opened": info["opened"],
                       "entry": info["entry"], "trade_id": info.get("trade_id"),
                       "protected": info.get("protected", False)}
                 for sym, info in book.items()}
        STATE.write_text(json.dumps({"positions": cache, "updated": today.isoformat(),
                                     "note": "cache only — venue is authoritative"}, indent=2))
        print(f"[fx] state cache written: {STATE} ({len(cache)} positions)")
    else:
        print("[fx] dry run — no state write")
    ot2 = _venue_book(ex)
    print(f"[fx] book after (venue): {len(ot2)} positions | "
          f"protection: { {s: i['protected'] for s, i in ot2.items()} }")
    return book


def run_intraday(dry=False):
    """Hourly lab loop: H1 momentum on majors NOT held by the daily book.
    2,000-unit clips, tight server-side SL/TP (1x / 1.5x ATR-H1), 12h max
    hold. Demo-only evidence velocity: fills, execution stats, netting
    behavior — this lane does not go live (intraday is ADR-0004 research)."""
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[fx-id] connect failed")
    # venue-authoritative: this lane owns only positions tagged h1-mom
    if not dry:
        _reconcile(ex)  # hourly catch-up: the ≤1h ledger-lag bound (map #158)
    book_all = _venue_book(ex)
    held = set(book_all)
    pool = [s for s in ex.discover_symbols() if s not in held]
    print(f"[fx-id] pool (not held by daily book): {pool}")

    istate_p = PROJECT / "data" / "fx_intraday.json"
    fills = []
    now = datetime.now(timezone.utc)
    book = {sym: info for sym, info in book_all.items() if info["owner"] == "h1-mom"}

    # close: stale holds (12h) or any with SL/TP already consumed (venue closed)
    for sym in list(book):
        opened = _parse_opened(book[sym].get("opened"))
        if opened is None:
            print(f"[fx-id] !! {sym} unparseable opened stamp "
                  f"{book[sym].get('opened')!r} — hold-age logic skipped this run")
            age_h = 0.0
        else:
            age_h = (now - opened).total_seconds() / 3600
        net = _venue_net(ex, sym)
        if age_h >= 12 or not net or abs(net - 2000) > 1e-9:
            if abs(net - 2000) > 1e-9 and net:
                print(f"[fx-id] !! {sym} venue net {net} != ours 2000 — close deferred")
                continue
            if not net:
                book.pop(sym, None)
                print(f"[fx-id] {sym} venue-closed (SL/TP) — ledger reconciled by daily run")
                continue
            close_side = "SELL" if net > 0 else "BUY"
            reason = "max-hold-12h"
            if dry:
                print(f"[fx-id] (dry) would CLOSE {sym} ({reason})")
                continue
            r = ex.place_order(sym, close_side, abs(net), "market")
            if r.status != "filled":
                print(f"[fx-id] CLOSE {sym} REJECTED ({r.status}) — retried next run")
                continue
            fills.append({"timestamp": r.timestamp, "symbol": sym, "side": close_side,
                          "quantity": abs(net), "price": r.price, "order_id": r.order_id,
                          "reason": f"intraday-{reason}"})
            print(f"[fx-id] CLOSE {sym} ({reason}) -> {r.status} @ {r.price}")
            book.pop(sym, None)
        else:
            print(f"[fx-id] holding {sym} ({age_h:.1f}h, net {net})")

    # open: H1 momentum on pool, positive only, top-2
    mom = {}
    atrs = {}
    for sym in pool[:]:
        bars = ex.get_bars(sym, "1h", 20)
        if len(bars) < 10:
            continue
        mom[sym] = bars[-1].close / bars[-9].close - 1.0
        trs = [max(bars[i].high - bars[i].low, abs(bars[i].high - bars[i-1].close),
                   abs(bars[i].low - bars[i-1].close)) for i in range(1, len(bars))]
        atrs[sym] = sum(trs) / len(trs)
    ranked = sorted(mom.items(), key=lambda kv: -kv[1])[:2]
    for sym, m in ranked:
        if m <= 0 or sym in book:
            continue
        atr = atrs[sym]
        px = ex.get_current_price(sym)
        sl, tp = px - atr, px + 1.5 * atr
        if dry:
            print(f"[fx-id] (dry) would OPEN {sym} 2000 units SL {sl:.5f} TP {tp:.5f}")
            continue
        r = ex.place_order(sym, "BUY", 2000, "market", stop_loss=sl, take_profit=tp,
                           tag="h1-mom")
        if r.status != "filled":
            print(f"[fx-id] OPEN {sym} REJECTED ({r.status}) — retried next run")
            continue
        fills.append({"timestamp": r.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": 2000, "price": r.price, "order_id": r.order_id,
                      "reason": "intraday-momentum", "sl": sl, "tp": tp})
        book[sym] = {"units": 2000, "opened": now.isoformat(), "entry": r.price, "sl": sl, "tp": tp}
        print(f"[fx-id] OPEN {sym} 2000 units -> {r.status} @ {r.price:.5f} SL {sl:.5f} TP {tp:.5f}")

    _append_ledger(fills)
    if not dry:
        istate_p.write_text(json.dumps({"positions": book, "updated": now.isoformat()}, indent=2))
        print(f"[fx-id] state written ({len(book)} intraday positions)")
    else:
        print("[fx-id] dry run — no state write")


def main():
    dry = "--once" not in sys.argv
    if "--intraday" in sys.argv:
        run_intraday(dry=dry)
    else:
        # one instance at a time — a double-run triggered the 2026-09-01 FIFO
        # incident that stripped the book's protective orders
        lock = PROJECT / "data" / "fx_runner.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
        except FileExistsError:
            raise SystemExit("[fx] another fx_runner instance is running — exiting")
        try:
            run(dry=dry)
        finally:
            os.close(fd)
            os.unlink(lock)


if __name__ == "__main__":
    main()
