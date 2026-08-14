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


@app.get("/")
async def root():
    """Redirect to dashboard HTML."""
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)


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
        experts = [{"error": str(e)}]

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
