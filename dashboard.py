#!/usr/bin/env python3
"""OpenTrader Web Dashboard — REST API + simple HTML UI on port 8097.

Replaces the broken PVA-only helper. Serves portfolio state, PVA history,
and a lightweight dashboard page. Run: python3 dashboard.py --port 8097
"""

import argparse
import asyncio
import json
import logging
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("opentrader.dashboard")

PROJECT = str(Path(__file__).resolve().parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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
    TUIs) never block on OANDA latency and never trigger concurrent refreshes."""
    import threading
    import time as _time
    if _FX_CACHE["data"] is not None:
        if _time.time() - _FX_CACHE["ts"] >= 30 and not _FX_REFRESHING["t"]:
            _FX_REFRESHING["t"] = True
            threading.Thread(target=_refresh_fx_cache, daemon=True).start()
        out = dict(_FX_CACHE["data"])
        out["flat"] = _flat_reasons()  # reasons have their own 300s TTL
        return out
    out = _compute_fx()  # cold path: compute synchronously once, cache, serve
    _FX_CACHE["ts"] = _time.time()
    _FX_CACHE["data"] = {k: v for k, v in out.items()}
    return out
def _compute_fx() -> dict:
    import time as _time
    out = {"book": [], "fills": [], "registry": [], "queue": {}, "error": None}
    try:
        from exchange.oanda import OandaExchange
        ex = OandaExchange()
        if ex.connect():
            book = ex._request("GET", f"/v3/accounts/{ex._account_id}/openTrades").get("trades", [])
            for t in book:
                out["book"].append({
                    "trade_id": t.get("id"), "instrument": t.get("instrument"),
                    "units": t.get("currentUnits"), "price": t.get("price"),
                    "opened": str(t.get("openTime", ""))[:19],
                    "owner": (t.get("clientExtensions") or {}).get("tag") or "unknown",
                    "pl": t.get("unrealizedPL"),
                    "protected": bool(t.get("stopLossOrder") or t.get("takeProfitOrder")),
                })
            acct = ex._request("GET", f"/v3/accounts/{ex._account_id}")["account"]
            out["balance"] = acct.get("balance")
            out["nav"] = acct.get("NAV")
            out["_ex"] = ex
        else:
            out["error"] = "OANDA connect failed"
    except Exception as e:
        out["error"] = str(e)
    ledger = DATA / "fx_ledger.jsonl"
    if ledger.exists():
        rows = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
        out["fills"] = rows[-25:][::-1]
    reg = DATA / "epoch_registry.json"
    if reg.exists():
        out["registry"] = json.loads(reg.read_text()).get("experts", [])
    try:
        from strategies.fx_review import load_events, load_labels
        out["queue"] = {"events": len(load_events()), "labeled": len(load_labels())}
    except Exception:
        pass
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
    rows.append('<h2>Open book (by owner tag)</h2><table><tr><th>trade</th><th>instrument</th>'
                '<th>units</th><th>entry</th><th>opened (UTC)</th><th>owner</th><th>unrealized</th>'
                '<th>SL/TP</th></tr>')
    if not s["book"]:
        rows.append('<tr><td colspan="8" class="dim">flat</td></tr>')
    for t in s["book"]:
        prot = '<span class="ok">yes</span>' if t["protected"] else '<span class="err">NO</span>'
        pl = float(t["pl"] or 0)
        rows.append(f"<tr><td>{t['trade_id']}</td><td>{t['instrument']}</td>"
                    f"<td class='num'>{t['units']}</td><td class='num'>{t['price']}</td>"
                    f"<td>{t['opened']}</td><td>{t['owner']}</td>"
                    f"<td class='num'>{pl:+.2f}</td><td>{prot}</td></tr>")
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
FF_CACHE = DATA / "cache" / "ff_calendar.json"


def _ff_events():
    """Analyst-consensus calendar (ForexFactory community feed), 6h file cache."""
    import time as _time
    try:
        if FF_CACHE.exists() and _time.time() - FF_CACHE.stat().st_mtime < 6 * 3600:
            return json.loads(FF_CACHE.read_text())
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(FF_FEED, headers={"User-Agent": "OpenTrader/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            events = json.load(r)
        FF_CACHE.parent.mkdir(parents=True, exist_ok=True)
        FF_CACHE.write_text(json.dumps(events))
        return events
    except Exception:
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
    return _fx_snapshot()


@app.get("/")
async def root():
    """Redirect to dashboard HTML."""
    return HTMLResponse(
        content=DASHBOARD_HTML,
        status_code=200,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


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
        "--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)"
    )
    args = parser.parse_args()

    print(f"OpenTrader Dashboard starting on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
