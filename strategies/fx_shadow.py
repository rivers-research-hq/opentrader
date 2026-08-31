#!/usr/bin/env python3
"""fx_shadow — shadow paper lane for the epoch-registry challenger fx_mr_fade_ma20.

Faithful port of data/signal_gym/candidates/c04_mr_fade_ma20.py under the
gym's uniform risk shape (scripts/signal_gym.py): long a major when its close
is >1.5% below its 20-day MA (MA over the 20 bars BEFORE the signal bar,
gym convention); top-2 by stable insertion order; $10k notional per position;
stop/target = 1.5x/2.5x ATR-14 (ATR over the 15 bars before the signal bar);
14-bar max hold; stop checked before target on each bar.

PURE PAPER: this module places NO orders. Prices are real completed OANDA D1
candles (get_bars filters pending candles); fills are simulated at the signal
bar's close into data/fx_shadow_ledger.jsonl with paper=true. This is the
ADR-0009 shadow registry — order flow is only granted at the shadow->live
boundary with human signoff. It must not run in the same venue book as the
daily runner (fx_runner closes anything not in ITS target).

One deviation from the gym, conservative: spread cost 0.0001 x units is
subtracted on every exit (the gym's target branch added it back — sign bug
there; not replicated). Shadow PnL is therefore slightly pessimistic vs the
gym baseline.

Per-symbol asof guard: each symbol's newest completed bar is processed at
most once (state.last_bar), so reruns on the same day are idempotent.

State:   data/fx_shadow_state.json   (sole writer: fx_shadow)
Fills:   data/fx_shadow_ledger.jsonl (append-only, deduped, paper=true)
Usage:   python3 -m strategies.fx_shadow [--apply]   (default: dry)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_shadow_state.json"
LEDGER = PROJECT / "data" / "fx_shadow_ledger.jsonl"

FADE = -0.015       # long when close sits >1.5% below MA20 (c04_mr_fade_ma20)
TOP_N = 2           # gym: stable top-2 by weight
NOTIONAL = 10_000   # gym uniform risk: $10k per position
ATR_STOP, ATR_TP, HOLD = 1.5, 2.5, 14
SPREAD = 0.0001


def _fill_key(f):
    return (str(f.get("ts")), f.get("symbol"), f.get("side"), f.get("reason"))


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


def _ma20(closes, i):
    """Gym convention: mean of the 20 closes BEFORE bar i."""
    if i < 20:
        return None
    return sum(closes[i - 20:i]) / 20.0


def _atr14(bars, i):
    """Gym convention: 14 TRs from the 15 bars BEFORE bar i."""
    if i < 15:
        return None
    trs = []
    for j in range(i - 14, i + 1):
        h, l, pc = bars[j].high, bars[j].low, bars[j - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def run(apply=False):
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[fx-sh] connect failed — check config/oanda_keys.json")
    symbols = ex.discover_symbols()
    print(f"[fx-sh] shadow lane (mr_fade_ma20, paper) — symbols: {symbols}")

    state = json.loads(STATE.read_text()) if STATE.exists() else {"positions": {}, "last_bar": {}}
    book, last_bar = state.setdefault("positions", {}), state.setdefault("last_bar", {})
    fills = []

    # newest completed bar per symbol + series context
    ctx = {}
    for sym in symbols:
        bars = ex.get_bars(sym, "1d", 60)
        if len(bars) < 22:
            continue
        i = len(bars) - 1
        if last_bar.get(sym) == bars[i].timestamp:
            continue  # asof guard: already processed this bar
        ctx[sym] = (bars, i)

    # 1. exits on open shadow positions (gym order: stop, then target, then hold)
    for sym in list(book):
        if sym not in ctx:
            continue
        bars, i = ctx[sym]
        pos = book[sym]
        pos["bars_seen"] = pos.get("bars_seen", 0) + 1
        px = bars[i]
        exit_px, reason = None, None
        if px.low <= pos["sl"]:
            exit_px, reason = pos["sl"], "mr-fade-exit-stop"
        elif px.high >= pos["tp"]:
            exit_px, reason = pos["tp"], "mr-fade-exit-target"
        elif pos["bars_seen"] >= HOLD:
            exit_px, reason = px.close, "mr-fade-exit-hold"
        if exit_px is not None:
            pnl = (exit_px - pos["entry"]) * pos["units"] - SPREAD * pos["units"]
            fills.append({"ts": px.timestamp, "symbol": sym, "side": "SELL",
                          "quantity": pos["units"], "price": round(exit_px, 5),
                          "order_id": None, "paper": True, "reason": reason,
                          "pnl": round(pnl, 2)})
            print(f"[fx-sh] EXIT  {sym} ({reason}) @ {exit_px:.5f} pnl {pnl:+.2f}")
            del book[sym]

    # 2. entries: fade signal, stable top-2 (gym semantics, weight 1.0)
    picks = []
    for sym in symbols:  # discover order = gym ctx.symbols order
        if sym not in ctx or sym in book:
            continue
        bars, i = ctx[sym]
        closes = [b.close for b in bars]
        ma = _ma20(closes, i)
        c = closes[i]
        if ma and c and (c - ma) / ma < FADE:
            picks.append(sym)
    for sym in picks[:TOP_N]:
        bars, i = ctx[sym]
        px = bars[i]
        atr = _atr14(bars, i)
        if not atr or atr <= 0 or px.close <= 0:
            continue
        units = int(NOTIONAL / px.close)
        book[sym] = {"units": units, "entry": px.close, "sl": px.close - ATR_STOP * atr,
                     "tp": px.close + ATR_TP * atr, "entry_ts": px.timestamp, "bars_seen": 0}
        fills.append({"ts": px.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": units, "price": round(px.close, 5), "order_id": None,
                      "paper": True, "reason": "mr-fade-entry", "sl": book[sym]["sl"],
                      "tp": book[sym]["tp"]})
        print(f"[fx-sh] ENTRY {sym} {units}u @ {px.close:.5f} "
              f"(fade {(px.close / _ma20([b.close for b in bars], i) - 1):+.2%}) "
              f"SL {book[sym]['sl']:.5f} TP {book[sym]['tp']:.5f}")

    for sym, (bars, i) in ctx.items():
        last_bar[sym] = bars[i].timestamp

    # 3. persist (paper ledger is always appended — it is the evidence trail;
    #    only the state file is gated on --apply)
    _append_ledger(fills)
    if apply:
        newest_ts = max((bars[i].timestamp for bars, i in ctx.values()),
                        default=state.get("updated"))
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"positions": book, "last_bar": last_bar,
                                   "updated": newest_ts}, indent=2))
        os.replace(tmp, STATE)
        print(f"[fx-sh] state written ({len(book)} shadow positions)")
    else:
        print("[fx-sh] dry run — no state write")

    # 4. running stats (heuristic paper accounting, labeled)
    pnls = []
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    p = json.loads(line).get("pnl")
                    if p is not None:
                        pnls.append(float(p))
                except Exception:
                    pass
    if pnls:
        wins = [p for p in pnls if p > 0]
        gl = abs(sum(p for p in pnls if p <= 0))
        pf = (sum(wins) / gl) if gl else float("inf")
        print(f"[fx-sh] shadow book so far (paper, spread-adj): n={len(pnls)} "
              f"WR {len(wins) / len(pnls):.1%} PF {pf:.2f} cum {sum(pnls):+,.2f}")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
