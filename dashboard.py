#!/usr/bin/env python3
"""OpenTrader Web Dashboard — REST API + simple HTML UI on port 8097.

Replaces the broken PVA-only helper. Serves portfolio state, PVA history,
and a lightweight dashboard page. Run: python3 dashboard.py --port 8097
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow

import argparse
import asyncio
import json
import logging
import math
import sqlite3
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("opentrader.dashboard")

PROJECT = str(Path(__file__).resolve().parent)
REGISTRY_DB = Path(PROJECT) / "data" / "newsfeed" / "agent_registry.db"
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Paths ──────────────────────────────────────────────────────────────
DATA_DIR = Path(PROJECT) / "data"
STATE_FILE = DATA_DIR / "paper_state.json"
HISTORY_DIR = DATA_DIR / "history"



# ── Helpers ────────────────────────────────────────────────────────────
_SANITIZE_RE = re.compile(r"\b(?:NaN|-?Infinity)\b")


def _sanitize_nan(obj):
    """Recursively replace float('nan')/float('inf')/-inf with None."""
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _read_state() -> dict:
    """Read paper_state.json safely."""
    if not STATE_FILE.exists():
        return {}
    try:
        raw = STATE_FILE.read_text()
        raw = _SANITIZE_RE.sub("null", raw)
        return _sanitize_nan(json.loads(raw))
    except Exception as e:
        logger.warning(f"state file unreadable ({STATE_FILE}): {e}")
        return {}


_HIST_CACHE = {"ts": 0.0, "files": None}
_HIST_TTL = 5.0


def _list_history_files() -> list[Path]:
    """Sorted history files (newest first by mtime). Cached 5s to cut poll churn."""
    import time as _t

    now = _t.time()
    if _HIST_CACHE["files"] is not None and (now - _HIST_CACHE["ts"]) < _HIST_TTL:
        return _HIST_CACHE["files"]
    if not HISTORY_DIR.exists():
        _HIST_CACHE["files"] = []
    else:
        _HIST_CACHE["files"] = sorted(
            HISTORY_DIR.glob("cycle_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )[:2000]
    _HIST_CACHE["ts"] = now
    return _HIST_CACHE["files"]


_PVA_CACHE = {"ts": 0.0, "data": None, "n": 0}
_PVA_TTL = 15.0


def _build_pva(num_points: int = 500) -> dict:
    """Build portfolio-value-over-time data for charting. Cached 15s.

    Returns points in chronological order (oldest first); portfolio_pct is
    measured against the account's initial_cash, not the first snapshot in
    the window.
    """
    import time as _t

    now = _t.time()
    if (
        _PVA_CACHE["data"] is not None
        and _PVA_CACHE["n"] == num_points
        and (now - _PVA_CACHE["ts"]) < _PVA_TTL
    ):
        return _PVA_CACHE["data"]
    files = _list_history_files()
    if not files:
        return {"points": [], "count": 0}

    files = files[:num_points]  # keep most recent N (still newest-first)
    files = list(reversed(files))  # chronological: oldest first
    sample_n = max(1, len(files) // num_points)
    points = []
    base_cash = None
    base_prices = {}

    for fpath in files[::sample_n]:
        try:
            d = json.loads(fpath.read_text())
        except Exception:
            continue
        pv = d.get("portfolio_value", 0)
        prices = d.get("prices", {})
        ts = d.get("timestamp", "")
        if pv <= 0:
            continue
        if base_cash is None:
            base_cash = d.get("initial_cash") or pv
        pt = {
            "ts": str(ts)[:19],
            "portfolio_pct": round((pv / max(base_cash, 0.01) - 1) * 100, 2),
            "portfolio": round(pv, 2),
        }
        for sym, px in prices.items():
            sym_short = sym.split("/")[0]
            if sym_short not in base_prices and px > 0:
                base_prices[sym_short] = px
            if sym_short in base_prices and base_prices[sym_short] > 0:
                pt[sym_short] = round((px / base_prices[sym_short] - 1) * 100, 2)
        points.append(pt)

    # Append live state as latest point
    try:
        s = _read_state()
        pv = s.get("portfolio_value", 0)
        prices = s.get("prices", {})
        ts = s.get("timestamp", "")
        if base_cash is None:
            base_cash = s.get("initial_cash") or pv
        if pv > 0 and base_cash:
            pt = {
                "ts": str(ts)[:19],
                "portfolio_pct": round((pv / max(base_cash, 0.01) - 1) * 100, 2),
                "portfolio": round(pv, 2),
            }
            for sym, px in prices.items():
                sym_short = sym.split("/")[0]
                if sym_short not in base_prices and px > 0:
                    base_prices[sym_short] = px
                if sym_short in base_prices and base_prices[sym_short] > 0:
                    pt[sym_short] = round((px / base_prices[sym_short] - 1) * 100, 2)
            if pt not in points:
                points.append(pt)
    except Exception as e:
        logger.warning(f"live-state PVA append failed: {e}")

    result = {"points": points, "count": len(points)}
    _PVA_CACHE["data"] = result
    _PVA_CACHE["n"] = num_points
    _PVA_CACHE["ts"] = _t.time()
    return result


# ── FastAPI App ────────────────────────────────────────────────────────
app = FastAPI(title="OpenTrader Dashboard", version="1.0")

# Serve static assets (three.min.js for the 3D neural-network visualization)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_FX_CACHE = {"ts": 0.0, "data": None}
_FLAT_CACHE = {"ts": 0.0, "data": None}


_FX_REFRESHING = {"t": False}


def _refresh_fx_cache():
    """Background recompute — the served snapshot stays available (stale-while-
    revalidate), so fast pollers never block on OANDA latency."""
    import time as _time
    try:
        out = _compute_fx()
        _FX_CACHE["data"] = out
        _FX_CACHE["ts"] = _time.time()
    finally:
        _FX_REFRESHING["t"] = False


def _fx_snapshot() -> dict:
    """Live FX watch data. Stale-while-revalidate: instant serve from cache;
    a background thread refreshes when older than 30s. Fast pollers (the
    TUIs) never block on OANDA latency and never trigger concurrent
    refreshes. Cold cache (restart): serve a warming payload immediately —
    the cold compute takes ~15-20s (throttled venue walk) and must never
    block the first request."""
    import threading
    import time as _time
    if _FX_CACHE["data"] is not None:
        if _time.time() - _FX_CACHE["ts"] >= 30 and not _FX_REFRESHING["t"]:
            _FX_REFRESHING["t"] = True
            threading.Thread(target=_refresh_fx_cache, daemon=True).start()
        out = dict(_FX_CACHE["data"])
        out["flat"] = _flat_reasons()  # reasons have their own 300s TTL
        return out
    if not _FX_REFRESHING["t"]:
        _FX_REFRESHING["t"] = True
        threading.Thread(target=_refresh_fx_cache, daemon=True).start()
    return {"warming": True, "book": [], "fills": [], "registry": [], "queue": {},
            "balance": None, "nav": None, "error": None,
            "note": "cold cache — first compute in progress, poll again"}
def _compute_fx() -> dict:
    import time as _time
    out = {"book": [], "fills": [], "registry": [], "queue": {}, "error": None}
    try:
        from exchange.oanda import OandaExchange
        ex = OandaExchange()
        if ex.connect():
            book = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
            # live prices, so every row can show the DISTANCE to its targets
            pxs = {}
            try:
                pxs = ex.get_prices_batch(sorted({t["instrument"] for t in book})) or {}
            except Exception:
                pass
            for t in book:
                sym = t.get("instrument")
                ent = float(t.get("price") or 0)
                cur = float(pxs.get(sym) or 0)
                pip = 10 ** (-ex._price_digits(sym)) if sym else 0
                sl_o, tp_o = t.get("stopLossOrder"), t.get("takeProfitOrder")
                sl = float(sl_o["price"]) if sl_o else None
                tp = float(tp_o["price"]) if tp_o else None
                def _dist(level):
                    if not level or not cur:
                        return None, None
                    d = abs(level - cur)
                    return (round(d / cur * 100, 2),
                            round(d / pip) if pip else None)
                to_tp_pct, to_tp_pips = _dist(tp)
                to_sl_pct, to_sl_pips = _dist(sl)
                prog = None
                if tp and ent and cur and tp != ent:
                    prog = round((cur - ent) / (tp - ent) * 100, 1)
                out["book"].append({
                    "px": round(cur, 6) if cur else None,
                    "tp": tp, "sl": sl,
                    "to_tp_pct": to_tp_pct, "to_tp_pips": to_tp_pips,
                    "to_sl_pct": to_sl_pct, "to_sl_pips": to_sl_pips,
                    "progress_to_tp": prog,
                    "trade_id": t.get("id"), "instrument": t.get("instrument"),
                    "units": t.get("currentUnits"), "price": t.get("price"),
                    "opened": str(t.get("openTime", ""))[:19],
                    "owner": (t.get("clientExtensions") or {}).get("tag") or "unknown",
                    "pl": t.get("unrealizedPL"),
                    # BOTH orders = protected. Checking either one counted a
                    # leg with a stop but no target (venue 2026-09-14:
                    # USD_CHF/h4-brk had SL only) as fully protected.
                    "protected": bool(t.get("stopLossOrder")
                                      and t.get("takeProfitOrder")),
                    "orders": ("SL" if t.get("stopLossOrder") else "")
                              + ("TP" if t.get("takeProfitOrder") else "") or "-",
                })
            acct = ex._request("GET", f"/v3/accounts/{ex._account_id}")["account"]
            out["balance"] = acct.get("balance")
            out["nav"] = acct.get("NAV")
            # Venue day-window PnL (what the OANDA UI shows): realized today
            # resets at the venue day boundary; financing is the nightly carry
            # charge — previously invisible in every scoreboard (not a fill).
            try:
                summary = ex._request(
                    "GET", f"/v3/accounts/{ex._account_id}/summary")["account"]
                out["realized_today"] = float(summary.get("realizedPL", 0) or 0)
                out["financing_today"] = float(summary.get("financing", 0) or 0)
            except Exception:
                out["realized_today"] = None
                out["financing_today"] = None
            # protection coverage + the policy values the lane runs under
            # (2026-09-14: SL/TP backstops, 30-day cadence, scale-out trims).
            prot = [t for t in out["book"] if t["protected"]]
            unprot = [t for t in out["book"] if not t["protected"]]
            why = {}
            for t in unprot:
                if t.get("orders") not in ("-", None):
                    why[t["instrument"]] = f"partial ({t['orders']} only)"
            if unprot:
                try:
                    sys.path.insert(0, str(PROJECT))
                    from strategies.fx_trail_check import _halted_pairs
                    halted = _halted_pairs(ex, {t["instrument"] for t in unprot})
                    for sym in halted:
                        why[sym] = "venue-halted"   # merge: keep partial-order reasons
                except Exception:
                    pass
            out["protection"] = {
                "total": len(out["book"]), "protected": len(prot),
                "unprotected": [{"symbol": t["instrument"], "trade_id": t["trade_id"],
                                 "why": why.get(t["instrument"], "no SL/TP order")}
                                for t in unprot],
            }
            out["_ex"] = ex
        else:
            out["error"] = "OANDA connect failed"
    except Exception as e:
        out["error"] = str(e)
    ledger = DATA / "fx_ledger.jsonl"
    if ledger.exists():
        rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
        # append-only ledger corrections (map #158 #171): hide void rows and
        # the phantom rows they void — the venue never executed those fills
        voided = {ts for r in rows if r.get("reason") == "phantom-void"
                  for ts in (r.get("voids") or [])}
        rows = [r for r in rows if r.get("reason") != "phantom-void"
                and r.get("timestamp") not in voided]
        out["fills"] = rows[-25:][::-1]
    reg = DATA / "epoch_registry.json"
    if reg.exists():
        out["registry"] = json.loads(reg.read_text()).get("experts", [])
    try:
        from strategies.fx_review import load_events, load_labels
        out["queue"] = {"events": len(load_events()), "labeled": len(load_labels())}
    except Exception:
        pass
    policy: dict[str, object] = {
        "expert": "no-active-expert", "cadence_days": 5,
        "period": None, "last_traded": None,
        "trimmed_frac": {}, "rotation_pending": {},
    }
    try:
        sys.path.insert(0, str(PROJECT))
        from strategies.fx_expert_lane import REBAL
        from strategies.expert_lifecycle import active_lanes
        active = [e for e in active_lanes() if e.startswith("fx-expert-")]
        if active:
            my_eid = active[0]
            my_tag = my_eid.replace("fx-expert-", "fxexp-")
            ls = DATA / "fx_expert" / f"lane_state_{my_tag[6:]}.json"
            st = json.loads(ls.read_text()) if ls.exists() else {}
            ts = DATA / "fx_expert" / f"trail_state_{my_tag}.json"
            tr = json.loads(ts.read_text()) if ts.exists() else {}
            policy.update({
                "expert": my_tag, "cadence_days": REBAL,
                "period": st.get("last_period"),
                "last_traded": st.get("last_traded"),
                "trimmed_frac": tr.get("trimmed") or {},
                "rotation_pending": tr.get("trimmed_units") or {},
            })
    except Exception as e:
        policy["error"] = str(e)
    out["policy"] = policy
    out["flat"] = _flat_reasons()
    return out


def _flat_reasons() -> dict:
    """Why each non-watchdog lane holds no positions — computed from live
    bars, TTL 300s (signal state changes at most daily)."""
    import time as _time
    if _FLAT_CACHE["data"] is not None and _time.time() - _FLAT_CACHE["ts"] < 300:
        return _FLAT_CACHE["data"]
    out = {}
    try:
        sys.path.insert(0, str(Path(PROJECT) / "scripts"))
        from exchange.oanda import OandaExchange
        from strategies.fx_runner import _venue_book, atr14
        from signal_gym import Ctx, load_candidate, CAND_DIR
        ex = OandaExchange()
        if not ex.connect():
            return {"error": "OANDA down"}
        book = _venue_book(ex)
        held = set(book)
        owners = {i["owner"] for i in book.values()}
        exog = {}
        if (DATA / "exog_cache.json").exists():
            exog = json.load(open(DATA / "exog_cache.json"))
        d1, h1 = {}, {}
        for sym in ex.discover_symbols():
            d1[sym] = ex.get_bars(sym, "1d", 60)
            h1[sym] = ex.get_bars(sym, "1h", 20)
        now_s = datetime.now(timezone.utc)

        # mom-k5: 5d momentum top-2, positive only
        moms = {}
        for sym, bars in d1.items():
            if len(bars) >= 7:
                moms[sym] = bars[-1].close / bars[-6].close - 1.0
        target = [s for s, m in sorted(moms.items(), key=lambda kv: -kv[1])[:2] if m > 0]
        if "mom-k5" not in owners:
            if target:
                out["mom-k5"] = f"would enter {target} — next run"
            else:
                best = min(moms.items(), key=lambda kv: kv[1]) if moms else None
                out["mom-k5"] = (f"no positive 5d momentum (deepest {best[0]} {best[1]:+.2%})"
                                 if best else "no data")

        # c08-fade: evaluate the gym candidate on the live ctx
        if "c08-fade" not in owners:
            cand = load_candidate(CAND_DIR / "c08_mr_fade_cot.py")
            all_dates = sorted({b.timestamp for bars in d1.values() for b in bars})
            picks = {}
            deepest = None
            for sym, bars in d1.items():
                if len(bars) < 22:
                    continue
                closes = [b.close for b in bars]
                i = len(closes) - 1
                ma20 = sum(closes[i - 20:i]) / 20.0 if i >= 20 else None
                if ma20:
                    gap = closes[i] / ma20 - 1
                    if deepest is None or gap < deepest[1]:
                        deepest = (sym, gap)
            series = {sym: {b.timestamp: (b.open, b.high, b.low, b.close) for b in bars}
                      for sym, bars in d1.items()}
            try:
                picks = cand.entry(Ctx(series, all_dates, len(all_dates) - 1,
                                       list(series), exog_series=exog)) or {}
            except Exception:
                picks = {}
            if picks:
                out["c08-fade"] = f"signal live: {list(picks)[:2]} — enters next run"
            elif deepest:
                out["c08-fade"] = (f"no fade setup — deepest {deepest[0]} "
                                   f"{deepest[1]:+.2%} vs -1.50% trigger")
            else:
                out["c08-fade"] = "no data"

        # h1-mom + crash: H1 8-bar momentum on the non-held pool
        pool = [s for s in ex.discover_symbols() if s not in held]
        pool_mom = {}
        for sym in pool:
            bars = h1.get(sym) or []
            if len(bars) >= 9:
                pool_mom[sym] = bars[-1].close / bars[-9].close - 1.0
        pos_pool = {s: m for s, m in pool_mom.items() if m > 0}
        if "h1-mom" not in owners:
            if not pool:
                out["h1-mom"] = "pool empty — all 7 pairs held by other lanes"
            elif pos_pool:
                out["h1-mom"] = f"momentum live: {sorted(pos_pool, key=pos_pool.get, reverse=True)[:2]}"
            else:
                worst = sorted(pool_mom.items(), key=lambda kv: kv[1])[:2]
                out["h1-mom"] = ("pool squeezed to " + str(len(pool)) + " pairs (" +
                                 "held: " + ", ".join(sorted(held)) + ") — all H1 momentum non-positive")
        if "crash" not in owners:
            out["crash"] = ("waiting for positive H1 momentum in pool" if not pos_pool
                            else f"momentum live: {sorted(pos_pool, key=pos_pool.get, reverse=True)[:2]}")
        out["watchdog"] = "response-only — flattens shocks, never opens"
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    _FLAT_CACHE["ts"] = _time.time()
    _FLAT_CACHE["data"] = out
    return out


FX_PAGE = """<!doctype html><html><head><title>OpenTrader FX — practice book</title>
<meta charset="utf-8"><meta http-equiv="refresh" content="60">
<style>
body{background:#0b0f14;color:#c9d4de;font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;margin:24px}
h1,h2{color:#7fb3d5}h2{border-bottom:1px solid #1d2b38;padding-bottom:4px;margin-top:28px}
table{border-collapse:collapse;margin-top:8px}td,th{border:1px solid #1d2b38;padding:4px 10px;text-align:left}
th{color:#8aa2b8;background:#101820}.ok{color:#5fd38a}.err{color:#f0616f}
.dim{color:#5b6b7a}.num{text-align:right}
</style></head><body>
<h1>OpenTrader FX — practice book <span class="dim">(auto-refresh 60s · venue is authoritative)</span></h1>
__CONTENT__
</body></html>"""


@app.get("/fx")
async def fx_page():
    """Live FX practice-book watch page (positions, fills, registry, queue)."""
    s = _fx_snapshot()
    rows = []
    if s["error"]:
        rows.append(f'<p class="err">venue error: {s["error"]}</p>')
    rows.append(f'<p>balance <b>${float(s.get("balance") or 0):,.2f}</b> &middot; '
                f'NAV <b>${float(s.get("nav") or 0):,.2f}</b> &middot; '
                f'preference queue: <b>{s["queue"].get("events", 0)}</b> events, '
                f'{s["queue"].get("labeled", 0)} labeled</p>')
    pol = s.get("policy") or {}
    prot = s.get("protection") or {}
    if pol and not pol.get("error"):
        pend = pol.get("rotation_pending") or {}
        pend_s = (", ".join(f"{k} {v}u" for k, v in sorted(pend.items()))
                  if pend else "none")
        rows.append(
            '<h2>Deployed expert &amp; policy</h2>'
            f'<p><b>{pol.get("expert")}</b> &middot; cadence '
            f'<b>{pol.get("cadence_days")} trading days</b> (ADR-0013) &middot; '
            f'period <b>{pol.get("period")}</b> last traded {pol.get("last_traded")} &middot; '
            f'scale-out trims pending rotation: <b>{pend_s}</b></p>'
            '<p class="dim">g137/g138 cut 2026-09-13 (one-expert deployment, ADR-0011); '
            'scale-out trail LIVE (reduces 50% and re-arms, ADR-0013).</p>')
    if prot:
        un = prot.get("unprotected") or []
        if un:
            lst = ", ".join(f'{u["symbol"]} ({u["why"]})' for u in un)
            rows.append(f'<p>protection: <b>{prot.get("protected")}</b>/'
                        f'{prot.get("total")} legs carry venue SL/TP &middot; '
                        f'<span class="err">unprotected: {lst}</span></p>')
        else:
            rows.append(f'<p>protection: <span class="ok"><b>{prot.get("protected")}</b>/'
                        f'{prot.get("total")} legs carry venue SL/TP</span></p>')
    rows.append('<h2>Open book — with sell targets</h2>'
                '<p class="dim">SELL TARGET = the venue take-profit; the trail sells 50% '
                'there and re-arms (ADR-0013). STOP = the venue stop-loss. '
                '“to TP/SL” = distance from the current price (%, pips); '
                '“progress” = how far entry→target the price has travelled.</p>'
                '<table><tr><th>instrument</th><th>owner</th><th>units</th>'
                '<th>entry</th><th>now</th><th>SELL TARGET</th><th>to TP</th>'
                '<th>progress</th><th>STOP</th><th>to SL</th><th>unrealized</th>'
                '<th>trade</th></tr>')
    if not s["book"]:
        rows.append('<tr><td colspan="12" class="dim">flat</td></tr>')
    for t in s["book"]:
        pl = float(t["pl"] or 0)
        tp = t.get("tp")
        sl = t.get("sl")
        tp_s = f"{tp:.5f}" if tp else '<span class="err">none</span>'
        sl_s = f"{sl:.5f}" if sl else '<span class="err">none</span>'
        to_tp = (f"{t['to_tp_pct']:+.2f}% / {t['to_tp_pips']}p"
                 if t.get("to_tp_pct") is not None else "-")
        to_sl = (f"{t['to_sl_pct']:+.2f}% / {t['to_sl_pips']}p"
                 if t.get("to_sl_pct") is not None else "-")
        prog = t.get("progress_to_tp")
        prog_s = f"{prog:.0f}%" if prog is not None else "-"
        px_s = f"{t['px']:.5f}" if t.get("px") else "-"
        rows.append(f"<tr><td>{t['instrument']}</td><td>{t['owner']}</td>"
                    f"<td class='num'>{t['units']}</td>"
                    f"<td class='num'>{float(t['price'] or 0):.5f}</td>"
                    f"<td class='num'>{px_s}</td>"
                    f"<td class='num'>{tp_s}</td><td class='num'>{to_tp}</td>"
                    f"<td class='num'>{prog_s}</td>"
                    f"<td class='num'>{sl_s}</td><td class='num'>{to_sl}</td>"
                    f"<td class='num'>{pl:+.2f}</td><td>{t['trade_id']}</td></tr>")
    rows.append('</table><h2>Recent fills (ledger tail)</h2>'
                '<table><tr><th>time (UTC)</th><th>symbol</th><th>side</th><th>qty</th>'
                '<th>price</th><th>reason</th></tr>')
    if not s["fills"]:
        rows.append('<tr><td colspan="6" class="dim">no fills yet</td></tr>')
    for f in s["fills"]:
        rows.append(f"<tr><td>{str(f.get('timestamp'))[:19]}</td><td>{f.get('symbol')}</td>"
                    f"<td>{f.get('side')}</td><td class='num'>{f.get('quantity')}</td>"
                    f"<td class='num'>{f.get('price')}</td><td>{f.get('reason')}</td></tr>")
    rows.append('</table><h2>Epoch registry</h2><table><tr><th>expert</th><th>kind</th>'
                '<th>status</th><th>closed (accrual)</th></tr>')
    for e in s["registry"]:
        a = e.get("accrual") or {}
        rows.append(f"<tr><td>{e['expert_id']}</td><td>{e['kind']}</td>"
                    f"<td>{e['status']}</td><td class='num'>{a.get('closed_trades')}</td></tr>")
    rows.append('</table>')
    return HTMLResponse(content=FX_PAGE.replace("__CONTENT__", "\n".join(rows)),
                        headers={"Cache-Control": "no-store, max-age=0"})


DATA = Path(PROJECT) / "data"  # FX data root (also used by /fx page)
FF_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_FEED_NEXT = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"
FF_CACHE = DATA / "cache" / "ff_calendar.json"


def _ff_events():
    """Analyst-consensus calendar (ForexFactory community feed), 6h file cache.
    Per-feed fetch (a 404 on nextweek — FF rotates it at week's end — must not
    discard thisweek), and on total refresh failure fall back to the stale
    cache: an empty calendar reads as "no events" downstream and hides real
    entries (the 09-03/04 TUI staleness — nextweek 404 discarded a valid
    thisweek fetch for ~2 days). Constant literal URLs through the guarded
    opener (SSRF hardening layer)."""
    import time as _time
    try:
        if FF_CACHE.exists() and _time.time() - FF_CACHE.stat().st_mtime < 6 * 3600:
            return json.loads(FF_CACHE.read_text())
    except Exception:
        pass
    from security.guards import guarded_urlopen
    events = []
    fetched = False
    for url in (FF_FEED, FF_FEED_NEXT):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OpenTrader/1.0"})
            with guarded_urlopen(req, timeout=20) as r:
                events += json.load(r)
            fetched = True
        except Exception:
            continue  # one feed failing must not discard the other's events
    if fetched:
        FF_CACHE.parent.mkdir(parents=True, exist_ok=True)
        FF_CACHE.write_text(json.dumps(events))
        return events
    try:  # stale fallback: old events beat an empty calendar
        if FF_CACHE.exists():
            return json.loads(FF_CACHE.read_text())
    except Exception:
        pass
    return []


def _inhouse_state():
    """In-house per-currency state for the calendar: policy rate, 90d change,
    COT leveraged-money z. This is a STATE READ, not a forecast — labeled as
    such everywhere it renders."""
    try:
        exog = json.load(open(DATA / "exog_cache.json"))
    except Exception:
        return {}
    from data.economic_calendar import blackout  # noqa: F401  (module import warm)
    import datetime as dt
    now = dt.date.today()
    out = {}
    for cur, key in (("USD", "RATE:US"), ("EUR", "RATE:EA"), ("GBP", "RATE:GB"), ("CAD", "RATE:CA")):
        s = exog.get(key, {})
        ds = sorted(k for k in s if k <= now.isoformat())
        if not ds:
            continue
        lvl = s[ds[-1]]
        past = [k for k in ds if k <= (now - dt.timedelta(days=90)).isoformat()]
        chg = round(lvl - s[past[-1]], 3) if past else None
        out[cur] = {"rate": lvl, "chg90": chg}
    for cur in ("JPY", "CHF", "AUD", "NZD"):
        out[cur] = {"rate": None, "chg90": None, "note": "no rate source yet (ToC BM3)"}
    for key, cur in (("COT:EUR", "EUR"), ("COT:JPY", "JPY"), ("COT:GBP", "GBP"),
                     ("COT:CHF", "CHF"), ("COT:CAD", "CAD"), ("COT:AUD", "AUD"),
                     ("COT:NZD", "NZD")):
        s = exog.get(key, {})
        usable = [k for k in s if k <= now.isoformat()]
        if usable:
            out.setdefault(cur, {})["cot_z"] = s[usable[-1]]
    return out


@app.get("/api/calendar")
async def api_calendar():
    """Calendar page data: bank decisions (pattern-approx for non-FOMC, ToC BM5),
    analyst-consensus events (ForexFactory feed), in-house per-currency state."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    decisions = []
    try:
        sys.path.insert(0, str(PROJECT))
        from data.economic_calendar import bank_dates
        for bank in ("FED", "ECB", "BOE", "BOJ", "SNB", "BOC", "RBA", "RBNZ"):
            for d in sorted(bank_dates(bank)):
                if now.date() <= d <= now.date() + dt.timedelta(days=45):
                    decisions.append({"date": d.isoformat(), "bank": bank})
        decisions.sort(key=lambda x: x["date"])
    except Exception:
        pass
    cutoff = now + dt.timedelta(days=14)
    ff = []
    # Primary source: the week-view scrape (fetch_ff_upcoming, map #187 #204 —
    # replaces the dead nextweek JSON feed; covers 3 weeks ahead with
    # forecast fields). UTC normalization: FF renders in America/Chicago with
    # DST (verified in #195 against NFP/FFR release times).
    from zoneinfo import ZoneInfo
    CHICAGO = ZoneInfo("America/Chicago")
    up_file = Path("/home/mrc/opentrader-data/feeds/ff_upcoming.json")
    if up_file.exists():
        try:
            up = json.loads(up_file.read_text())
            for e in up.get("events", []):
                try:
                    local = dt.datetime.strptime(
                        f"{e.get('date_label')} {e.get('time_label')}", "%b %d, %Y %I:%M%p")
                    ed = local.replace(tzinfo=CHICAGO).astimezone(dt.timezone.utc)
                except Exception:
                    continue
                if ed >= now and ed <= cutoff and e.get("impact") in ("high", "medium"):
                    ff.append({"date": ed.isoformat(),
                               "title": e.get("name"), "currency": e.get("country"),
                               "impact": (e.get("impact") or "").capitalize(),
                               "forecast": e.get("forecast") or "—",
                               "previous": e.get("previous") or "—"})
        except Exception:
            pass
    if not ff:  # fallback: the legacy JSON feeds (thisweek/nextweek)
        for e in _ff_events():
            try:
                ed = dt.datetime.fromisoformat(e["date"])
                if ed >= now and ed <= cutoff and e.get("impact") in ("High", "Medium"):
                    ff.append({"date": ed.astimezone(dt.timezone.utc).isoformat(),
                               "title": e.get("title"), "currency": e.get("country"),
                               "impact": e.get("impact"), "forecast": e.get("forecast") or "—",
                               "previous": e.get("previous") or "—"})
            except Exception:
                continue
    ff.sort(key=lambda x: x["date"])
    return {"decisions": decisions[:20], "ff_events": ff[:25],
            "inhouse": _inhouse_state(), "generated": now.isoformat()}


@app.get("/api/fx")
async def api_fx():
    """FX watch data as JSON (same source as /fx)."""
    snap = _fx_snapshot()
    snap.pop("_ex", None)  # live exchange object never belongs in JSON
    return snap


def _venue_cursor():
    """Persistent high-water mark for the venue transaction walk.
    First boot walks from 0; restarts start from the last-seen ID."""
    p = Path(__file__).resolve().parent / "data" / "fx_expert" / "venue_cursor.json"
    if p.exists():
        return json.loads(p.read_text()).get("since_id", 0)
    return 0


def _save_venue_cursor(since_id: int):
    p = Path(__file__).resolve().parent / "data" / "fx_expert" / "venue_cursor.json"
    p.write_text(json.dumps({"since_id": since_id}))


def _venue_lane_realized(ex):
    """Per-lane realized from the venue journal (fills' pl attributed via the
    tradeID→tag chain, legacy size fallback pre-08-31)."""
    from strategies.fx_runner import _trade_tags, _walk_transactions
    from strategies.lane_attribution import resolve_fill_tag, LEGACY_CUTOFF, UNATTRIBUTED
    if not ex:
        return {}, {}
    try:
        since = _venue_cursor()
        tags, order_tag = _trade_tags(ex)
        out: dict = {}
        today = datetime.now(timezone.utc).date().isoformat()
        out_today: dict = {}
        max_id = since
        for t in _walk_transactions(
            ex, f"/v3/accounts/{ex._account_id}/transactions/sinceid?id={since}"):
            tid = int(t.get("id", 0))
            if tid > max_id:
                max_id = tid
            if t.get("type") != "ORDER_FILL":
                continue
            tag = resolve_fill_tag(t, tags, order_tag)
            if not tag:
                if t.get("time", "") < LEGACY_CUTOFF:
                    tag = "legacy-smoke"
                else:
                    tag = UNATTRIBUTED
            out.setdefault(tag, 0.0)
            out[tag] += float(t.get("pl", 0) or 0)
            if str(t.get("time", ""))[:10] == today:
                out_today.setdefault(tag, 0.0)
                out_today[tag] += float(t.get("pl", 0) or 0)
        if max_id > since:
            _save_venue_cursor(max_id)
        return out, out_today
    except Exception:
        return {}, {}


@app.get("/api/fx-lanes")
async def api_fx_lanes():
    """FX lane scoreboard for the GUI: realized from the venue journal (tag
    chain, authoritative), rounds/winrate from the void-aware ledger
    attribution (tui.ledger_performance), open counts and uPL from the venue
    book, flat reasons from _flat_reasons. Crash realized overrides from its
    own venue-journal tracker (fx_crashtest.json)."""
    import datetime as dt
    from tui import ledger_performance
    snap = _fx_snapshot()
    perf = ledger_performance()
    venue_realized, venue_today = _venue_lane_realized(snap.pop("_ex", None))
    open_by: dict = {}
    for t in snap.get("book") or []:
        tag = t.get("owner") or "unknown"
        o = open_by.setdefault(tag, {"n": 0, "upl": 0.0})
        o["n"] += 1
        o["upl"] += float(t.get("pl") or 0)
    crash_cache = {}
    try:
        crash_cache = (Path(__file__).resolve().parent / "data" / "fx_crashtest.json")
        crash_cache = json.loads(crash_cache.read_text())
    except Exception:
        crash_cache = {}
    flat = snap.get("flat") or {}
    TRAINED_LANES = ("fxexp-g151", "fxexp-g138", "fxexp-g137")
    # accrual bar (human-adjustable): promotion progress = closed round trips
    # per lane vs this bar (ADR-0009 accruing evidence, forward ledger)
    ACCRUAL_BAR = 30
    EXPERT_LANE = {"fx_mom_k5_top2": "mom-k5", "fx_mr_fade_ma20": "c08-fade",
                   "fx_mr_fade_ma20_cot": "c08-fade", "fx_h1_rev_rsi2": "h1-rev",
                   "fx_h4_donchian20": "h4-brk", "fx_mom_k10_top2": "d1-mom10"}
    lanes = {}
    for tag in ("fxexp-g151", "fxexp-g138", "fxexp-g137",
                "mom-k5", "c08-fade", "h1-mom", "h1-rev", "h4-brk",
                "d1-mom10", "crash", "watchdog"):
        p = perf.get(tag, {})
        realized = venue_realized.get(tag)
        if realized is None:
            realized = p.get("realized")
        if tag == "crash" and crash_cache.get("realized") is not None:
            realized = crash_cache.get("realized")
        lane = {"realized": realized, "rounds": p.get("rounds"),
                "winrate": p.get("winrate"),
                "realized_today": venue_today.get(tag, 0.0),
                "open_n": open_by.get(tag, {}).get("n", 0),
                "open_upl": open_by.get(tag, {}).get("upl", 0.0),
                "flat": flat.get(tag)}
        if tag == "crash":
            lane["note"] = "retired 09-03 — scorecard from venue journal"
        if tag in TRAINED_LANES:
            # 🧠 trained parameter model (fxexpert loop, amended gate 09-06)
            lane["trained"] = True
        lanes[tag] = lane
    # registry accrual progress: closed round trips vs the accrual bar
    for e in snap.get("registry") or []:
        eid = e.get("expert_id", "")
        lane_tag = eid.replace("fx-expert-", "fxexp-") if eid.startswith("fx-expert-") \
            else EXPERT_LANE.get(eid, eid)
        closed = (perf.get(lane_tag) or {}).get("rounds") or 0
        e["lane"] = lane_tag
        e["accrual_closed"] = closed
        e["accrual_bar"] = ACCRUAL_BAR
        e["accrual_pct"] = round(100.0 * closed / ACCRUAL_BAR, 1)
        e["accrual_realized"] = venue_realized.get(lane_tag)
    # lifecycle control-plane state (v2 registry): state, cap, transition reason
    from strategies.expert_lifecycle import active_lanes, notional_cap
    active = set(active_lanes())
    for e in snap.get("registry") or []:
        eid = e.get("expert_id", "")
        e["lifecycle"] = e.get("lifecycle", "candidate")
        e["lifecycle_active"] = eid in active
        e["lifecycle_cap"] = notional_cap(eid)
    return {"lanes": lanes, "balance": snap.get("balance"), "nav": snap.get("nav"),
            "realized_today": snap.get("realized_today"),
            "financing_today": snap.get("financing_today"),
            # the web panels (open book / registry / fill stream) render from
            # this payload — /api/fx's tables ride along (#user-reported:
            # panels rendered from a payload that never carried them)
            "book": snap.get("book") or [], "registry": snap.get("registry") or [],
            "fills": snap.get("fills") or [],
            "error": snap.get("error"), "generated": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/api/lifecycle")
async def api_lifecycle():
    """Control-plane view: the registry state machine read directly from the
    registry file (no cache) — lifecycle, notional cap, accrual, claims, and
    the log tail so every transition is auditable."""
    import sys as _sys
    proj = Path(__file__).resolve().parent
    if str(proj) not in _sys.path:
        _sys.path.insert(0, str(proj))
    from strategies.expert_lifecycle import (
        REGISTRY, STATES, _load_registry, lifecycle_of, active_lanes,
    )
    reg = _load_registry()
    claims = {}
    cf = proj / "data" / "fx_expert" / "claims.json"
    if cf.exists():
        try:
            claims = json.loads(cf.read_text()).get("claims", {})
        except Exception:
            claims = {}
    my_claims = {}
    for pair, v in claims.items():
        my_claims.setdefault(v.get("lane"), []).append(pair)
    active = set(active_lanes())
    experts = []
    for e in reg.get("experts", []):
        eid = e["expert_id"]
        experts.append({
            "expert_id": eid,
            "family": e.get("family"),
            "kind": e.get("kind"),
            "status": e.get("status"),
            "lifecycle": e.get("lifecycle", "candidate"),
            "notional_cap": e.get("notional_cap", 1.0),
            "lifecycle_reason": e.get("lifecycle_reason"),
            "cut_reason": e.get("cut_reason"),
            "lifecycle_changed": e.get("lifecycle_changed"),
            "active": eid in active,
            "registered": e.get("registered"),
            "accrual": e.get("accrual"),
            "notes": e.get("notes"),
            "claims": sorted(my_claims.get(eid.replace("fx-expert-", "fxexp-"), [])),
        })
    log_tail = []
    logf = proj / "data" / "epoch_registry_log.jsonl"
    if logf.exists():
        for line in logf.read_text().splitlines()[-40:]:
            if line.strip():
                try:
                    log_tail.append(json.loads(line))
                except Exception:
                    continue
    return {"experts": experts, "states": STATES, "log": log_tail,
            "generated": datetime.now(timezone.utc).isoformat()}


@app.get("/api/warden")
async def api_warden():
    """The Warden's repository: verified notes, game plans, scoreboards,
    probation state, proposals, and mid-train corpus stats — per-model
    receipts so a future swap can clean-train the successor."""
    import datetime as dt
    w = Path(__file__).resolve().parent / "data" / "warden"
    out = {"model_current": None, "notes": [], "note_stats": {},
           "plan": None, "scorecard": None, "proposals": [],
           "corpus": {"total": 0, "by_mode": {}, "models": {}, "first": None, "last": None},
           "last_run": None}
    notes = []
    if (w / "notes.jsonl").exists():
        for line in (w / "notes.jsonl").read_text().splitlines()[-400:]:
            if not line.strip():
                continue
            try:
                notes.append(json.loads(line))
            except Exception:
                continue
        out["note_stats"] = {"total": len(notes),
                             "verified": sum(1 for n in notes if n.get("verified") is True),
                             "fab_flagged": sum(1 for n in notes if n.get("verified") is False)}
        out["notes"] = notes[-150:]
    if (w / "game_plan.json").exists():
        try:
            out["plan"] = json.loads((w / "game_plan.json").read_text())
        except Exception:
            pass
    if (w / "scorecard.json").exists():
        try:
            out["scorecard"] = json.loads((w / "scorecard.json").read_text())
        except Exception:
            pass
    if (w / "instability.json").exists():
        try:
            out["instability"] = json.loads((w / "instability.json").read_text())
        except Exception:
            out["instability"] = None
    if (w / "proposals.jsonl").exists():
        for line in (w / "proposals.jsonl").read_text().splitlines()[-30:]:
            if line.strip():
                try:
                    out["proposals"].append(json.loads(line))
                except Exception:
                    pass
    recs = w / "records.jsonl"
    if recs.exists():
        by_mode, models = {}, {}
        first = last = None
        n = 0
        for line in recs.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            n += 1
            by_mode[r.get("mode", "?")] = by_mode.get(r.get("mode", "?"), 0) + 1
            m = r.get("model") or "unattributed"
            models[m] = models.get(m, 0) + 1
            ts = str(r.get("ts", ""))
            first = first or ts
            last = ts
            out["last_run"] = ts
        out["corpus"] = {"total": n, "by_mode": by_mode, "models": models,
                         "first": first, "last": last}
    # lifecycle control-plane panel (read straight from the registry file —
    # no cache, per the audit gate)
    from strategies.expert_lifecycle import lifecycle_of, active_lanes
    reg = json.loads((Path(__file__).resolve().parent / "data" / "epoch_registry.json").read_text())
    experts = []
    for e in reg.get("experts", []):
        eid = e["expert_id"]
        acc = e.get("accrual") or {}
        experts.append({
            "expert_id": eid,
            "lifecycle": e.get("lifecycle", "candidate"),
            "notional_cap": e.get("notional_cap", 1.0),
            "lifecycle_reason": e.get("lifecycle_reason"),
            "closed_trades": acc.get("closed_trades"),
            "active": eid in active_lanes(),
        })
    out["lifecycle_panel"] = experts
    # authoritative: the last STAMPED warden record (what actually produced
    # the notes) — the live probe races the busy server and flaked to None
    out["model_current"] = None
    if notes:
        out["model_current"] = notes[-1].get("model")
    try:
        with urllib.request.urlopen("http://127.0.0.1:5802/v1/models", timeout=5) as r:
            d = json.loads(r.read())
        live = (d.get("data") or [{}])[0].get("id")
        if live and not out["model_current"]:
            out["model_current"] = live
        out["model_live"] = live
    except Exception:
        out["model_live"] = None
    return {"warden": out, "generated": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/")
async def root():
    """Redirect to dashboard HTML."""
    return HTMLResponse(
        content=DASHBOARD_HTML,
        status_code=200,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


_PWA = Path(__file__).resolve().parent / "pwa"


@app.get("/manifest.webmanifest")
async def pwa_manifest():
    return FileResponse(_PWA / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def pwa_sw():
    return FileResponse(_PWA / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/icon-192.png")
async def pwa_icon_192():
    return FileResponse(_PWA / "icon-192.png", media_type="image/png")


@app.get("/icon-512.png")
async def pwa_icon_512():
    return FileResponse(_PWA / "icon-512.png", media_type="image/png")


@app.get("/health")
async def health():
    s = _read_state()
    return {
        "status": "ok",
        "cycle": s.get("cycle", 0),
        "cash": s.get("cash", 0),
        "portfolio_value": s.get("portfolio_value", 0),
        "initial_cash": s.get("initial_cash", 100_000),
        "positions": len(s.get("positions", [])),
        "drawdown_pct": s.get("metrics", {}).get("drawdown_pct", 0),
        "model_available": s.get("models", {}).get("llama_available", False),
        "debate_model": s.get("models", {}).get("debate_model", ""),
        "data_mode": s.get("data_provenance", {}).get("mode", "unknown"),
        "exchange": s.get("data_provenance", {}).get("exchange", ""),
    }


@app.get("/pva")
async def pva(points: int = Query(500, ge=10, le=5000)):
    return _build_pva(num_points=points)


@app.get("/state")
async def state_full():
    return _read_state()


@app.get("/api/history-summary")
async def history_summary():
    """Return recent summary rows for the dashboard table."""
    files = _list_history_files()[:50]  # newest 50 snapshots
    rows = []
    for fpath in files:
        try:
            d = json.loads(fpath.read_text())
        except Exception:
            continue
        rows.append(
            {
                "ts": str(d.get("timestamp", ""))[:19],
                "cycle": d.get("cycle", 0),
                "portfolio": d.get("portfolio_value", 0),
                "cash": d.get("cash", 0),
                "positions": len(d.get("positions", [])),
                "pnl_pct": round(
                    (d.get("portfolio_value", 0) / max(d.get("initial_cash", 1), 1) - 1)
                    * 100,
                    2,
                ),
            }
        )
    return {"rows": rows[-30:], "count": len(rows[-30:])}


@app.get("/api/positions")
async def api_positions():
    """Return current positions with P&L detail."""
    s = _read_state()
    positions = []
    for p in s.get("positions", []):
        qty = p.get("quantity", 0) or 0
        entry = p.get("entry_price") or 0
        current = p.get("current_price", 0) or 0
        value = qty * current
        cost = qty * entry
        pnl = (current - entry) / max(entry, 0.01) * 100 if entry else 0
        positions.append(
            {
                "symbol": p.get("symbol", "?"),
                "quantity": round(qty, 6),
                "entry_price": entry,
                "current_price": current,
                "value": round(value, 2),
                "pnl_pct": round(pnl, 2),
                "stop_loss": p.get("stop_loss"),
                "take_profit": p.get("take_profit"),
                "cycle_opened": p.get("cycle_opened"),
            }
        )
    return {"positions": positions, "count": len(positions)}


@app.get("/api/trades")
async def api_trades():
    s = _read_state()
    trades = s.get("trades", [])
    return {
        "trades": trades[-30:],
        "count": len(trades),
        "total_pnl": round(sum(t.get("pnl_dollar", 0) or 0 for t in trades), 2),
    }


@app.get("/api/regimes")
async def api_regimes():
    s = _read_state()
    regimes = s.get("symbol_regimes", {})
    result = {}
    for sym, data in regimes.items():
        result[sym] = {
            "regime": data.get("regime", "unknown"),
            "confidence": data.get("confidence", 0),
            "thesis": data.get("thesis", "")[:120],
            "price": data.get("price", 0),
        }
    return {"regimes": result}


@app.get("/api/benchmark")
async def api_benchmark():
    s = _read_state()
    return s.get("hodl_benchmark", {})


@app.get("/api/trade-status")
async def api_trade_status():
    """Why am I / am I not trading. Reads paper_state + live_router_state."""
    import json as _json
    from pathlib import Path as _Path

    s = _read_state()
    cash = s.get("cash", 0)
    pv = s.get("portfolio_value", cash)
    positions = len(s.get("positions", []))
    cycle = s.get("cycle", 0)

    # fills from metrics if present
    m = s.get("metrics", {})
    fills = m.get("fills_total", m.get("trades_total", 0))

    # router pick
    ROUTER_STATE = _Path(__file__).resolve().parent / "data" / "live_router_state.json"
    router = {}
    if ROUTER_STATE.exists():
        try:
            router = _json.loads(ROUTER_STATE.read_text())
        except Exception:
            router = {}
    weights = router.get("weights", {})
    track = router.get("track", {})
    def _pick(regime):
        t = track.get(regime, {})
        best, best_imp = "rule", t.get("rule", {}).get("sum", 0.0)
        for e, rec in t.items():
            if e == "rule":
                continue
            n = rec.get("n", 0)
            imp = rec.get("sum", 0.0) / n if n else 0.0
            w = weights.get(regime, {}).get(e, 0.0)
            if n >= 5 and w > 0 and imp > best_imp:
                best, best_imp = e, imp
        return best
    pick_up = _pick("up")

    # status classification
    if fills > 0:
        status, title = "trading", f"TRADING — {fills} fill(s) · cycle {cycle}"
    elif positions > 0:
        status, title = "trading", f"HOLDING {positions} position(s) · cycle {cycle}"
    else:
        status, title = "idle", f"IDLE — 0 fills · cycle {cycle}"

    return {
        "status": status,
        "title": title,
        "cash": cash,
        "pv": pv,
        "positions": positions,
        "cycle": cycle,
        "fills": fills,
        "pick_up": pick_up,
        "mode": "rule-primary",
        "note": ("Router pick=" + str(pick_up) +
                 " (verified expert) is NOT the live trader: harness runs "
                 "rule-primary, which trades the iter-74 rule and bypasses the "
                 "verified experts. 0 fills because no symbol's rule score "
                 "clears buy_thresh in the current market."),
    }


@app.get("/api/lanes")
async def api_lanes():
    """Paper lane state — one avenue per verified expert."""
    import json as _json
    from pathlib import Path as _Path
    p = _Path(__file__).resolve().parent / "data" / "lanes_state.json"
    if not p.exists():
        return {"lanes": {}, "note": "lanes not yet run"}
    try:
        return _json.loads(p.read_text())
    except Exception:
        return {"lanes": {}, "note": "lanes state unreadable"}


@app.get("/api/expert-router")
async def api_expert_router():
    """Arena self-evolution view: verified experts, weight schedule, current
    picks, and live router state. Read-only monitoring of the MoT layer."""
    import json as _json
    from pathlib import Path as _Path

    ROUTER_STATE = _Path(__file__).resolve().parent / "data" / "live_router_state.json"
    router = {}
    if ROUTER_STATE.exists():
        try:
            router = _json.loads(ROUTER_STATE.read_text())
        except Exception:
            router = {}

    experts = []
    experts_error = ""
    try:
        from strategies.experts import VERIFIED
        for name, v in sorted(VERIFIED.items(),
                              key=lambda kv: -kv[1].oos_calmar):
            experts.append({
                "name": name,
                "oos_calmar": v.oos_calmar,
                "oos_sharpe": v.oos_sharpe,
                "maxdd": v.maxdd,
                "description": v.description,
            })
    except Exception as e:
        # Registry unavailable (e.g. swarm data missing): return an EMPTY list,
        # never an error-dict entry — the dashboard graph renders nodes from
        # router weights instead and flags the registry in er-note.
        experts_error = str(e)

    # weight schedule + picks from the router state (regime keys up/down)
    weights = router.get("weights", {})
    track = router.get("track", {})

    def _pick(regime: str) -> str:
        t = track.get(regime, {})
        best, best_imp = "rule", t.get("rule", {}).get("sum", 0.0)
        for e, rec in t.items():
            if e == "rule":
                continue
            n = rec.get("n", 0)
            imp = rec.get("sum", 0.0) / n if n else 0.0
            w = weights.get(regime, {}).get(e, 0.0)
            if n >= 5 and w > 0 and imp > best_imp:
                best, best_imp = e, imp
        return best

    return {
        "experts": experts,
        "experts_error": experts_error,
        "weights": weights,
        "picks": {"up": _pick("up"), "down": _pick("down")},
        "note": router.get("note", ""),
        "status": "MONITORING — not live order flow",
    }


@app.get("/stream")
async def stream(request: Request):
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            s = _read_state()
            metrics = s.get("metrics", {})
            summary = {
                "cycle": s.get("cycle", 0),
                "pv": s.get("portfolio_value", 0),
                "cash": s.get("cash", 0),
                "pnl_pct": round(
                    (
                        s.get("portfolio_value", 0)
                        / max(s.get("initial_cash", 100_000), 1)
                        - 1
                    )
                    * 100,
                    2,
                ),
                "positions": len(s.get("positions", [])),
                "dd": metrics.get("drawdown_pct", 0),
                "fg": metrics.get("fear_greed", {}),
                "ts": str(s.get("timestamp", ""))[:19],
                "peak": metrics.get("peak_value", 0),
                "stage": metrics.get("stage", 0),
            }
            yield f"data: {json.dumps(summary)}\n\n"
            await asyncio.sleep(3)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Simple HTML Dashboard ──────────────────────────────────────────────
DASHBOARD_HTML = (Path(__file__).parent / "dashboard.html").read_text()

# ── Main ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenTrader Dashboard")
    parser.add_argument(
        "--port", type=int, default=8097, help="Port to listen on (default: 8097)"
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1 — loopback only; 0.0.0.0 would expose the book to the network)"
    )
    args = parser.parse_args()

    print(f"OpenTrader Dashboard starting on http://{args.host}:{args.port}")
    # Pre-warm FX cache immediately on startup so the dashboard is ready
    # by the time the human's TUI first polls. The background thread runs
    # concurrently with uvicorn; cold-requests still get the warming payload.
    if not _FX_REFRESHING["t"]:
        _FX_REFRESHING["t"] = True
        import threading as _threading
        _threading.Thread(target=_refresh_fx_cache, daemon=True).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


# ---------------------------------------------------------------------------
# Agent Lifecycle Registry API (context: agent-registry)
# ---------------------------------------------------------------------------
from collections import defaultdict as _dd


@app.get("/api/registry/agents")
async def api_registry_agents():
    """Per-agent lifecycle registry: gate verdicts, overrides, drift, cycles."""
    try:
        from strategies.expert_lifecycle import all_lifecycles, REGISTRY as LC_REGISTRY
        lc = all_lifecycles()
        agents = _dd(lambda: {"lifecycle": {}, "gates": [], "overrides": [], "cycles": []})
        for eid, state in lc.items():
            agents[eid]["lifecycle"] = {"expert_id": eid, "lifecycle": state}
        reg_raw = json.loads(LC_REGISTRY.read_text()) if LC_REGISTRY.exists() else {"experts": []}
        for e in reg_raw.get("experts", []):
            eid = e.get("expert_id", "?")
            if eid in agents:
                agents[eid]["lifecycle"].update({
                    "status": e.get("status"),
                    "registered": e.get("registered"),
                    "kind": e.get("kind"),
                    "notional_cap": e.get("notional_cap", 1.0),
                    "lifecycle_reason": e.get("lifecycle_reason"),
                })
        out = []
        for name, d in sorted(agents.items()):
            gates = d["gates"]
            out.append({
                "agent": name,
                "total_gates": len(gates),
                "total_overrides": len(d["overrides"]),
                "pass_rate": (
                    sum(1 for g in gates if g.get("verdict") == "PASS") / len(gates)
                    if gates else None
                ),
                "last_gate": gates[0] if gates else None,
                "recent_gates": gates[:20],
                "recent_overrides": d["overrides"][:10],
                "cycles": d["cycles"][:10],
            })
        return {"agents": out, "count": len(out)}
    except Exception as exc:
        return {"agents": [], "count": 0, "error": str(exc)}


@app.get("/api/registry/summary")
async def api_registry_summary():
    """Rolling summary for the dashboard header strip."""
    try:
        from strategies.expert_lifecycle import all_lifecycles
        lc = all_lifecycles()
        by_agent = {}
        for eid, state in lc.items():
            by_agent[eid] = {"lifecycle": state}
        return {"agents": by_agent, "recent_gates": [], "recent_overrides": []}
    except Exception as exc:
        return {"agents": {}, "recent_gates": [], "recent_overrides": [],
                "error": str(exc)}
