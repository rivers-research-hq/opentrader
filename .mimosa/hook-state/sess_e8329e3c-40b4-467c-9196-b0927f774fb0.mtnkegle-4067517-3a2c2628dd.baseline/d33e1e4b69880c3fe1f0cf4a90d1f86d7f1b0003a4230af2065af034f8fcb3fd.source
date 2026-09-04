#!/usr/bin/env python3
"""OpenTrader MCP Server — trading tools via Model Context Protocol.

The model calls tools instead of the harness calling the model.
MCP protocol (streamable HTTP) + REST API for harness integration.

Usage:
    python3 mcp_server.py                        # default :8092
    python3 mcp_server.py --port 8092 --exchange paper
"""
import argparse
import json
import logging
import os
import sys
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Ensure project root is on path ──
PROJECT = str(Path(__file__).resolve().parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from exchange.base import ExchangeBase, OHLCV, OrderResult, Balance, get_exchange, list_exchanges
from exchange.paper import PaperExchange
from risk.manager import RiskManager, RiskConfig, RiskResult
from state.manager import StateManager
from mot.adapter_registry import AdapterRegistry
from mot.dynamic_discovery import refresh_from_exchange, get_sector_list

logger = logging.getLogger("opentrader.mcp")

# ── Global state (shared across MCP tools) ──
_exchange: ExchangeBase = None
_risk: RiskManager = None
_state_mgr: StateManager = None
_cycle: int = 0
_models_meta: dict = {}
_fills: List[dict] = []
_registry: AdapterRegistry = None
_state_dir: str = None
_args = None  # populated by main()


def init_globals(exchange_name: str = "paper", exchange_config: dict = None,
                 risk_config: RiskConfig = None, state_dir: str = None,
                 initial_cash: float = 100_000, models_meta: dict = None):
    """Initialize shared state for all MCP tools."""
    global _exchange, _risk, _state_mgr, _models_meta, _fills, _registry, _state_dir
    if exchange_name == "paper":
        _exchange = PaperExchange(config={"initial_cash": initial_cash})
    else:
        _exchange = get_exchange(exchange_name, exchange_config or {})
        if _exchange is None:
            raise ValueError(f"Unknown exchange: {exchange_name}")
    _exchange.connect()
    _risk = RiskManager(risk_config or RiskConfig())
    bal = _exchange.get_balance()
    _risk.set_initial(bal.cash)
    _state_mgr = StateManager(state_dir)
    _state_dir = state_dir
    try:
        _registry = AdapterRegistry(state_dir)
    except Exception as e:
        logger.warning(f"Could not init adapter registry: {e}")
        _registry = None
    _models_meta = models_meta or {}
    _fills = []
    logger.info(f"OpenTrader MCP initialized: {exchange_name}, cash=${bal.cash:,.2f}")
    _load_cycle()


def _load_cycle() -> None:
    """Load cycle counter from persisted state to survive restarts."""
    global _cycle
    try:
        state_path = Path(_state_mgr.state_dir) / "paper_state.json"
        if state_path.exists():
            data = json.loads(state_path.read_text())
            _cycle = data.get("cycle", 0)
            logger.info(f"Loaded cycle {_cycle} from state")
    except Exception as e:
        logger.warning(f"Could not load cycle from state: {e}")


def get_exchange_instance():
    return _exchange

def get_risk_instance():
    return _risk

def get_state_manager():
    return _state_mgr


# =======================================================================
# Tool implementations (used by both MCP and REST API)
# =======================================================================

def tool_get_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 50) -> str:
    """Fetch OHLCV bars for a symbol.

    Args:
        symbol: Trading pair (e.g. BTC/USDT, ETH/USDT)
        timeframe: Bar timeframe (1m, 5m, 15m, 1h, 4h, 1d)
        limit: Number of bars to return (max 200)
    Returns:
        JSON string with OHLCV data
    """
    global _exchange
    if _exchange is None:
        return json.dumps({"error": "exchange not initialized", "bars": []})
    try:
        bars = _exchange.get_bars(symbol, timeframe, min(limit, 200))
        if not bars:
            return json.dumps({"symbol": symbol, "bars": [], "count": 0})
        result = {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(bars),
            "bars": [b.to_dict() for b in bars],
            "current_price": bars[-1].close,
        }
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "bars": []})


def tool_submit_order(symbol: str, side: str, quantity: float = 0,
                      order_type: str = "market", price: float = None,
                      confidence: float = 0.5, reason: str = "",
                      position_pct: float = None,
                      stop_loss: float = None, take_profit: float = None) -> str:
    """Submit a trading order.

    Goes through risk gate before execution.
    Uses position_pct for risk-based sizing if provided; otherwise uses quantity directly.
    
    Args:
        symbol: Trading pair
        side: BUY or SELL
        quantity: Amount to trade (used directly if position_pct not given)
        order_type: market or limit
        price: Limit price (required for limit orders)
        confidence: Signal confidence 0.0-1.0
        reason: Reason for the trade
        position_pct: Fraction of portfolio to risk (0.0-0.2). If set, overrides quantity.
        stop_loss: Stop loss price level
        take_profit: Take profit price level
    Returns:
        JSON string with order result
    """
    global _exchange, _risk, _fills, _cycle
    if _exchange is None:
        return json.dumps({"status": "error", "error": "exchange not initialized"})
    try:
        # Build a signal-like object for risk check
        class _Signal:
            pass
        sig = _Signal()
        sig.symbol = symbol
        sig.action = side.upper()
        sig.position_pct = position_pct if position_pct is not None else 0.05
        sig.stop_loss = stop_loss
        sig.take_profit = take_profit
        sig.confidence = min(1.0, max(0.0, confidence))
        sig.reason = reason

        # Get portfolio state
        bal = _exchange.get_balance()
        prices = {symbol: _exchange.get_current_price(symbol) or 0}
        positions = {k: float(v) for k, v in (bal.positions or {}).items()}
        portfolio = {"total_value": bal.total_value, "cash": bal.cash, "positions": positions}

        # Risk gate
        result = _risk.check(sig, portfolio, prices, current_positions=positions)
        if not result.approved:
            return json.dumps({
                "status": "rejected", "error": result.reason,
                "order_id": None, "symbol": symbol, "side": side, "quantity": quantity,
            })

        # Compute quantity: position_pct-based sizing, fall back to explicit quantity
        if position_pct is not None or quantity <= 0:
            qty = (result.adjusted_size * bal.total_value) / max(prices.get(symbol, 1), 1)
        else:
            qty = quantity

        final_qty = qty

        if final_qty <= 0:
            return json.dumps({
                "status": "rejected", "error": "zero quantity after risk sizing",
                "adjusted": result.adjusted_size, "total_value": bal.total_value,
            })

        order = _exchange.place_order(symbol, side.upper(), round(final_qty, 8), order_type, price)
        fill = {
            "order_id": order.order_id, "symbol": order.symbol,
            "side": order.side, "quantity": order.quantity,
            "price": order.price, "status": order.status,
            "timestamp": order.timestamp,
            "signal_confidence": result.adjusted_size,
            "signal_reason": reason,
            "stop_loss": result.adjusted_stop,
            "take_profit": result.adjusted_tp,
            "cycle": _cycle,
        }
        _fills.append(fill)

        return json.dumps({
            "status": order.status,
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": order.price,
            "stop_loss": result.adjusted_stop,
            "take_profit": result.adjusted_tp,
            "reason": reason,
            "position_pct": sig.position_pct,
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_get_portfolio() -> str:
    """Get current portfolio state: cash, positions, total value, P&L."""
    global _exchange
    if _exchange is None:
        return json.dumps({"error": "exchange not initialized"})
    try:
        bal = _exchange.get_balance()
        return json.dumps({
            "cash": bal.cash,
            "total_value": bal.total_value,
            "positions": bal.positions,
            "position_count": len(bal.positions),
            "fills_count": len(_fills),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def tool_get_regime(symbol: str = "BTC/USDT") -> str:
    """Analyze current market regime using SLM statistical classifier.

    Uses ADX, Bollinger Bands, MA slope, volume analysis, and price structure
    to classify market as: trending_up, trending_down, ranging, volatile, bearish.
    """
    global _exchange
    if _exchange is None:
        return json.dumps({"regime": "unknown", "confidence": 0, "thesis": "no exchange"})
    try:
        from data.regime_classifier import classify_regime, format_regime_for_prompt
        bars = _exchange.get_bars(symbol, timeframe="1h", limit=80)
        if not bars:
            return json.dumps({"regime": "unknown", "confidence": 0, "thesis": "no data"})
        result = classify_regime([b.to_dict() for b in bars])
        if result.get("regime") == "insufficient_data":
            result["symbol"] = symbol
            return json.dumps(result)
        result["symbol"] = symbol
        return json.dumps(result)
    except ImportError:
        # Fallback if regime_classifier not available
        return _tool_get_regime_fallback(symbol)
    except Exception as e:
        return json.dumps({"regime": "error", "confidence": 0, "thesis": str(e)})


def _tool_get_regime_fallback(symbol: str = "BTC/USDT") -> str:
    """Simple fallback regime when classifier module not available."""
    global _exchange
    try:
        bars = _exchange.get_bars(symbol, timeframe="1h", limit=40)
        if not bars:
            return json.dumps({"regime": "unknown", "confidence": 0, "thesis": "no data"})
        closes = [b.close for b in bars[-20:]]
        first, last = closes[0], closes[-1]
        pct = (last - first) / first if first else 0
        if pct > 0.03:
            regime, conf = "trending_up", min(0.85, 0.5 + pct * 5)
        elif pct < -0.03:
            regime, conf = "bearish", min(0.85, 0.5 + abs(pct) * 5)
        else:
            regime, conf = "ranging", 0.6
        return json.dumps({
            "regime": regime, "confidence": round(conf, 2),
            "thesis": f"fallback: price {pct:+.1%}",
            "symbol": symbol, "price": last,
        })
    except Exception as e:
        return json.dumps({"regime": "error", "confidence": 0, "thesis": str(e)})


def tool_get_economics() -> str:
    """Fetch economic indicators (FRED → cache → simulated fallback)."""
    try:
        from data.economics import fetch_economics
        result = fetch_economics()
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"source": "error", "error": str(e)})


def tool_render_chart(chart_type: str = "candles", symbol: str = "BTC/USDT") -> str:
    """Generate a trading chart and return the file path.
    
    Args:
        chart_type: candles, portfolio, regime, dashboard
        symbol: Trading pair
    Returns:
        JSON with chart file path
    """
    global _exchange
    if _exchange is None:
        return json.dumps({"error": "exchange not initialized"})
    try:
        from charts.renderer import render_candlestick, render_dashboard
        bars = _exchange.get_bars(symbol, limit=100)
        if not bars:
            return json.dumps({"error": "no bars to chart"})
        out_dir = Path(__file__).resolve().parent / "data" / "charts"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if chart_type == "candles":
            path = render_candlestick(bars, symbol, output_dir=str(out_dir))
        else:
            path = render_dashboard([100000], [], bars, output_dir=str(out_dir))
        return json.dumps({"chart_type": chart_type, "file": str(path)})
    except ImportError:
        return json.dumps({"error": "chart renderer not available", "chart_type": chart_type})
    except Exception as e:
        return json.dumps({"error": str(e), "chart_type": chart_type})


def record_cycle(market_data: dict = None, signals: list = None) -> dict:
    """Record a cycle's state to disk."""
    global _exchange, _risk, _state_mgr, _cycle, _fills, _models_meta
    _cycle += 1
    bal = _exchange.get_balance()
    prices = {}
    for sym in list(bal.positions.keys()):
        p = _exchange.get_current_price(sym)
        if p:
            prices[sym] = p
    positions_list = [
        {"symbol": sym, "quantity": round(float(qty), 8), "current_price": prices.get(sym, 0)}
        for sym, qty in (bal.positions or {}).items() if float(qty) > 0
    ]
    _risk.update_peak(bal.total_value)
    state = _state_mgr.write(
        cycle=_cycle, portfolio={"cash": bal.cash, "total_value": bal.total_value,
                                  "positions": bal.positions or {}},
        positions=positions_list, fills=_fills, prices=prices,
        regime=market_data.get("regime") if market_data else None,
        signals=signals, models=_models_meta,
        metrics={"cycle_time_s": 0},
    )
    hl_regime = (market_data.get("regime") or {}) if market_data else {}
    _state_mgr.write_high_level(
        regime=hl_regime.get("regime", "unknown"),
        confidence=hl_regime.get("confidence", 0),
        thesis=hl_regime.get("thesis", ""),
        available=True, models=_models_meta,
    )
    return state


# =======================================================================
# Cartographer MCP Tools
# =======================================================================

def tool_adapter_list() -> str:
    """List all registered adapters."""
    global _registry
    if _registry is None:
        return json.dumps({"adapters": [], "error": "registry not available"})
    try:
        data = _registry.get_adapter_for_dashboard()
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"adapters": [], "error": str(e)})


def tool_adapter_register(version: str, path: str, training_score: float = 0.0,
                          training_cycles: int = 0, training_examples: int = 0,
                          previous_version: str = "") -> str:
    """Register a new trained adapter."""
    global _registry
    if _registry is None:
        return json.dumps({"status": "error", "error": "registry not available"})
    if not version or not path:
        return json.dumps({"status": "error", "error": "version and path are required"})
    try:
        record = _registry.register(version, path, training_score, training_cycles, training_examples, previous_version)
        return json.dumps({"status": "ok", "version": record.version, "path": record.path})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_adapter_promote(version: str) -> str:
    """Promote an adapter to active."""
    global _registry
    if _registry is None:
        return json.dumps({"status": "error", "error": "registry not available"})
    try:
        record = _registry.promote(version)
        if record is None:
            return json.dumps({"status": "error", "error": f"adapter '{version}' not found"})
        return json.dumps({"status": "ok", "version": record.version, "adapter_status": record.status})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_adapter_rollback(version: str, reason: str = "performance regression") -> str:
    """Rollback to a previous adapter version."""
    global _registry
    if _registry is None:
        return json.dumps({"status": "error", "error": "registry not available"})
    try:
        record = _registry.rollback(version, reason)
        if record is None:
            return json.dumps({"status": "error", "error": f"adapter '{version}' not found"})
        return json.dumps({"status": "ok", "version": record.version, "status": record.status, "reason": reason})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_training_queue(version: str, base_model: str = "Qwen/Qwen2.5-7B-Instruct",
                        dataset_path: str = "", method: str = "qlora",
                        epochs: int = 3, lora_r: int = 16,
                        lora_alpha: int = 16, notes: str = "") -> str:
    """Queue a training job by writing a training objective file."""
    global _state_dir
    if _state_dir is None:
        return json.dumps({"status": "error", "error": "state_dir not available"})
    try:
        obj_dir = Path(_state_dir) / "training" / "objectives"
        obj_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        default_data = "data/training/dpo_training_data.jsonl" if method == "dpo" else "data/training/training_data_current.jsonl"
        obj = {
            "version": version,
            "base_model": base_model,
            "dataset_path": dataset_path or default_data,
            "method": method,
            "epochs": epochs,
            "lora_r": lora_r,
            "lora_alpha": lora_alpha,
            "notes": notes,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "status": "queued",
        }
        path = obj_dir / f"{version}_{ts}.json"
        path.write_text(json.dumps(obj, indent=2))
        logger.info(f"Training objective queued: {path}")
        return json.dumps({"status": "queued", "version": version, "objective_file": str(path)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_training_status() -> str:
    """Check current training job status."""
    global _state_dir
    if _state_dir is None:
        return json.dumps({"status": "unknown", "error": "state_dir not available"})
    try:
        finetune_path = Path(_state_dir) / "training" / "finetune_status.json"
        dpo_path = Path(_state_dir) / "training" / "dpo_status.json"
        if finetune_path.exists():
            data = json.loads(finetune_path.read_text())
            data["training_type"] = "sft"
        elif dpo_path.exists():
            data = json.loads(dpo_path.read_text())
            data["training_type"] = "dpo"
        else:
            return json.dumps({"status": "idle", "message": "no training status found"})
        lock_path = Path(_state_dir) / "training.lock"
        data["lock_active"] = lock_path.exists()
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_eval_run(version: str, benchmark: str = "traderbench") -> str:
    """Queue an evaluation run for a specific adapter version."""
    global _state_dir
    if _state_dir is None:
        return json.dumps({"status": "error", "error": "state_dir not available"})
    try:
        eval_dir = Path(_state_dir) / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        req = {
            "version": version,
            "benchmark": benchmark,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "status": "queued",
        }
        path = eval_dir / f"eval_{version}_{ts}.json"
        path.write_text(json.dumps(req, indent=2))
        return json.dumps({"status": "queued", "version": version, "request_file": str(path)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_metrics_snapshot() -> str:
    """Get current metrics snapshot from paper state."""
    global _exchange, _cycle
    if _exchange is None:
        return json.dumps({"error": "exchange not initialized"})
    try:
        bal = _exchange.get_balance()
        prices = {}
        for sym in list(bal.positions.keys()):
            p = _exchange.get_current_price(sym)
            if p:
                prices[sym] = p
        return json.dumps({
            "cycle": _cycle,
            "cash": bal.cash,
            "total_value": bal.total_value,
            "position_count": len(bal.positions),
            "open_positions": {k: {"qty": float(v), "price": prices.get(k, 0)} for k, v in (bal.positions or {}).items() if float(v) > 0},
            "fills_count": len(_fills),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def tool_harness_pause(reason: str = "") -> str:
    """Pause the harness by creating a pause flag file."""
    global _state_dir
    if _state_dir is None:
        return json.dumps({"status": "error", "error": "state_dir not available"})
    try:
        pause_path = Path(_state_dir) / ".harness_paused"
        data = {"paused_at": datetime.now(timezone.utc).isoformat(), "reason": reason}
        pause_path.write_text(json.dumps(data, indent=2))
        logger.info(f"Harness paused: {reason}")
        return json.dumps({"status": "paused", "reason": reason})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_harness_resume() -> str:
    """Resume the harness by removing the pause flag."""
    global _state_dir
    if _state_dir is None:
        return json.dumps({"status": "error", "error": "state_dir not available"})
    try:
        pause_path = Path(_state_dir) / ".harness_paused"
        if not pause_path.exists():
            return json.dumps({"status": "already_running", "message": "harness was not paused"})
        pause_path.unlink()
        logger.info("Harness resumed")
        return json.dumps({"status": "resumed"})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def tool_research_idle_check() -> str:
    """Check if research-scout can run (idle conditions met)."""
    global _state_dir, _exchange, _cycle
    try:
        state = {"can_run": True, "reasons": []}
        # Check training lock
        if _state_dir:
            lock_path = Path(_state_dir) / "training.lock"
            if lock_path.exists():
                state["can_run"] = False
                state["reasons"].append("training in progress")
        # Check harness pause
        if _state_dir:
            pause_path = Path(_state_dir) / ".harness_paused"
            if pause_path.exists():
                state["can_run"] = False
                state["reasons"].append("harness is paused")
        # Check recent research manifests
        if _state_dir:
            research_dir = Path(_state_dir) / "research"
            if research_dir.exists():
                existing = list(research_dir.glob("capability_manifest_*.json"))
                state["existing_manifests"] = len(existing)
                if existing:
                    latest = max(existing, key=lambda p: p.stat().st_mtime)
                    state["latest_manifest"] = latest.name
            else:
                state["existing_manifests"] = 0
        state["cycle"] = _cycle
        return json.dumps(state)
    except Exception as e:
        return json.dumps({"can_run": False, "error": str(e)})


def tool_discover_symbols(exchange_name: str = None) -> str:
    """Discover tradable symbols from the current exchange.

    Args:
        exchange_name: Optional exchange type (e.g. "binance", "kraken") to discover from.
                       If omitted, uses the current exchange.

    Returns:
        JSON string with symbols list, count, and available sectors.
    """
    global _exchange
    try:
        universe = refresh_from_exchange(_exchange)
        sectors = get_sector_list()
        result = {
            "symbols": universe,
            "count": len(universe),
            "sectors": sectors,
            "exchange": _exchange.get_name() if _exchange else "none",
        }
        # If a specific exchange name was requested, also try to discover from it
        if exchange_name and exchange_name != (_exchange.get_name() if _exchange else ""):
            try:
                alt = get_exchange(exchange_name.lower())
                if alt:
                    alt.connect()
                    alt_symbols = alt.discover_symbols()
                    result["alt_exchange"] = exchange_name
                    result["alt_symbols"] = alt_symbols
                    result["alt_count"] = len(alt_symbols)
                    alt.disconnect()
            except Exception as e:
                result["alt_error"] = str(e)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "symbols": [], "count": 0, "sectors": "", "exchange": "error"})


def _load_qmath():
    try:
        from tools import qmath
        return qmath
    except Exception:
        import importlib.util as _ilu
        import os as _os
        _p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "tools", "qmath.py")
        _spec = _ilu.spec_from_file_location("qmath", _p)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return _mod


def tool_qmath(op: str, args: dict = None) -> str:
    """Accurate math/quant/stat compute. LLMs are bad at arithmetic — call this
    instead of computing by hand.

    Args:
        op: a qmath operation, e.g. "evaluate", "sharpe_ratio", "black_scholes",
            "var_historical", "cvar", "percentile", "correlation", "beta",
            "ols_regression", "irr", "max_drawdown", "kelly_fraction".
        args: kwargs dict for the op, e.g. {"expr": "(110-100)/100*100"} or
              {"returns": [...], "confidence": 0.95} or {"prices": [...]}.

    Returns:
        JSON: {"op": ..., "result": ...} or {"op": ..., "error": "..."}.
    """
    try:
        qmath = _load_qmath()
        return json.dumps(qmath.run(op, **(args or {})))
    except Exception as e:
        return json.dumps({"op": op, "error": str(e)})


def tool_qmath_ops() -> str:
    """List available qmath operations with their argument signatures."""
    try:
        qmath = _load_qmath()
        return json.dumps({"ops": qmath.list_ops(), "capabilities": qmath.CAPABILITIES})
    except Exception as e:
        return json.dumps({"error": str(e)})


# =======================================================================
# FastAPI App for REST API (harness-friendly)
# =======================================================================

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

rest_app = FastAPI(title="OpenTrader MCP - REST API")
rest_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@rest_app.get("/api/version")
async def api_version():
    return {"version": "opentrader-v0.1.0", "mcp_port": args.port}


@rest_app.get("/api/health")
async def api_health():
    global _exchange
    bal = _exchange.get_balance() if _exchange else None
    return {
        "status": "ok",
        "exchange": _exchange.get_name() if _exchange else "none",
        "connected": _exchange.is_connected() if _exchange else False,
        "cash": bal.cash if bal else 0,
        "total_value": bal.total_value if bal else 0,
        "positions": len(bal.positions) if bal else 0,
        "cycle": _cycle,
    }


@rest_app.get("/api/ohlcv")
async def api_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 50):
    return json.loads(tool_get_ohlcv(symbol, timeframe, limit))


@rest_app.post("/api/order")
async def api_order(body: dict):
    return json.loads(tool_submit_order(
        symbol=body.get("symbol", "BTC/USDT"),
        side=body.get("side", "BUY"),
        quantity=body.get("quantity", 0),
        order_type=body.get("order_type", "market"),
        price=body.get("price"),
        confidence=body.get("confidence", 0.5),
        reason=body.get("reason", ""),
        position_pct=body.get("position_pct"),
        stop_loss=body.get("stop_loss"),
        take_profit=body.get("take_profit"),
    ))


@rest_app.get("/api/portfolio")
async def api_portfolio():
    return json.loads(tool_get_portfolio())


@rest_app.get("/api/regime")
async def api_regime(symbol: str = "BTC/USDT"):
    return json.loads(tool_get_regime(symbol))


@rest_app.get("/api/economics")
async def api_economics():
    return json.loads(tool_get_economics())


@rest_app.get("/api/chart")
async def api_chart(chart_type: str = "candles", symbol: str = "BTC/USDT"):
    return json.loads(tool_render_chart(chart_type, symbol))


@rest_app.get("/api/state")
async def api_state():
    global _state_mgr
    return _state_mgr.read()


@rest_app.get("/api/adapter/list")
async def api_adapter_list():
    return json.loads(tool_adapter_list())


@rest_app.post("/api/adapter/register")
async def api_adapter_register(body: dict):
    return json.loads(tool_adapter_register(
        version=body.get("version", ""),
        path=body.get("path", ""),
        training_score=body.get("training_score", 0.0),
        training_cycles=body.get("training_cycles", 0),
        training_examples=body.get("training_examples", 0),
        previous_version=body.get("previous_version", ""),
    ))


@rest_app.post("/api/adapter/promote")
async def api_adapter_promote(body: dict):
    return json.loads(tool_adapter_promote(version=body.get("version", "")))


@rest_app.post("/api/adapter/rollback")
async def api_adapter_rollback(body: dict):
    return json.loads(tool_adapter_rollback(
        version=body.get("version", ""),
        reason=body.get("reason", "performance regression"),
    ))


@rest_app.post("/api/training/queue")
async def api_training_queue(body: dict):
    return json.loads(tool_training_queue(
        version=body.get("version", ""),
        base_model=body.get("base_model", "Qwen/Qwen2.5-7B-Instruct"),
        dataset_path=body.get("dataset_path", ""),
        method=body.get("method", "qlora"),
        epochs=body.get("epochs", 3),
        lora_r=body.get("lora_r", 16),
        notes=body.get("notes", ""),
    ))


@rest_app.get("/api/training/status")
async def api_training_status():
    return json.loads(tool_training_status())


@rest_app.post("/api/eval/run")
async def api_eval_run(body: dict):
    return json.loads(tool_eval_run(
        version=body.get("version", ""),
        benchmark=body.get("benchmark", "traderbench"),
    ))


@rest_app.get("/api/metrics/snapshot")
async def api_metrics_snapshot():
    return json.loads(tool_metrics_snapshot())


@rest_app.post("/api/harness/pause")
async def api_harness_pause(body: dict):
    return json.loads(tool_harness_pause(reason=body.get("reason", "")))


@rest_app.post("/api/harness/resume")
async def api_harness_resume():
    return json.loads(tool_harness_resume())


@rest_app.get("/api/research/idle_check")
async def api_research_idle_check():
    return json.loads(tool_research_idle_check())


@rest_app.get("/api/discover/symbols")
async def api_discover_symbols(exchange: str = None):
    """Discover tradable symbols from the exchange. Optionally also query a named exchange."""
    return json.loads(tool_discover_symbols(exchange))


@rest_app.get("/api/tools")
async def api_tools():
    """List available tools and their schemas (for harness integration)."""
    return {
        "tools": [
            {
                "name": "get_ohlcv",
                "description": "Fetch OHLCV bars for a symbol",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Trading pair e.g. BTC/USDT"},
                        "timeframe": {"type": "string", "description": "1m, 5m, 15m, 1h, 4h, 1d"},
                        "limit": {"type": "integer", "description": "Number of bars (max 200)"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "submit_order",
                "description": "Place a trading order (goes through risk gate). Use position_pct for risk-based sizing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Trading pair"},
                        "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "Order side"},
                        "quantity": {"type": "number", "description": "Quantity in base currency (used if position_pct not set)"},
                        "order_type": {"type": "string", "enum": ["market", "limit"], "description": "Order type"},
                        "price": {"type": "number", "description": "Limit price (for limit orders)"},
                        "confidence": {"type": "number", "description": "Signal confidence 0-1"},
                        "reason": {"type": "string", "description": "Reason for the trade"},
                        "position_pct": {"type": "number", "description": "Fraction of portfolio to risk (0.0-0.2)"},
                        "stop_loss": {"type": "number", "description": "Stop loss price level"},
                        "take_profit": {"type": "number", "description": "Take profit price level"},
                    },
                    "required": ["symbol", "side"],
                },
            },
            {
                "name": "get_portfolio",
                "description": "Get current portfolio state (cash, positions, P&L)",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_regime",
                "description": "Analyze current market regime",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Trading pair"},
                    },
                },
            },
            {
                "name": "get_economics",
                "description": "Fetch economic indicators",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "render_chart",
                "description": "Generate a trading chart",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {"type": "string", "enum": ["candles", "portfolio", "dashboard"]},
                        "symbol": {"type": "string", "description": "Trading pair"},
                    },
                },
            },
            {
                "name": "adapter_list",
                "description": "List all registered adapters",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "adapter_register",
                "description": "Register a new trained adapter",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "path": {"type": "string"},
                        "training_score": {"type": "number"},
                        "training_cycles": {"type": "integer"},
                        "training_examples": {"type": "integer"},
                        "previous_version": {"type": "string"},
                    },
                    "required": ["version", "path"],
                },
            },
            {
                "name": "adapter_promote",
                "description": "Promote an adapter to active",
                "parameters": {
                    "type": "object",
                    "properties": {"version": {"type": "string"}},
                    "required": ["version"],
                },
            },
            {
                "name": "adapter_rollback",
                "description": "Rollback to a previous adapter version",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["version"],
                },
            },
            {
                "name": "training_queue",
                "description": "Queue a training job",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "base_model": {"type": "string"},
                        "dataset_path": {"type": "string"},
                        "method": {"type": "string"},
                        "epochs": {"type": "integer"},
                        "lora_r": {"type": "integer"},
                        "notes": {"type": "string"},
                    },
                    "required": ["version"],
                },
            },
            {
                "name": "training_status",
                "description": "Check current training job status",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "eval_run",
                "description": "Queue an evaluation run for an adapter",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "version": {"type": "string"},
                        "benchmark": {"type": "string"},
                    },
                    "required": ["version"],
                },
            },
            {
                "name": "metrics_snapshot",
                "description": "Get current metrics snapshot",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "harness_pause",
                "description": "Pause the harness",
                "parameters": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                },
            },
            {
                "name": "harness_resume",
                "description": "Resume the harness",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "research_idle_check",
                "description": "Check if research-scout can run",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "discover_symbols",
                "description": "Discover tradable symbols from the exchange. Optionally query a named exchange for broader universe.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "exchange_name": {"type": "string", "description": "Optional exchange name e.g. binance, kraken, alpaca"},
                    },
                },
            },
        ],
    }


# =======================================================================
# MCP Server (FastMCP)
# =======================================================================

from mcp.server import FastMCP

mcp_server = FastMCP(
    "OpenTrader",
    instructions="OpenTrader MCP Server — trading tools for models to call via function calling.",
    port=8092,
    streamable_http_path="/mcp",
)


@mcp_server.tool()
def get_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 50) -> str:
    """Fetch OHLCV bars for a trading symbol."""
    return tool_get_ohlcv(symbol, timeframe, limit)


@mcp_server.tool()
def submit_order(symbol: str, side: str, quantity: float = 0,
                 order_type: str = "market", price: float = None,
                 confidence: float = 0.5, reason: str = "",
                 position_pct: float = None,
                 stop_loss: float = None, take_profit: float = None) -> str:
    """Place a trading order. Goes through risk gate. Use position_pct for risk-based sizing."""
    return tool_submit_order(symbol, side, quantity, order_type, price,
                             confidence, reason, position_pct, stop_loss, take_profit)


@mcp_server.tool()
def get_portfolio() -> str:
    """Get current portfolio state."""
    return tool_get_portfolio()


@mcp_server.tool()
def get_regime(symbol: str = "BTC/USDT") -> str:
    """Analyze market regime."""
    return tool_get_regime(symbol)


@mcp_server.tool()
def get_economics() -> str:
    """Fetch economic indicators."""
    return tool_get_economics()


@mcp_server.tool()
def render_chart(chart_type: str = "candles", symbol: str = "BTC/USDT") -> str:
    """Generate a trading chart."""
    return tool_render_chart(chart_type, symbol)


@mcp_server.tool()
def adapter_list() -> str:
    """List all registered adapters."""
    return tool_adapter_list()


@mcp_server.tool()
def adapter_register(version: str, path: str, training_score: float = 0.0,
                     training_cycles: int = 0, training_examples: int = 0,
                     previous_version: str = "") -> str:
    """Register a new trained adapter."""
    return tool_adapter_register(version, path, training_score, training_cycles, training_examples, previous_version)


@mcp_server.tool()
def adapter_promote(version: str) -> str:
    """Promote an adapter to active."""
    return tool_adapter_promote(version)


@mcp_server.tool()
def adapter_rollback(version: str, reason: str = "performance regression") -> str:
    """Rollback to a previous adapter version."""
    return tool_adapter_rollback(version, reason)


@mcp_server.tool()
def training_queue(version: str, base_model: str = "Qwen/Qwen2.5-7B-Instruct",
                   dataset_path: str = "", method: str = "qlora",
                   epochs: int = 3, lora_r: int = 16,
                   notes: str = "") -> str:
    """Queue a training job."""
    return tool_training_queue(version, base_model, dataset_path, method, epochs, lora_r, notes)


@mcp_server.tool()
def training_status() -> str:
    """Check current training job status."""
    return tool_training_status()


@mcp_server.tool()
def eval_run(version: str, benchmark: str = "traderbench") -> str:
    """Queue an evaluation run for an adapter."""
    return tool_eval_run(version, benchmark)


@mcp_server.tool()
def metrics_snapshot() -> str:
    """Get current metrics snapshot."""
    return tool_metrics_snapshot()


@mcp_server.tool()
def harness_pause(reason: str = "") -> str:
    """Pause the harness."""
    return tool_harness_pause(reason)


@mcp_server.tool()
def harness_resume() -> str:
    """Resume the harness."""
    return tool_harness_resume()


@mcp_server.tool()
def research_idle_check() -> str:
    """Check if research-scout can run."""
    return tool_research_idle_check()


@mcp_server.tool()
def discover_symbols(exchange_name: str = None) -> str:
    """Discover tradable symbols from the current exchange."""
    return tool_discover_symbols(exchange_name)


@mcp_server.tool()
def qmath(op: str, args: dict = None) -> str:
    """Accurate math/quant/stat (evaluate, mean, std, percentile, returns, sharpe_ratio, sortino_ratio, max_drawdown, var_historical, cvar, kelly_fraction, correlation, beta, ols_regression, black_scholes, irr, npv, percent_change, ...). Use this instead of hand-arithmetic."""
    return tool_qmath(op, args)


@mcp_server.tool()
def qmath_ops() -> str:
    """List available qmath operations and their argument signatures."""
    return tool_qmath_ops()


# =======================================================================
# Main
# =======================================================================

def main():
    global args, _args
    parser = argparse.ArgumentParser(description="OpenTrader MCP Server")
    parser.add_argument("--port", type=int, default=8092, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--exchange", default="paper", help="Exchange backend")
    parser.add_argument("--initial-cash", type=float, default=100_000, help="Paper initial cash")
    parser.add_argument("--state-dir", default=None, help="State directory")
    parser.add_argument("--max-position-pct", type=float, default=0.10, help="Max position size")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()
    _args = args

    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format="%(asctime)s [%(name)s] %(message)s")

    # Initialize trading globals
    risk_config = RiskConfig(max_position_pct=args.max_position_pct)
    state_dir = args.state_dir or str(Path.cwd() / "data")
    init_globals(
        exchange_name=args.exchange,
        risk_config=risk_config,
        state_dir=state_dir,
        initial_cash=args.initial_cash,
        models_meta={"mcp_server": "opentrader-v0.1.0"},
    )

    logger.info(f"Starting OpenTrader MCP server on {args.host}:{args.port}")
    logger.info(f"Exchange: {args.exchange}, Cash: ${args.initial_cash:,.2f}")
    logger.info(f"MCP endpoint: http://{args.host}:{args.port}/mcp")
    logger.info(f"REST API: http://{args.host}:{args.port}/api/health")

    # Graceful shutdown
    def _shutdown(*_):
        logger.info("Shutting down...")
        _exchange.disconnect()
        sys.exit(0)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # REST routes already have /api prefix in their @rest_app.get("/api/...") decorators.
    # Mount rest_app at root so /api/health, /api/ohlcv etc. work directly.
    _combined = FastAPI(title="OpenTrader")
    _combined.mount("/", rest_app, name="rest")
    # Mount MCP SSE at explicit /mcp path to avoid route conflicts
    _combined.mount("/mcp", mcp_server.sse_app(), name="mcp")

    logger.info(f"MCP SSE endpoint: http://{args.host}:{args.port}/mcp")
    logger.info(f"REST API root: http://{args.host}:{args.port}/api/*")

    uvicorn.run(_combined, host=args.host, port=args.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
