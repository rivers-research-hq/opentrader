#!/usr/bin/env python3
"""fx_trail_check — simulated trailing stop / TP for trained FX lanes.

The books hold to rebalance because the A/B said uniform ATR stops hurt the
*portfolio* PF. But that tested uniform stops applied to every leg; this
module implements the per-leg selective version: at each daily check, every
open trade is evaluated against its own peak/trough and ATR. Triggered legs
close via per-tradeID (surgical — no netting ambiguity). Freed margin is
redeployed at the next rebalance.

Trigger conditions (per trade, computed from venue truth):
  TRAIL: price retraces k_trail × ATR from the trade's peak (long) or
         trough (short)
  TP:    price hits entry + k_tp × ATR (long) or entry − k_tp × ATR (short)

ATR comes from the accrual store (atr_pct = high-low rolling 14 / close).
The MFE tracker (Warden) already tracks lane-level peak uPL; this operates
per-trade for per-leg precision.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

import duckdb  # noqa: E402

FX_DIR = PROJECT / "data" / "fx_expert"
LEDGER = PROJECT / "data" / "fx_ledger.jsonl"
STORE = "/home/mrc/opentrader-data/store.duckdb"

LANES = {"g151": "fxexp-g151", "g138": "fxexp-g138", "g137": "fxexp-g137"}
TRAIL_ATR = 2.0   # default: 2.0 ATR from peak
TP_ATR = 3.0      # default: 3.0 ATR from entry


def load_atr():
    """pair -> latest atr_pct (14d rolling high-low / close)."""
    con = duckdb.connect(STORE, read_only=True)
    rows = con.execute("""
        SELECT symbol, atr_pct FROM (
            SELECT symbol, ts, close,
                   MAX(high) OVER w14 / close AS atr_pct,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) rn
            FROM bars WHERE timeframe = '1d'
            WINDOW w14 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)
        ) WHERE rn = 1
    """).fetchall()
    con.close()
    return {sym: float(a) for sym, a in rows}


def check_trails(ex, my_tag, trail_atr=TRAIL_ATR, tp_atr=TP_ATR, dry=False):
    """One trail/TP check: evaluate every open fxexp trade, close triggered
    ones via per-tradeID. Returns list of closed trades."""
    trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    fx = [t for t in trades if ((t.get("clientExtensions") or {}).get("tag") or "").startswith("fxexp-")]
    if not fx:
        return []
    atr = load_atr()
    closed = []
    state_f = FX_DIR / f"trail_state_{my_tag}.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    peaks = state.setdefault("peaks", {})

    for t in fx:
        tid = t["id"]
        sym = t["instrument"]
        units = float(t["currentUnits"])
        if units == 0:
            continue
        direction = "long" if units > 0 else "short"
        entry = float(t["price"])
        a = atr.get(sym, 0.0) * entry  # ATR in price units
        if a <= 0:
            continue
        px = ex.get_current_price(sym) or entry

        # peak/trough tracking (long tracks peak, short tracks trough)
        pk = peaks.get(tid, {})
        peak = max(pk.get("peak", entry), px)
        trough = min(pk.get("trough", entry), px)
        peaks[tid] = {"peak": peak, "trough": trough}

        trigger = None
        if direction == "long":
            if px < peak - trail_atr * a:
                trigger = f"trail: px {px:.5f} < peak {peak:.5f} - {trail_atr}×ATR"
            elif px > entry + tp_atr * a:
                trigger = f"tp: px {px:.5f} >= entry {entry:.5f} + {tp_atr}×ATR"
        else:
            if px > trough + trail_atr * a:
                trigger = f"trail: px {px:.5f} > trough {trough:.5f} + {trail_atr}×ATR"
            elif px < entry - tp_atr * a:
                trigger = f"tp: px {px:.5f} <= entry {entry:.5f} - {tp_atr}×ATR"

        if not trigger:
            continue

        # close by tradeID (surgical)
        if dry:
            print(f"[{my_tag}] (dry) {sym} {direction} would close: {trigger}")
            continue
        r = ex._request("PUT", f"/v3/accounts/{ex._account_id}/trades/{tid}/close")
        if isinstance(r, dict) and "orderCreateTransaction" in r:
            pl = float(r.get("orderFillTransaction", {}).get("pl", 0))
            closed.append({"timestamp": datetime.now(timezone.utc).isoformat(),
                           "symbol": sym, "side": "SELL" if units > 0 else "BUY",
                           "quantity": abs(units), "price": px,
                           "order_id": tid, "pl": pl,
                           "reason": f"trail-close ({trigger})", "tag": my_tag})
            print(f"[{my_tag}] {sym} {direction} CLOSED: {trigger} | pl {pl:+.2f}")
            peaks.pop(tid, None)  # trade closed — clean up peak tracking
        else:
            print(f"[{my_tag}] {sym} {direction} close FAILED: {str(r)[:100]}")
        time.sleep(0.3)

    state["peaks"] = peaks
    state["asof"] = datetime.now(timezone.utc).isoformat()
    if not dry:
        state_f.parent.mkdir(parents=True, exist_ok=True)
        state_f.write_text(json.dumps(state, indent=1))
    return closed


def run_all(dry=False):
    from strategies.expert_lifecycle import active_lanes
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[trail] connect failed")
    all_closed = []
    active = active_lanes()  # expert IDs in accruing/probation
    for expert, my_tag in LANES.items():
        eid = f"fx-expert-{expert}"
        if eid not in active:
            print(f"[{my_tag}] lifecycle not active — skipping trail check")
            continue
        closed = check_trails(ex, my_tag, dry=dry)
        all_closed.extend(closed)
    # append to ledger
    if all_closed and not dry:
        seen = set()
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines():
                if line.strip():
                    try:
                        r = json.loads(line)
                        seen.add((r.get("timestamp"), r.get("symbol"),
                                  r.get("order_id", "")))
                    except Exception:
                        pass
        with LEDGER.open("a") as f:
            for c in all_closed:
                key = (c["timestamp"], c["symbol"], c["order_id"])
                if key not in seen:
                    seen.add(key)
                    f.write(json.dumps(c, default=str) + "\n")
            f.flush()
    print(f"[trail] {len(all_closed)} simulated exits ({'dry' if dry else 'live'})")
    return all_closed


if __name__ == "__main__":
    dry = "--once" not in sys.argv
    run_all(dry=dry)
