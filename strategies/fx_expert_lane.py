#!/usr/bin/env python3
"""fx_expert_lane — live lane for the gate-PASSing fxexpert rank books.

Wires the three amended-gate experts (fx-expert-g137/g138/g151) into the
OANDA practice account as competing lanes (human directive 2026-09-06:
demo funds, bottom two cut at Friday close). Mirrors the backtest: a
dollar-neutral weekly rank-rebalanced book over the accrual store's pairs,
10-day-horizon transformer scores, weights held 5 trading days.

CRON CONTRACT (binding): --once means REAL orders; no flag = dry run.
Never pass --once to "test".

Account-sharing rules (netted venue, one account):
  - every order carries the lane tag (tradeClientExtensions) — attribution
    is tag-based; the legacy fill-size matcher is untouched (sizes vary)
  - a symbol held by ANOTHER tag is entered only in the direction that
    increases the account net (never reduces |net|) — reducing deltas are
    deferred to a later run; this is the same arbitration the legacy lanes
    apply, relaxed where netting is provably safe
  - no server-side SL/TP (the backtest holds to rebalance); lane-initiated
    closes only, so every close is tagged
Deviations from the backtest, documented: foreign-held symbols skipped
(their legs deferred), sub-100-unit legs not traded (dust), econ-blackout
not applied (the book holds through events by design).

Usage:
  python3 -m strategies.fx_expert_lane --expert g151 --once   # REAL
  python3 -m strategies.fx_expert_lane --expert g151          # dry
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from exchange.oanda import OandaExchange  # noqa: E402

from fxexpert import data as fxdata  # noqa: E402
from fxexpert import gate as fxgate  # noqa: E402
from fxexpert import train as fxtrain  # noqa: E402
from strategies import lane_claims  # noqa: E402
from strategies.fx_trail_check import check_trails  # noqa: E402

FX_DIR = PROJECT / "data" / "fx_expert"
LEDGER = PROJECT / "data" / "fx_ledger.jsonl"
REFRESH_MARK = FX_DIR / "refresh_state.json"
NOTIONAL = 2000          # account-ccy units per unit weight, per expert
MIN_UNITS = 100          # dust floor — legs below this are not traded
REFRESH_DAYS = 14        # incremental bar upsert window
REBAL = 5                # trading days per weight period (mirrors rebal=5)
LANES = {"g137": "fxexp-g137", "g138": "fxexp-g138", "g151": "fxexp-g151"}


def _fill_key(f):
    return (str(f.get("timestamp", "")), f.get("symbol", ""),
            (f.get("side") or "").lower(), f.get("quantity", 0), f.get("price", 0))


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


def refresh_store(ex):
    """Incremental bar upsert (D1 full pull, H1 recent window) + panel
    rebuild. Skipped only when the venue's latest D1 bar is already in the
    panel (venue-truth gate — a wall-clock date marker alone would skip the
    refresh if it was written earlier the same UTC day, e.g. a manual run
    after midnight, and trade stale weights). Dry runs reuse the stored
    panel (read-only)."""
    if dry_check_fresh(ex):
        print("[lane] venue has no bars newer than panel — refresh skipped")
        return
    syms = [r[0] for r in __import__("duckdb").connect(
        "/home/mrc/opentrader-data/store.duckdb", read_only=True).execute(
        "SELECT DISTINCT symbol FROM bars").fetchall()]
    import duckdb
    import pandas as pd
    con = duckdb.connect("/home/mrc/opentrader-data/store.duckdb")
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - __import__("datetime").timedelta(days=REFRESH_DAYS)
    cols = ["symbol", "timeframe", "ts", "open", "high", "low", "close", "volume"]
    for sym in syms:
        for tf in ("1d", "1h"):
            try:
                bars = ex.get_bars(sym, tf, 5000)
            except Exception as e:
                print(f"[lane] {sym} {tf} refresh FAILED: {e}")
                continue
            rows = [{"symbol": sym, "timeframe": tf,
                     "ts": datetime.fromtimestamp(b.timestamp, tz=timezone.utc).replace(tzinfo=None),
                     "open": b.open, "high": b.high, "low": b.low,
                     "close": b.close, "volume": b.volume} for b in bars]
            rows = [r for r in rows if r["ts"] >= cutoff]
            if rows:
                con.execute("DELETE FROM bars WHERE symbol = ? AND timeframe = ? AND ts >= ?",
                            [sym, tf, cutoff])
                con.register("up", pd.DataFrame(rows, columns=cols))
                con.execute("INSERT INTO bars SELECT * FROM up")
                con.unregister("up")
            time.sleep(0.25)
    con.close()
    print("[lane] bars refreshed — rebuilding panel (minutes)...")
    fxdata.build()
    REFRESH_MARK.write_text(json.dumps({"date": datetime.now(timezone.utc).date().isoformat(),
                                        "panel_date": json.loads(
        (FX_DIR / "panel_meta.json").read_text())["date_max"]}))
    print("[lane] panel rebuilt")


def dry_check_fresh(ex):
    """True when the venue's latest D1 bar (EUR_USD probe) is already
    covered by the panel — i.e. no refresh needed."""
    try:
        meta = json.loads((FX_DIR / "panel_meta.json").read_text())
        bars = ex.get_bars("EUR_USD", "1d", 2)
        if not bars:
            return True
        latest = datetime.fromtimestamp(bars[-1].timestamp, tz=timezone.utc).date().isoformat()
        return str(meta.get("date_max"))[:10] >= latest
    except Exception:
        return False  # probe failed → refresh (safe default)


def today_weights(tag):
    """Rank weights for the panel's latest date from the expert checkpoint."""
    panel = fxtrain.load_panel()
    ckpt = torch.load(FX_DIR / "checkpoints" / f"{tag}.pt", weights_only=True)
    cfg = ckpt["config"]
    model = fxtrain.FXExpert(cfg["n_feat"], cfg["d_model"], cfg["n_layers"],
                             cfg["n_heads"], cfg["dropout"], cfg["T"]).to(fxtrain.DEVICE)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    day = panel["date"]
    last = int(day.max())
    rows_v, win_v = fxtrain._windows(panel["pair_idx"], len(day))
    sel = day[rows_v] == last
    rows = rows_v[sel]
    X = panel["features"][win_v[sel]]
    Xs = np.nan_to_num(np.clip(
        (X - ckpt["feat_mean"].numpy()) / ckpt["feat_std"].numpy(), -8, 8)).astype(np.float32)
    with torch.no_grad():
        score = model(torch.from_numpy(Xs).to(fxtrain.DEVICE)).cpu().numpy()
    w = fxgate._positions_rank(
        np.full(len(rows), last), panel["pair_idx"][rows], score,
        vol20=(panel["vol20"][rows] if "vol20" in panel and cfg.get("vol_target") else None),
        cost=panel["cost"][rows], lev=cfg.get("lev", 1.0),
        vol_target=bool(cfg.get("vol_target")), cost_cap=cfg.get("cost_cap"),
        rebal=1)
    w = np.nan_to_num(np.asarray(w), nan=0.0, posinf=0.0, neginf=0.0)
    pairs = {m["idx"]: m["pair"] for m in
             json.loads((FX_DIR / "panel_meta.json").read_text())["pairs"]}
    weights = {pairs[int(panel["pair_idx"][i])]: float(ww)
               for i, ww in zip(rows, w) if abs(ww) > 1e-9}
    udays = np.unique(day)
    period = int(np.where(udays == last)[0][0]) // REBAL
    return weights, period, str(np.datetime64(last, "D"))


def quote_usd_rates(ex, quotes, known_pairs):
    """quote-ccy → USD rate, priced off whichever USD orientation exists
    (USD_AUD is not a real instrument; AUD_USD is). USD → 1.0."""
    out, want = {"USD": 1.0}, []
    for q in quotes:
        if q == "USD":
            continue
        if f"USD_{q}" in known_pairs:
            want.append(f"USD_{q}")
        elif f"{q}_USD" in known_pairs:
            want.append(f"{q}_USD")
    if want:
        chunk = ",".join(sorted(set(want)))
        for pr in ex._request("GET", f"/v3/accounts/{ex._account_id}/pricing?instruments={chunk}").get("prices", []):
            b = pr.get("bids") or pr.get("closes") or []
            if not b:
                continue
            inst = pr["instrument"]
            out[inst.split("_")[1]] = (1.0 / float(b[0]["price"])) if inst.startswith("USD_") \
                else float(b[0]["price"])
    return out


def venue_books(ex, my_tag):
    """Per-symbol: my tagged units, foreign units (venue-authoritative)."""
    trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    mine, foreign = {}, {}
    for t in trades:
        tag = (t.get("clientExtensions") or {}).get("tag") or "untagged"
        bucket = mine if tag == my_tag else foreign
        bucket[t["instrument"]] = bucket.get(t["instrument"], 0) + int(t["currentUnits"])
    return mine, foreign


def run(expert, dry=False, force=False, consolidate=False):
    my_tag = LANES[expert]
    # lifecycle gate: the registry controls whether this lane can run
    from strategies.expert_lifecycle import lifecycle_of, notional_cap
    lc = lifecycle_of(my_tag.replace("fxexp-", "fx-expert-"))
    if lc is None:
        lc = lifecycle_of(my_tag)
    if lc is None:
        print(f"[{my_tag}] not registered — using default notional 1.0")
        lc = {"lifecycle": "accruing", "notional_cap": 1.0}
    lstate = lc.get("lifecycle", "accruing")
    ncap = float(lc.get("notional_cap", 1.0))
    if lstate in ("cut", "archived"):
        raise SystemExit(f"[{my_tag}] lifecycle is {lstate} — lane refuses to start")
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit(f"[{my_tag}] connect failed")
    bal = ex.get_balance()
    print(f"[{my_tag}] connected: balance ${bal.cash:,.2f} (dry={dry}) "
          f"(lifecycle={lstate}, notional_cap={ncap})")

    if not dry:
        refresh_store(ex)
    weights, period, panel_day = today_weights(expert)
    print(f"[{my_tag}] panel {panel_day}: {len(weights)} legs, "
          f"net {sum(weights.values()):+.3f}, gross {sum(abs(w) for w in weights.values()):.1f}")
    # conviction auction: write scores, recompute claims on period change
    lane_claims.write_scores(my_tag, {p: abs(w) for p, w in weights.items()})
    state_f = FX_DIR / f"lane_state_{expert}.json"
    state = json.loads(state_f.read_text()) if state_f.exists() else {}
    claims = lane_claims.current_claims()
    if period != state.get("last_period") or force or not claims:
        claims = lane_claims.recompute()
        mine_n = sum(1 for v in claims.values() if v["lane"] == my_tag)
        print(f"[{my_tag}] claims recomputed: {len(claims)} pairs, mine {mine_n}")

    if period == state.get("last_period") and state.get("last_period") is not None and not force:
        check_trails(ex, my_tag, dry=dry)
        print(f"[{my_tag}] period {period} already traded — weights held (rebal every {REBAL} days)")
        return
    if not weights:
        print(f"[{my_tag}] no weights for {panel_day} — nothing to do")
        return

    mine, foreign = venue_books(ex, my_tag)
    # USD-notional sizing: 1 unit = 1 base-ccy unit; its USD value is
    # price × quote_usd_rate. Dividing by price alone (v0.1 bug, caught via
    # the Warden's notes 2026-09-08) shrinks USD-base legs by the pair price
    # and non-USD-quote crosses by the quote→USD rate (JPY legs ran ~$11).
    pairs = sorted({t["instrument"] for t in ex._request(
        "GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])}
        | set(weights.keys()))
    quotes = sorted({p.split("_")[1] for p in pairs})
    rates = quote_usd_rates(ex, quotes, set(pairs))
    def usd_per_base(sym):
        base, quote = sym.split("_")
        px = ex.get_current_price(sym)
        if px is None:
            px = 1.0
        return px * rates.get(quote, 1.0)
    fills = []
    # order plan: reductions/exits as per-tradeID closes (surgical — netting
    # orders FIFO-close other lanes' older fragments), same-sign adds/opens
    # as market orders with the foreign-net guard
    all_trades = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    my_trades = {}
    for t in all_trades:
        if (t.get("clientExtensions") or {}).get("tag") == my_tag:
            my_trades.setdefault(t["instrument"], []).append(t)

    def close_units_by_trade(sym, units_needed):
        """Close exactly units_needed units of my trades on sym, oldest
        first, via per-tradeID closes. Returns [(tid, closed)]."""
        done = []
        need = float(units_needed)
        for t in sorted(my_trades.get(sym, []), key=lambda x: int(x["id"])):
            if need <= 0:
                break
            cu = abs(float(t["currentUnits"]))
            c = min(need, cu)
            if c < 1:
                continue
            r = ex._request("PUT", f"/v3/accounts/{ex._account_id}/trades/{t['id']}/close",
                            body={"units": str(int(round(c)))})
            if isinstance(r, dict) and "orderCreateTransaction" in r:
                done.append((t["id"], c))
                need -= c
            time.sleep(0.25)
        return done

    def _record(sym, side, qty, price=0.0, oid=""):
        fills.append({"timestamp": datetime.now(timezone.utc).isoformat(),
                      "symbol": sym, "side": side, "quantity": qty,
                      "price": price, "order_id": oid,
                      "reason": "rank-rebal", "tag": my_tag})

    # deltas: signed units of change per symbol (target − mine), exits included
    deltas = {}
    for sym, w in weights.items():
        owner = lane_claims.owner_of(sym, claims)
        if owner != my_tag:
            if mine.get(sym, 0):
                deltas[sym] = -mine[sym]  # lost the claim — full exit
            continue
        target = int(round(w * NOTIONAL * ncap / max(usd_per_base(sym), 1e-9)))
        if abs(target) < MIN_UNITS:
            if mine.get(sym, 0):
                deltas[sym] = -mine[sym]  # fell below dust — exit
            continue
        deltas[sym] = target - mine.get(sym, 0)
    for sym in sorted(mine):
        if sym not in weights and abs(mine[sym]) >= MIN_UNITS:
            deltas[sym] = -mine[sym]  # held but no longer a leg -> exit

    # halt-gate: venue status per leg before ordering — non-tradeable legs
    # are deferred as HALT (distinct from rejections). Real halts (TRY-class)
    # have a stale price timestamp (>30 min); transient snapshots don't.
    pairs_csv = ",".join(pairs)
    halt_pairs = set()
    if pairs_csv:
        now_s = time.time()
        for pr in ex._request("GET", f"/v3/accounts/{ex._account_id}/pricing?instruments={pairs_csv}").get("prices", []):
            if pr.get("status") not in ("tradeable",):
                ts = str(pr.get("time", ""))
                try:
                    pt = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    if now_s - pt > 1800:
                        halt_pairs.add(pr["instrument"])
                except (ValueError, KeyError):
                    pass

    for sym in sorted(deltas, key=lambda s: -abs(deltas[s])):
        delta = deltas[sym]
        if delta == 0:
            continue
        if sym in halt_pairs:
            print(f"[{my_tag}] {sym} HALTED at venue — deferred (halt-gate)")
            continue
        m = mine.get(sym, 0.0)
        f_units = foreign.get(sym, 0)

        # reduce/exit: per-tradeID closes (surgical — netting orders FIFO-close
        # other lanes' older fragments)
        if m != 0 and ((delta > 0) != (m > 0) or abs(delta) <= abs(m)):
            close_qty = min(abs(delta), abs(m))
            side = "SELL" if m > 0 else "BUY"
            if dry:
                print(f"[{my_tag}] (dry) CLOSE {close_qty:.0f} of {sym} via tradeIDs")
                _record(sym, side, close_qty)
                continue
            done = close_units_by_trade(sym, close_qty)
            for tid, c in done:
                _record(sym, side, c, oid=tid)
            print(f"[{my_tag}] CLOSE {sym} {close_qty:.0f}u via {len(done)} tradeID closes")
            if abs(delta) > abs(m):  # flip remainder: market order
                rem = abs(delta) - abs(m)
                side2 = "BUY" if delta > 0 else "SELL"
                if f_units != 0 and net != 0 and (side2 == "BUY") != (net > 0):
                    print(f"[{my_tag}] {sym} flip remainder deferred (foreign net)")
                    continue
                r = ex.place_order(sym, side2, rem, "market", tag=my_tag,
                                   client_id=f"{my_tag}-{sym[:8]}-{int(time.time()) % 100000}")
                if r.status == "filled":
                    _record(sym, side2, rem, price=r.price, oid=r.order_id)
                    print(f"[{my_tag}] {side2} {sym} {rem} (flip) -> filled @ {r.price}")
            continue

        # pure add/open: market order with the foreign-net guard
        net = m + f_units
        if f_units != 0 and net != 0 and (delta > 0) != (net > 0):
            print(f"[{my_tag}] {sym} add {delta:+} would reduce foreign-held net "
                  f"({f_units:+} foreign) — deferred (arbitration)")
            continue
        side = "BUY" if delta > 0 else "SELL"
        qty = abs(delta)
        if dry:
            print(f"[{my_tag}] (dry) would {side} {sym} {qty} units "
                  f"(target {delta + m:+.0f}, mine {m:+.0f})")
            continue
        r = ex.place_order(sym, side, qty, "market", tag=my_tag,
                           client_id=f"{my_tag}-{sym[:8]}-{int(time.time()) % 100000}")
        if r.status != "filled":
            print(f"[{my_tag}] {side} {sym} {qty} REJECTED ({r.status}) — retried next run")
            continue
        _record(sym, side, qty, price=r.price, oid=r.order_id)
        print(f"[{my_tag}] {side} {sym} {qty} -> {r.status} @ {r.price}")
        time.sleep(0.3)

    _append_ledger(fills)
    if not dry:
        state.update({"last_period": period, "last_traded": panel_day,
                      "updated": datetime.now(timezone.utc).isoformat(),
                      "note": "cache only — venue is authoritative"})
        state_f.write_text(json.dumps(state, indent=1))
        print(f"[{my_tag}] {len(fills)} fills; state -> {state_f.name} (period {period})")
    else:
        print(f"[{my_tag}] dry run — {len(fills)} would-fill, no state/ledger write")


def main():
    args = sys.argv[1:]
    expert = args[args.index("--expert") + 1] if "--expert" in args else None
    if expert not in LANES:
        raise SystemExit(f"usage: --expert [{'|'.join(LANES)}] [--once] [--force]")
    run(expert, dry="--once" not in args, force="--force" in args,
        consolidate="--consolidate" in args)


if __name__ == "__main__":
    main()
