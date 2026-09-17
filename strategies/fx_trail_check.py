#!/usr/bin/env python3
"""fx_trail_check — selective trailing stop / TP for trained FX lanes.

SCALE-OUT MODEL (2026-09-14): a trigger REDUCES the leg by REDUCE_FRAC and
re-arms (trail reference reset to the current price), rather than closing it
outright — the human's "reduce the position and rotate it into another". The
remainder rides; a second trigger trims again; below MIN_REMAIN_FRAC of the
original size the leg is closed out (dust). Accumulated trims are written to
trail_state_<tag>.json["trimmed"] = {sym: fraction_of_original}, which the lane
reads to redeploy the freed weight (fx_expert_lane.rotate_weights).

Mode (binding cron contract): no flag = DRY (evaluate, track peaks, log
would-closes; no orders); --once = REAL (closes triggered legs at the venue).
Since 2026-09-13 the timer runs DRY by human decision — the OOS A/B
(fxexpert/trailing_ab.py) showed every forced-exit variant losing to
hold-to-rebalance, and the service had crossed the human gate silently
(docs/agents/research/trail-closer-gate-brief-2026-09-13.md).

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

def _lane_tags():
    """Dynamic {short_tag: lane_tag} from lifecycle active fx-expert lanes."""
    from strategies.expert_lifecycle import active_lanes
    result = {}
    for eid in active_lanes():
        if not eid.startswith("fx-expert-"):
            continue
        short = eid.replace("fx-expert-", "")
        result[short] = "fxexp-" + short
    return result

TRAIL_ATR = 2.0   # default: 2.0 ATR from peak
TP_ATR = 2.0      # ATR from entry. Lowered 3.0 -> 2.0 on 2026-09-14: the
# book sat on winners at 20-80% of the old 3x target (GBP_AUD +0.99% vs
# 1.25% needed, USD_ZAR +1.55% vs 2.37%) so nothing ever banked. The A/B
# prices the TP channel as near-free (tp 2.0: PF 0.599, tp 3.0: 0.603 vs
# baseline 0.604) — unlike the trail variants, which are the costly ones.
# One TP per trade (tp_done), then the trail manages the remainder.
# SCALE-OUT (human directive 2026-09-14: "reduce the position and rotate
# it into another"): a trigger trims a fraction and re-arms, instead of
# dumping the whole leg. The freed capital is redistributed by the lane
# (rotate_weights) instead of sitting idle for up to a rebalance.
MIN_UNITS = 100        # dust floor — mirrors fx_expert_lane.MIN_UNITS
REDUCE_FRAC = 0.5      # fraction of the position closed per trigger
MIN_REMAIN_FRAC = 0.25 # below this share of the original size, close out


def load_atr():
    """pair -> latest atr_pct: mean 14d (high - low) / close, a FRACTION of
    price (e.g. 0.004 = 0.4%). Callers multiply by the entry price for
    ATR in price units.

    NOTE (fixed 2026-09-14): the SQL used MAX(high)/close — a ratio just
    above 1.0 (median 1.0074), not the fraction this module's docstring
    describes. Callers used it as a fraction, so trail/TP thresholds sat
    ~2x PRICE away and could never trigger: that is the real reason behind
    "0 triggers in 829 live runs", read as "the trail is wide" in
    trail-closer-gate-brief-2026-09-13.md. Mean range is the documented
    intent and a sane threshold basis."""
    con = duckdb.connect(STORE, read_only=True)
    rows = con.execute("""
        SELECT symbol, atr_pct FROM (
            SELECT symbol, ts, close,
                   AVG(high - low) OVER w14 / close AS atr_pct,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY ts DESC) rn
            FROM bars WHERE timeframe = '1d'
            WINDOW w14 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)
        ) WHERE rn = 1
    """).fetchall()
    con.close()
    return {sym: float(a) for sym, a in rows}


def _halted_pairs(ex, symbols):
    """Venue-halted legs: status != tradeable AND stale price timestamp >30min.

    Same rule the lane's halt-gate applies (fx_expert_lane.py). Without it the
    closer retries a halted leg every 5 minutes and — before the fix below —
    recorded a phantom close row each time it was ORDER_CANCEL/MARKET_HALTED.
    """
    if not symbols:
        return set()
    now_s = time.time()
    out = set()
    for pr in ex._request(
            "GET", f"/v3/accounts/{ex._account_id}/pricing?instruments="
                   f"{','.join(sorted(symbols))}").get("prices", []):
        if pr.get("status") == "tradeable":
            continue
        try:
            ts = datetime.fromisoformat(
                str(pr.get("time", "")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if now_s - ts > 1800:
            out.add(pr["instrument"])
    return out


def check_trails(ex, my_tag, trail_atr=TRAIL_ATR, tp_atr=TP_ATR, dry=False):
    """One trail/TP check: evaluate every open fxexp trade, close triggered
    ones via per-tradeID. Returns list of closed trades."""
    trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    fx = [t for t in trades if (t.get("clientExtensions") or {}).get("tag") == my_tag]
    if not fx:
        return []
    atr = load_atr()
    closed = []
    state_f = FX_DIR / f"trail_state_{my_tag}.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    peaks = state.setdefault("peaks", {})
    origins = state.setdefault("origins", {})
    trimmed = state.setdefault("trimmed", {})
    trimmed_units = state.setdefault("trimmed_units", {})
    # A TP scale-out re-arms the trail, but the TP condition is measured from
    # ENTRY and stays true — without this marker the leg would be trimmed
    # again on every 5-minute run until it was gone (a cascade back to the
    # all-or-nothing behaviour this replaced). One TP per trade; the trail
    # manages the remainder afterwards.
    tp_done = state.setdefault("tp_done", {})

    halted = _halted_pairs(ex, {t["instrument"] for t in fx})
    for t in fx:
        tid = t["id"]
        sym = t["instrument"]
        units = float(t["currentUnits"])
        if units == 0:
            continue
        if sym in halted:
            print(f"[{my_tag}] {sym} HALTED at venue — trail check deferred")
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
        tp_hit = (px > entry + tp_atr * a) if direction == "long" \
            else (px < entry - tp_atr * a)
        if direction == "long":
            if px < peak - trail_atr * a:
                trigger = f"trail: px {px:.5f} < peak {peak:.5f} - {trail_atr}×ATR"
            elif tp_hit and not tp_done.get(tid):
                trigger = f"tp: px {px:.5f} >= entry {entry:.5f} + {tp_atr}×ATR"
        else:
            if px > trough + trail_atr * a:
                trigger = f"trail: px {px:.5f} > trough {trough:.5f} + {trail_atr}×ATR"
            elif tp_hit and not tp_done.get(tid):
                trigger = f"tp: px {px:.5f} <= entry {entry:.5f} - {tp_atr}×ATR"

        if not trigger:
            continue

        # scale-out: trim a fraction, re-arm; close out only near dust
        orig = float(origins.get(tid) or abs(units))
        if tid not in origins:
            origins[tid] = abs(units)
        trim = max(1.0, round(abs(units) * REDUCE_FRAC))
        remaining = abs(units) - trim
        full = remaining < max(MIN_UNITS, orig * MIN_REMAIN_FRAC)
        act = "close" if full else "reduce"
        if dry:
            print(f"[{my_tag}] (dry) {sym} {direction} would {act} "
                  f"{abs(units) if full else trim:.0f}u of {abs(units):.0f}u: {trigger}")
            closed.append({"would_close": True, "symbol": sym,
                           "tag": my_tag, "trigger": trigger})
            continue
        body = {} if full else {"units": str(int(trim))}
        r = ex._request("PUT", f"/v3/accounts/{ex._account_id}/trades/{tid}/close",
                        body=body or None)
        # A close order is CREATED on every PUT; only an orderFillTransaction
        # means it FILLED. Accepting orderCreateTransaction wrote a phantom
        # row for the halted USD_TRY close (txn 4232 created, 4233 cancelled
        # MARKET_HALTED, 2026-09-14) — the same lying-response class as #167.
        fill = (r.get("orderFillTransaction") if isinstance(r, dict) else None)
        if fill is not None:
            pl = float(fill.get("pl") or 0)
            fill_px = float(fill.get("price") or px)
            qty = abs(units) if full else int(trim)
            closed.append({"timestamp": datetime.now(timezone.utc).isoformat(),
                           "symbol": sym, "side": "SELL" if units > 0 else "BUY",
                           "quantity": qty, "price": fill_px,
                           "order_id": tid, "pl": pl,
                           "reason": f"{act} ({trigger})", "tag": my_tag})
            print(f"[{my_tag}] {sym} {direction} {act.upper()} {qty}u of "
                  f"{abs(units):.0f}u: {trigger} | pl {pl:+.2f}")
            if full:
                peaks.pop(tid, None)   # closed out — drop tracking
                origins.pop(tid, None)
                tp_done.pop(tid, None)
                trimmed.pop(sym, None)
                trimmed_units.pop(sym, None)
            else:
                if trigger.startswith("tp"):
                    tp_done[tid] = True   # one TP per trade (see above)
                # record the trim for the lane's rotation, and re-arm the trail
                trimmed[sym] = min(1.0, trimmed.get(sym, 0.0) + qty / max(orig, 1.0))
                # units freed — the lane redeploys exactly these (rotation)
                trimmed_units[sym] = trimmed_units.get(sym, 0) + int(qty)
                peaks[tid] = {"peak": px, "trough": px}
        else:
            why = ""
            if isinstance(r, dict):
                why = ((r.get("orderCancelTransaction") or {}).get("reason")
                       or (r.get("orderRejectTransaction") or {}).get("rejectedReason")
                       or "no fill")
            print(f"[{my_tag}] {sym} {direction} close NOT FILLED ({why}) "
                  f"— not recorded, retried next run")
        time.sleep(0.3)

    # prune tracking for trades that are no longer open (entries otherwise
    # accumulate forever as the book rotates — 82 peaks for 16 trades after
    # the g137/g138 cut)
    live_tids = {t["id"] for t in fx}
    for tid in [k for k in peaks if k not in live_tids]:
        peaks.pop(tid, None)
        origins.pop(tid, None)
        tp_done.pop(tid, None)
    state["peaks"] = peaks
    state["origins"] = origins
    state["trimmed"] = trimmed
    state["trimmed_units"] = trimmed_units
    state["tp_done"] = tp_done
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
    lanes = _lane_tags()
    for expert, my_tag in lanes.items():
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
    n = len(all_closed)
    print(f"[trail] {n} {'would-exit (DRY — no orders sent)' if dry else 'scale-outs/reduces (LIVE — real orders sent)'}")
    return all_closed


if __name__ == "__main__":
    dry = "--once" not in sys.argv
    run_all(dry=dry)
