#!/usr/bin/env python3
"""MCP Client — calls OpenTrader's MCP server tools via REST API.

This is how agents actually invoke trading tools.
Each tool maps to a method that calls the MCP server's HTTP endpoint.
"""
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError
from urllib.parse import urlencode

logger = logging.getLogger("opentrader.mcp_client")


class MCPClient:
    """Lightweight HTTP client for OpenTrader's MCP REST API.

    All calls are sync, matching the sync-only architecture.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8092", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            qs = urlencode({k: v for k, v in params.items() if v is not None})
            if qs:
                url = f"{url}?{qs}"
        return self._request(url)

    def _post(self, path: str, body: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body or {}).encode() if body else None
        return self._request(url, data=data, method="POST" if body else "GET")

    def _request(self, url: str, data: bytes = None, method: str = None) -> dict:
        req = Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw)
        except URLError as e:
            logger.error(f"MCP request failed: {url} — {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"MCP bad JSON from {url}: {e}")
            return {"error": f"bad JSON: {e}"}
        except Exception as e:
            logger.error(f"MCP unexpected error: {e}")
            return {"error": str(e)}

    # ── Tool methods ───────────────────────────────────────────

    def get_ohlcv(self, symbol: str = "BTC/USDT",
                  timeframe: str = "1h", limit: int = 50) -> dict:
        """Fetch OHLCV bars."""
        return self._get("/api/ohlcv", {"symbol": symbol, "timeframe": timeframe, "limit": limit})

    def submit_order(self, symbol: str, side: str, quantity: float,
                     order_type: str = "market", price: float = None,
                     confidence: float = 0.5, reason: str = "",
                     position_pct: float = None,
                     stop_loss: float = None, take_profit: float = None) -> dict:
        """Submit a trading order through the risk gate."""
        body = {
            "symbol": symbol, "side": side, "quantity": quantity,
            "order_type": order_type, "price": price,
            "confidence": confidence, "reason": reason,
        }
        if position_pct is not None:
            body["position_pct"] = position_pct
        if stop_loss is not None:
            body["stop_loss"] = stop_loss
        if take_profit is not None:
            body["take_profit"] = take_profit
        return self._post("/api/order", body)

    def get_portfolio(self) -> dict:
        """Get current portfolio state."""
        return self._get("/api/portfolio")

    def get_regime(self, symbol: str = "BTC/USDT") -> dict:
        """Analyze current market regime."""
        return self._get("/api/regime", {"symbol": symbol})

    def get_economics(self) -> dict:
        """Fetch economic indicators."""
        return self._get("/api/economics")

    def render_chart(self, chart_type: str = "candles",
                     symbol: str = "BTC/USDT") -> dict:
        """Generate a trading chart."""
        return self._get("/api/chart", {"chart_type": chart_type, "symbol": symbol})

    def get_state(self) -> dict:
        """Read current persisted state."""
        return self._get("/api/state")

    def health(self) -> dict:
        """Check MCP server health."""
        return self._get("/api/health")

    def tools(self) -> dict:
        """List available MCP tools."""
        return self._get("/api/tools")
