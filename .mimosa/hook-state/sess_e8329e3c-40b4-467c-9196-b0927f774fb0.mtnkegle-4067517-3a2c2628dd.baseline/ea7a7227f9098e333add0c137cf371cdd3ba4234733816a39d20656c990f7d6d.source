#!/usr/bin/env python3
"""Python client for the Rust exchange-engine sidecar.

Communicates via JSON-line protocol over a subprocess pipe.
Drop-in replacement for exchange/paper.py PaperExchange + risk/manager.py RiskManager.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from typing import Any, Optional

logger = logging.getLogger("opentrader.sidecar")


class SidecarError(Exception):
    pass


class SidecarClient:
    """Manages the Rust exchange-engine subprocess and provides Python APIs.

    Usage:
        sc = SidecarClient(binary="/path/to/exchange-engine")
        sc.start()

        # Exchange
        sc.load_bars("BTC/USDT", bars)
        price = sc.get_current_price("BTC/USDT")
        result = sc.place_order("BTC/USDT", "BUY", 1.0)
        balance = sc.get_balance()

        # Risk
        result = sc.risk_check(signal, 100000.0, 100000.0, {"BTC/USDT": 67550.0})

        sc.stop()
    """

    def __init__(self, binary: str = "exchange-engine"):
        self._binary = binary
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._seq: int = 0

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.running:
            return
        self._proc = subprocess.Popen(
            [self._binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # Ping to confirm readiness
        resp = self._call({"method": "ping"})
        assert resp["ok"], f"Sidecar ping failed: {resp}"
        logger.info("Sidecar started (pid=%d)", self._proc.pid)

    def stop(self) -> None:
        if not self.running:
            return
        self._call({"method": "shutdown"})
        self._proc.wait(timeout=2)
        self._proc = None
        logger.info("Sidecar stopped")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        return False

    # ── Internal ────────────────────────────────────────────────

    def _call(self, req: dict) -> dict:
        with self._lock:
            self._seq += 1
            req_line = json.dumps(req, default=str) + "\n"
            try:
                self._proc.stdin.write(req_line)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise SidecarError(f"Sidecar write failed: {e}") from e

            resp_line = self._proc.stdout.readline()
            if not resp_line:
                raise SidecarError("Sidecar closed stdout unexpectedly")
            try:
                resp = json.loads(resp_line)
            except json.JSONDecodeError as e:
                raise SidecarError(f"Bad JSON from sidecar: {resp_line[:200]}") from e

            if not resp.get("ok", False):
                raise SidecarError(resp.get("error", "unknown error"))
            return resp

    # ── Exchange API ────────────────────────────────────────────

    def load_bars(self, symbol: str, bars: list) -> None:
        self._call({
            "method": "exchange.load_bars",
            "symbol": symbol,
            "bars": bars,
        })

    def push_bar(self, symbol: str, bar: dict) -> None:
        self._call({
            "method": "exchange.push_bar",
            "symbol": symbol,
            "bar": bar,
        })

    def get_bars(self, symbol: str, limit: int = 100) -> list:
        resp = self._call({
            "method": "exchange.get_bars",
            "symbol": symbol,
            "limit": limit,
        })
        return resp.get("result", [])

    def get_current_price(self, symbol: str) -> Optional[float]:
        resp = self._call({
            "method": "exchange.get_current_price",
            "symbol": symbol,
        })
        result = resp.get("result")
        if result is None or result == "null":
            return None
        return float(result)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
    ) -> dict:
        resp = self._call({
            "method": "exchange.place_order",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
        })
        return resp.get("result", {})

    def get_balance(self) -> dict:
        resp = self._call({"method": "exchange.get_balance"})
        return resp.get("result", {})

    def reset(self, initial_cash: float = 100_000) -> None:
        self._call({
            "method": "exchange.reset",
            "initial_cash": initial_cash,
        })

    def discover_symbols(self) -> list:
        resp = self._call({"method": "exchange.discover_symbols"})
        return resp.get("result", [])

    def get_state(self) -> dict:
        resp = self._call({"method": "exchange.get_state"})
        return resp.get("result", {})

    def load_state(self, state: dict, config: dict = None) -> None:
        req: dict = {
            "method": "exchange.load_state",
            "state": state,
        }
        if config:
            req["config"] = config
        self._call(req)

    def set_slippage(self, pct: float) -> None:
        self._call({"method": "exchange.set_slippage", "pct": pct})

    def set_partial_fill(self, prob: float, ratio: float = 0.7) -> None:
        self._call({
            "method": "exchange.set_partial_fill",
            "prob": prob,
            "ratio": ratio,
        })

    def get_fills(self) -> list:
        resp = self._call({"method": "exchange.get_fills"})
        return resp.get("result", [])

    # ── Risk API ─────────────────────────────────────────────────

    def risk_set_initial(self, cash: float) -> None:
        self._call({"method": "risk.set_initial", "cash": cash})

    def risk_update_peak(self, portfolio_value: float) -> None:
        self._call({
            "method": "risk.update_peak",
            "portfolio_value": portfolio_value,
        })

    def risk_check_circuit_breaker(self, portfolio_value: float) -> bool:
        resp = self._call({
            "method": "risk.check_circuit_breaker",
            "portfolio_value": portfolio_value,
        })
        return bool(resp.get("result", False))

    def risk_kelly_criterion(
        self,
        win_prob: Optional[float] = None,
        win_loss_ratio: Optional[float] = None,
    ) -> float:
        resp = self._call({
            "method": "risk.kelly_criterion",
            "win_prob": win_prob,
            "win_loss_ratio": win_loss_ratio,
        })
        return float(resp.get("result", 0))

    def risk_var_calculation(
        self,
        portfolio_value: float,
        confidence: Optional[float] = None,
    ) -> float:
        resp = self._call({
            "method": "risk.var_calculation",
            "portfolio_value": portfolio_value,
            "confidence": confidence,
        })
        return float(resp.get("result", 0))

    def risk_check(
        self,
        signal: Any,
        portfolio_total_value: float,
        portfolio_cash: float,
        prices: dict,
        current_positions: Optional[dict] = None,
    ) -> dict:
        signal_dict = {
            "action": signal.action if hasattr(signal, 'action') else signal.get("action", ""),
            "symbol": signal.symbol if hasattr(signal, 'symbol') else signal.get("symbol", ""),
            "confidence": float(getattr(signal, 'confidence', 0) or 0),
            "position_pct": float(getattr(signal, 'position_pct', 0) or 0),
            "stop_loss": getattr(signal, 'stop_loss', None) or signal.get("stop_loss") if hasattr(signal, 'get') else getattr(signal, 'stop_loss', None),
            "take_profit": getattr(signal, 'take_profit', None) or signal.get("take_profit") if hasattr(signal, 'get') else getattr(signal, 'take_profit', None),
        }
        req: dict = {
            "method": "risk.check",
            "signal": signal_dict,
            "portfolio_total_value": portfolio_total_value,
            "portfolio_cash": portfolio_cash,
            "prices": prices,
        }
        if current_positions is not None:
            req["current_positions"] = current_positions
        resp = self._call(req)
        return resp.get("result", {})

    def risk_pre_trade_check(
        self,
        signal: Any,
        portfolio_total_value: float,
        portfolio_cash: float,
        prices: dict,
        current_positions: Optional[dict] = None,
        price_history: Optional[dict] = None,
    ) -> tuple:
        signal_dict = {
            "action": signal.action if hasattr(signal, 'action') else signal.get("action", ""),
            "symbol": signal.symbol if hasattr(signal, 'symbol') else signal.get("symbol", ""),
            "confidence": float(getattr(signal, 'confidence', 0) or 0),
            "position_pct": float(getattr(signal, 'position_pct', 0) or 0),
            "stop_loss": getattr(signal, 'stop_loss', None) or signal.get("stop_loss") if hasattr(signal, 'get') else getattr(signal, 'stop_loss', None),
            "take_profit": getattr(signal, 'take_profit', None) or signal.get("take_profit") if hasattr(signal, 'get') else getattr(signal, 'take_profit', None),
        }
        req: dict = {
            "method": "risk.pre_trade_check",
            "signal": signal_dict,
            "portfolio_total_value": portfolio_total_value,
            "portfolio_cash": portfolio_cash,
            "prices": prices,
        }
        if current_positions is not None:
            req["current_positions"] = current_positions
        if price_history is not None:
            req["price_history"] = price_history
        resp = self._call(req)
        result = resp.get("result", {})
        return (result.get("approved", False), result.get("reason", ""))

    def risk_get_config(self) -> dict:
        resp = self._call({"method": "risk.get_config"})
        return resp.get("result", {})

    def risk_set_config(self, config: dict) -> None:
        self._call({"method": "risk.set_config", "config": config})
