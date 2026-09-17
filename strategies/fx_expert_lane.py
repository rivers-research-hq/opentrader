#!/usr/bin/env python3
"""fx_expert_lane — live lane for the gate-PASSing fxexpert rank books.

Wires the three amended-gate experts (fx-expert-g137/g138/g151) into the
OANDA practice account as competing lanes (human directive 2026-09-06:
demo funds, bottom two cut at Friday close). Mirrors the backtest: a
dollar-neutral weekly rank-rebalanced book over the accrual store's pairs,
10-day-horizon transformer scores, weights held REBAL=30 trading days.

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

# The lane's scoring model is ~340k params — CPU inference is instant. Pin
# to CPU BEFORE importing fxexpert.train: the lane runs 21:25-21:45 UTC
# (prime gaming time) and must never grab a GPU (AGENTS.md 2026-09-13),
# nor fail on VRAM contention.
os.environ.setdefault("FXEXPERT_DEVICE", "cpu")

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
REBAL = 5                # trading days per weight period.
# RECONCILIATION 2026-09-14 (this constant was briefly 30 — reverted):
# the 30-day cadence was set from fxexpert/trailing_ab.py on generation gab1
# (PF 0.604@5d -> 1.013@30d, "turnover dominates"). The gate's own protocol,
# scored on the LIVE generations with BOTH metrics, says the opposite:
#   g151 (deployed): 5d PF 1.0846 / +0.333 bp-day   30d PF 0.9962 / -0.013
#   g185 (best pass): 5d PF 1.2862 / +1.096 bp-day  30d PF 1.0868 / +0.328
#   g221/g222 (panel-v2 transfer): 30d slightly better than 5d
# So the cadence optimum is GENERATION-specific, and gab1's ranking did not
# transfer to the deployed book (the same generation-specificity the gate's
# own stats study documents for PF). Holding 30 days costs more signal than it
# saves in spread for the live book. Cadence is therefore re-derived per
# generation at deployment time, on the gate, using both PF and bp/day.
def _lane_tags():
    """Dynamic {short_tag: lane_tag} from lifecycle active lanes.
    Replaces the hardcoded LANES dict — any actively accruing fx-expert
    lane is immediately runnable without a code change."""
    from strategies.expert_lifecycle import active_lanes
    result = {}
    for eid in active_lanes():
        if not eid.startswith("fx-expert-"):
            continue
        short = eid.replace("fx-expert-", "")
        result[short] = "fxexp-" + short
    return result


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
            # An unpriced row is not evidence — a fill we cannot price corrupts
            # every FIFO/PnL consumer downstream. 102 such rows were written
            # during the 2026-09-09/10 venue freezes (get_current_price failed
            # after a venue fill) and 59 more by unguarded dry runs; both are
            # quarantined. Refuse at write time.
            if float(fill.get("price") or 0) <= 0:
                print(f"[ledger] REFUSED unpriced fill {fill.get('symbol')} "
                      f"{fill.get('side')} {fill.get('quantity')} "
                      f"(reason={fill.get('reason')}) — not recorded")
                continue
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
            # A probe that returns nothing is NOT evidence of freshness.
            # Returning True here meant a venue hiccup silently disabled every
            # future refresh (fail-open on the one gate that keeps the panel
            # current).
            return False
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
    # FEATURE CONTRACT (2026-09-14): the panel builder grew 48 -> 61 features
    # (pv_carry/fred block inserted mid-list) after the deployed checkpoint was
    # trained. Feeding all 61 would be a shape mismatch (crash) or, worse, the
    # wrong columns at the same indices. Select the checkpoint's features BY
    # NAME, in its trained order, so the weights see exactly what they learned.
    feat_names = list(panel["feature_names"])
    want = None
    fpath = FX_DIR / "checkpoints" / f"{tag}.features.json"
    if fpath.exists():
        want = json.loads(fpath.read_text())["feature_names"]
    if want:
        missing = [n for n in want if n not in feat_names]
        if missing:
            raise SystemExit(f"[{tag}] panel is missing trained features: "
                             f"{missing[:5]} — retrain required")
        col = [feat_names.index(n) for n in want]
        # shape is (rows, T, n_feat) — the feature axis is LAST
        X = panel["features"][win_v[sel]][..., col]
        if X.shape[-1] != ckpt["config"]["n_feat"]:
            raise SystemExit(f"[{tag}] feature contract mismatch: selected "
                             f"{X.shape[-1]}, checkpoint expects "
                             f"{ckpt['config']['n_feat']}")
    else:
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


def _trail_state_path(my_tag):
    return FX_DIR / f"trail_state_{my_tag}.json"


def load_trimmed_units(my_tag):
    """{symbol: units the trail closed} — the capital to redeploy."""
    p = _trail_state_path(my_tag)
    if not p.exists():
        return {}
    try:
        return (json.loads(p.read_text()) or {}).get("trimmed_units") or {}
    except Exception:
        return {}


def clear_trimmed_units(my_tag):
    """Handled -> reset, so the same freed units are not redeployed twice."""
    p = _trail_state_path(my_tag)
    if not p.exists():
        return
    try:
        d = json.loads(p.read_text()) or {}
    except Exception:
        return
    if d.get("trimmed_units"):
        d["trimmed_units"] = {}
        p.write_text(json.dumps(d, indent=1))


def rescale_trimmed_units(my_tag, keep):
    """Retain `keep` of the recorded freed units (the undeployed remainder)."""
    p = _trail_state_path(my_tag)
    if not p.exists():
        return
    try:
        d = json.loads(p.read_text()) or {}
    except Exception:
        return
    tu = d.get("trimmed_units") or {}
    if tu:
        d["trimmed_units"] = {k: int(round(v * keep)) for k, v in tu.items()
                              if int(round(v * keep)) > 0}
        p.write_text(json.dumps(d, indent=1))


def rotate_execute(ex, my_tag, adds):
    """Market adds that redeploy freed capital (halt-gated, tagged, protected).

    Returns the units actually filled, so the caller can retain the rest.
    """
    halted = set()
    try:
        from strategies.fx_trail_check import _halted_pairs
        halted = _halted_pairs(ex, set(adds))
    except Exception as exc:
        print(f"[{my_tag}] rotation halt-check unavailable ({exc})")
    deployed = 0.0
    for sym in sorted(adds, key=lambda s: -abs(adds[s])):
        qty = abs(adds[sym])
        if sym in halted:
            print(f"[{my_tag}] rotate {sym} HALTED at venue — deferred")
            continue
        side = "BUY" if adds[sym] > 0 else "SELL"
        r = ex.place_order(sym, side, qty, "market", tag=my_tag,
                           client_id=f"{my_tag}-rot-{sym[:8]}-{int(time.time()*1000)}")
        if r.status != "filled":
            print(f"[{my_tag}] rotate {side} {sym} {qty} REJECTED "
                  f"({r.status}: {_why(r)}) — retried next run")
            continue
        _append_ledger([{"timestamp": datetime.now(timezone.utc).isoformat(),
                         "symbol": sym, "side": side, "quantity": qty,
                         "price": r.price, "order_id": r.order_id,
                         "reason": "rotation", "tag": my_tag}])
        deployed += qty
        print(f"[{my_tag}] rotate {side} {sym} {qty}u -> filled @ {r.price}")
        time.sleep(0.3)
    return deployed


def load_trims(my_tag):
    """{symbol: fraction trimmed} written by the trail's scale-outs."""
    p = _trail_state_path(my_tag)
    if not p.exists():
        return {}
    try:
        return (json.loads(p.read_text()) or {}).get("trimmed") or {}
    except Exception:
        return {}


def clear_trims(my_tag):
    p = _trail_state_path(my_tag)
    if not p.exists():
        return
    try:
        d = json.loads(p.read_text()) or {}
    except Exception:
        return
    if d.get("trimmed"):
        d["trimmed"] = {}
        p.write_text(json.dumps(d, indent=1))


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
    my_tag = _lane_tags().get(expert)
    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit(f"[{my_tag}] connect failed")
    # --consolidate: the cut-path flatten (lifecycle v2: a cut means
    # "positions close"). Runs BEFORE the lifecycle gate — the whole point is
    # to flatten a lane that is about to be (or just was) cut. --once governs
    # REAL, exactly like every other lane entry point.
    if consolidate:
        from strategies.fx_flatten import flatten_tag
        res = flatten_tag(ex, my_tag, dry=dry)
        for c in res["closed"]:
            verb = "(dry) CLOSE" if c.get("dry") else f"CLOSE @ {c['price']}"
            print(f"[{my_tag}] {verb} {c['symbol']} {c['quantity']}u")
        for r in res["rejected"]:
            print(f"[{my_tag}] REJECTED {r['symbol']} tradeID "
                  f"{r['trade_id']}: {r['why']} — rerun to retry")
        rows = [c for c in res["closed"] if not c.get("dry")]
        if dry:
            print(f"[{my_tag}] dry run — {len(res['closed'])} would-close, "
                  f"no ledger write")
        else:
            _append_ledger(rows)
            print(f"[{my_tag}] consolidate: {len(rows)} closed, "
                  f"{len(res['rejected'])} rejected")
        return
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
        if period != state.get("last_period"):
            # new period: the book is re-picked, so scale-out trims no longer
            # constrain targets — clear them (stale trims would distort the
            # fresh weights).
            clear_trims(my_tag)

    if period == state.get("last_period") and state.get("last_period") is not None and not force:
        check_trails(ex, my_tag, dry=dry)
        # ROTATION (human directive 2026-09-14): capital freed by scale-outs is
        # redeployed into the book's untouched legs now, rather than sitting
        # idle until the next 30-day rebalance. Trimmed legs are NOT refilled.
        trims = load_trims(my_tag)
        freed = load_trimmed_units(my_tag)
        if not trims or not freed:
            print(f"[{my_tag}] period {period} already traded — weights held "
                  f"(rebal every {REBAL} days)")
            return
        # rotate only the units the trail closed, within the current book
        m_now, _f = venue_books(ex, my_tag)
        tgt = rotation_targets(m_now, freed)
        adds = {s: tgt[s] - m_now.get(s, 0) for s in tgt
                if abs(tgt[s] - m_now.get(s, 0)) >= MIN_UNITS}
        if not adds:
            print(f"[{my_tag}] rotation: nothing to redeploy "
                  f"({len(freed)} trimmed leg(s), no same-side room)")
            return
        print(f"[{my_tag}] rotation: redeploying {sum(abs(v) for v in adds.values()):.0f}u "
              f"from {sorted(freed)} across {len(adds)} same-side leg(s)")
        if dry:
            for s in sorted(adds, key=lambda x: -abs(adds[x])):
                print(f"[{my_tag}] (dry) rotate {adds[s]:+d}u {s} "
                      f"(held {m_now.get(s, 0):+d})")
            return
        deployed = rotate_execute(ex, my_tag, adds)
        # Only the units that actually reached the market are retired: an
        # allocation below the dust floor is not redeployed, and clearing the
        # whole marker would silently bank it instead of rotating it.
        total_freed = sum(abs(v) for v in freed.values())
        if total_freed > 0 and deployed < total_freed:
            keep = max(0.0, 1.0 - deployed / total_freed)
            rescale_trimmed_units(my_tag, keep)
            print(f"[{my_tag}] rotation: {total_freed - deployed:.0f}u left "
                  f"(below the {MIN_UNITS}u dust floor) — kept for the next run")
        else:
            clear_trimmed_units(my_tag)
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
        first, via per-tradeID closes. Returns [(tid, closed, price)]."""
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
            fill = r.get("orderFillTransaction") if isinstance(r, dict) else None
            if fill:
                # A close fill must be priceable: the venue response carries
                # "price" normally, but during freezes it can be absent and a
                # price-0 row is not evidence (see _append_ledger). Fall back
                # to the venue's own trade record, then to a fresh quote.
                price = float(fill.get("price") or fill.get("fullVWAP") or 0)
                if price <= 0:
                    tr = ex._request(
                        "GET", f"/v3/accounts/{ex._account_id}/trades/{t['id']}")
                    price = float((tr.get("trade") or {}).get("price") or 0)
                if price <= 0:
                    price = float(ex.get_current_price(sym) or 0)
                done.append((t["id"], c, price))
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
    # VENUE-WIDE MAINTENANCE EXEMPTION (2026-09-13, pre-open readiness): the
    # lanes run 21:25-21:45 UTC, inside OANDA's daily maintenance freeze —
    # every leg then reads non-tradeable with a stale timestamp and the gate
    # deferred ALL of period 1045's rebalance (89 fills in period 1044 vs 0
    # in 1045). >30% of the legs stale = the venue-wide freeze (the same rule
    # fx_warden.instability uses), not per-pair halts: defer nothing (orders
    # at these times filled for weeks before the gate existed).
    pairs_csv = ",".join(pairs)
    halt_pairs = set()
    if pairs_csv:
        now_s = time.time()
        stale_pairs = set()
        for pr in ex._request("GET", f"/v3/accounts/{ex._account_id}/pricing?instruments={pairs_csv}").get("prices", []):
            if pr.get("status") not in ("tradeable",):
                ts = str(pr.get("time", ""))
                try:
                    pt = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    if now_s - pt > 1800:
                        stale_pairs.add(pr["instrument"])
                except (ValueError, KeyError):
                    pass
        if len(stale_pairs) > max(1, int(0.3 * len(pairs))):
            print(f"[{my_tag}] {len(stale_pairs)}/{len(pairs)} legs stale — "
                  f"venue-wide maintenance window, halt-gate stands down")
        else:
            halt_pairs = stale_pairs

    # "traded" honesty (2026-09-13): the period is marked traded only on real
    # progress — >=1 fill, or the book was already at target. Friday 09-12's
    # all-halt-deferred run marked period 1045 traded with ZERO fills (the
    # book then cannot rebalance until the next period opens), and a
    # rejected-order run would have done the same while printing "retried
    # next run" — a promise the already-traded gate made void. Leave the
    # period open on no progress; a retry run finishes the rebalance.
    actionable = 0  # deltas that reached a real order/close attempt
    for sym in sorted(deltas, key=lambda s: -abs(deltas[s])):
        delta = deltas[sym]
        if delta == 0:
            continue
        if sym in halt_pairs:
            print(f"[{my_tag}] {sym} HALTED at venue — deferred (halt-gate)")
            continue
        m = mine.get(sym, 0.0)
        f_units = foreign.get(sym, 0)
        net = m + f_units  # venue net for this symbol; used by both branches below

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
            actionable += 1
            for tid, c, price in done:
                _record(sym, side, c, price=price, oid=tid)
            print(f"[{my_tag}] CLOSE {sym} {close_qty:.0f}u via {len(done)} tradeID closes")
            if abs(delta) > abs(m):  # flip remainder: market order
                rem = abs(delta) - abs(m)
                side2 = "BUY" if delta > 0 else "SELL"
                if f_units != 0 and net != 0 and (side2 == "BUY") != (net > 0):
                    print(f"[{my_tag}] {sym} flip remainder deferred (foreign net)")
                    continue
                r = ex.place_order(sym, side2, rem, "market", tag=my_tag,
                                   client_id=f"{my_tag}-{sym[:8]}-{int(time.time() * 1000)}")
                actionable += 1
                if r.status == "filled":
                    _record(sym, side2, rem, price=r.price, oid=r.order_id)
                    print(f"[{my_tag}] {side2} {sym} {rem} (flip) -> filled @ {r.price}")
            continue

        # pure add/open: market order with the foreign-net guard
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
                           client_id=f"{my_tag}-{sym[:8]}-{int(time.time() * 1000)}")
        actionable += 1
        if r.status != "filled":
            print(f"[{my_tag}] {side} {sym} {qty} REJECTED ({r.status}: {_why(r)}) — retried next run")
            continue
        _record(sym, side, qty, price=r.price, oid=r.order_id)
        print(f"[{my_tag}] {side} {sym} {qty} -> {r.status} @ {r.price}")
        time.sleep(0.3)

    if not dry:
        _append_ledger(fills)
        # mark traded only on real progress: >=1 fill, or no open deltas at
        # all (book at target). All-deferred (halt/arbitration) or
        # all-rejected runs leave the period open for a retry.
        n_deltas = sum(1 for d in deltas.values() if d != 0)
        if fills or n_deltas == 0:
            state.update({"last_period": period, "last_traded": panel_day,
                          "updated": datetime.now(timezone.utc).isoformat(),
                          "note": "cache only — venue is authoritative"})
            state_f.write_text(json.dumps(state, indent=1))
            print(f"[{my_tag}] {len(fills)} fills; state -> {state_f.name} (period {period})")
        else:
            print(f"[{my_tag}] {actionable} actionable deltas, 0 fills — period "
                  f"{period} NOT marked traded; the next run retries the rebalance")
        # at-entry protection (human directive 2026-09-14): attach the hard
        # SL/TP backstop to anything of ours still unprotected — the legs we
        # just opened AND any older leg the book carried in.
        try:
            from strategies.fx_trail_check import load_atr
            p = protect_open_trades(ex, my_tag, load_atr())
            if p["attached"]:
                print(f"[{my_tag}] protected {len(p['attached'])} trade(s)")
            for sym, tid, why in p["failed"]:
                print(f"[{my_tag}] protect FAILED {sym} tradeID {tid}: {why}")
        except Exception as exc:
            print(f"[{my_tag}] protect pass failed (non-fatal): {exc}")
    else:
        print(f"[{my_tag}] dry run — {len(fills)} would-fill, no state/ledger write")


def main():
    args = sys.argv[1:]
    expert = args[args.index("--expert") + 1] if "--expert" in args else None
    lanes = _lane_tags()
    if expert not in lanes:
        raise SystemExit(f"usage: --expert [{'|'.join(lanes)}] [--once] "
                         f"[--force] [--consolidate] [--protect]")
    if "--protect" in args:
        # Attach server-side SL/TP to this lane's unprotected open trades and
        # exit. --once means REAL, as everywhere else.
        from strategies.fx_trail_check import load_atr
        dry = "--once" not in args
        my_tag = _lane_tags().get(expert)
        ex = OandaExchange()
        if not ex.connect():
            raise SystemExit(f"[{my_tag}] connect failed")
        res = protect_open_trades(ex, my_tag, load_atr(), dry=dry)
        for sym, tid, note, *rest in res["attached"]:
            print(f"[{my_tag}] {'(dry) ' if dry else ''}PROTECT {sym} "
                  f"tradeID {tid}: {note}")
        for sym, tid, why in res["skipped"]:
            print(f"[{my_tag}] skip {sym} tradeID {tid}: {why}")
        for sym, tid, why in res["failed"]:
            print(f"[{my_tag}] FAILED {sym} tradeID {tid}: {why}")
        print(f"[{my_tag}] protect: {len(res['attached'])} attached, "
              f"{len(res['skipped'])} skipped, {len(res['failed'])} failed"
              f"{' (dry)' if dry else ''}")
        return
    run(expert, dry="--once" not in args, force="--force" in args,
        consolidate="--consolidate" in args)




def _why(r):
    """The venue's own reject/cancel reason for a non-fill response.

    Four rejection defects (2026-09-04..10) were untriageable because the
    lanes logged only "REJECTED (rejected)". place_order already carries the
    reason in OrderResult.raw; surface it so the next one self-documents.
    """
    raw = getattr(r, "raw", None) or {}
    return (raw.get("reason") or raw.get("rejectReason")
            or raw.get("cancelReason") or "no fill (venue returned no reason)")


# ── server-side protection (human directive 2026-09-14: "Both") ──────────
# Hard SL/TP attached to the venue trade itself, so protection survives
# restarts and does not depend on this box being up. Levels mirror the
# trail-check's own math (fx_trail_check.TP_ATR) with a deliberately WIDER
# stop than the 2.0 ATR trail, so the trail normally exits first and this is
# the backstop. Levels already breached at attach time are SKIPPED, never
# attached — attaching a through-the-price stop would fire instantly and turn
# a bookkeeping action into a market exit.
SL_ATR = 3.0
TP_ATR = 3.0


def rotation_targets(mine, freed_units, same_side_only=True):
    """Units targets for rotating capital the trail's scale-outs freed.

    `mine` = {sym: signed units held NOW (post-trim)}, `freed_units` = {sym:
    units the trail closed}. Trimmed legs keep their current size (never
    refilled — that would fight the exit); the freed units are spread across
    the same-side legs still held, pro-rata to their size.

    Net semantics: each side's TOTAL is restored to its pre-trim level, so the
    rotated book's net equals the net the book had BEFORE the trim (i.e.
    net(targets) = net(mine) + signed(freed)). Redeploying a trimmed long back
    into other longs re-invests capital the trim had taken out of the book —
    that is the point of rotating rather than banking it.

    Deliberately units-based, NOT weight-based: the model's target weights
    drift with each day's panel, so re-targeting after a trim would quietly
    re-balance daily and defeat the 30-day cadence. This moves only the units
    the trail actually closed. Pure + unit-tested (tests/test_fx_rotation.py).
    """
    tgt = dict(mine)
    freed = {1: 0.0, -1: 0.0}
    for sym, u in freed_units.items():
        if sym in mine and mine[sym]:
            freed[1 if mine[sym] > 0 else -1] += abs(u)
    for side in (1, -1):
        legs = [s for s in mine
                if s not in freed_units and mine[s] * side > 0]
        base = sum(abs(mine[s]) for s in legs)
        if legs and freed[side] > 0 and base > 0:
            for s in legs:
                add = freed[side] * (abs(mine[s]) / base) * side
                tgt[s] = mine[s] + add
    if not same_side_only:
        raise NotImplementedError("cross-side rotation changes net exposure")
    return {s: int(round(v)) for s, v in tgt.items()}


def stop_levels(entry, atr_frac, long, sl_atr=SL_ATR, tp_atr=TP_ATR):
    """(stop_loss, take_profit) price levels, or (None, None) if unusable.

    Pure + unit-tested (tests/test_fx_atr_units.py): `atr_frac` MUST be a
    FRACTION of price (0.005 = 0.5%), which is what load_atr() returns. The
    MAX(high)/close-era value (~1.0) silently inverted these levels — the
    guard below turns that class of mistake into a loud (None, None) instead
    of a stop on the wrong side of the market.
    """
    if not entry or not atr_frac or atr_frac <= 0 or not (0 < atr_frac < 0.5):
        return None, None
    if long:
        return entry * (1 - sl_atr * atr_frac), entry * (1 + tp_atr * atr_frac)
    return entry * (1 + sl_atr * atr_frac), entry * (1 - tp_atr * atr_frac)


def protect_open_trades(ex, tag, atr_by_pair, dry=False):
    """Attach server-side SL/TP to this lane's unprotected open trades.

    Idempotent: trades that already carry both orders are skipped. Returns
    {"attached": [...], "skipped": [...], "failed": [...]} for the caller to
    log. New entries call this right after their fill, so `at entry` is the
    same run; existing book legs are covered by the first pass.
    """
    out = {"attached": [], "skipped": [], "failed": []}
    trades = ex._request(
        "GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
    for t in trades:
        if (t.get("clientExtensions") or {}).get("tag") != tag:
            continue
        sym = t["instrument"]
        price = float(t.get("price") or 0)     # entry
        cur = ex.get_current_price(sym)
        a = float(atr_by_pair.get(sym) or 0)
        if t.get("stopLossOrder") and t.get("takeProfitOrder"):
            out["skipped"].append((sym, t["id"], "already protected"))
            continue
        if not price or not cur or a <= 0:
            out["failed"].append((sym, t["id"],
                                  f"no basis (entry={price} px={cur} atr={a})"))
            continue
        long = float(t["currentUnits"]) > 0
        sl, tp = stop_levels(price, a, long)
        if sl is None:
            out["failed"].append((sym, t["id"], f"unusable ATR basis ({a})"))
            continue
        if (long and (cur <= sl or cur >= tp)) or (not long and (cur >= sl or cur <= tp)):
            out["skipped"].append(
                (sym, t["id"], f"level already breached (entry={price} px={cur})"))
            continue
        if dry:
            out["attached"].append((sym, t["id"], f"SL {sl:.6g} TP {tp:.6g}", True))
            continue
        body = {"stopLoss": {"price": ex._fmt_price(sym, sl), "timeInForce": "GTC"},
                "takeProfit": {"price": ex._fmt_price(sym, tp), "timeInForce": "GTC"}}
        r = ex._request("PUT",
                        f"/v3/accounts/{ex._account_id}/trades/{t['id']}/orders",
                        body=body)
        if isinstance(r, dict) and not r.get("_error") and (
                r.get("stopLossOrder") or r.get("takeProfitOrder")
                or r.get("lastTransactionID")):
            out["attached"].append((sym, t["id"], f"SL {sl:.6g} TP {tp:.6g}"))
        else:
            out["failed"].append((sym, t["id"], str(r)[:160]))
        time.sleep(0.2)
    return out

if __name__ == "__main__":
    main()
