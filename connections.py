#!/usr/bin/env python3
"""Connections Manager — central store for all API keys and service configs.

Reads/writes a JSON file (data/connections.json) so the dashboard can manage
keys without env vars or CLI flags. The harness reads this file at startup.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from security.guards import guarded_urlopen  # hardening (2026-09-02)

logger = logging.getLogger("opentrader.connections")

urlopen = guarded_urlopen  # hardening shadow — all outbound requests via guard

CONNECTIONS_FILE = Path(__file__).resolve().parent / "data" / "connections.json"

# Default connection template — every known service
DEFAULT_CONNECTIONS: Dict[str, Dict[str, Any]] = {
    "finnhub": {
        "label": "Finnhub",
        "type": "data",
        "description": "US stock OHLCV & quotes (free tier)",
        "api_key": "",
        "base_url": "https://finnhub.io/api/v1",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "kraken": {
        "label": "Kraken",
        "type": "exchange",
        "description": "Crypto spot exchange via CCXT",
        "api_key": "",
        "api_secret": "",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "coinbase": {
        "label": "Coinbase",
        "type": "exchange",
        "description": "Crypto spot exchange via CCXT",
        "api_key": "",
        "api_secret": "",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "coingecko": {
        "label": "CoinGecko",
        "type": "sentiment",
        "description": "Crypto trending, global stats, BTC dominance",
        "api_key": "",
        "base_url": "https://api.coingecko.com/api/v3",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "fear_greed": {
        "label": "Fear & Greed",
        "type": "sentiment",
        "description": "Crypto Fear & Greed Index (alternative.me)",
        "api_key": "",
        "base_url": "https://api.alternative.me/fng/",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "fred": {
        "label": "FRED",
        "type": "data",
        "description": "Federal Reserve economic data (macro indicators)",
        "api_key": "",
        "base_url": "https://api.stlouisfed.org/fred",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "llama_server": {
        "label": "LLaMA Server",
        "type": "model",
        "description": "Local inference server for trading agent",
        "api_key": "",
        "base_url": "http://127.0.0.1:8080",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "mcp_server": {
        "label": "MCP Server",
        "type": "server",
        "description": "Economic data & external API proxy",
        "api_key": "",
        "base_url": "http://127.0.0.1:8092",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "dashboard": {
        "label": "Dashboard",
        "type": "server",
        "description": "OpenTrader web UI & monitoring",
        "api_key": "",
        "base_url": "http://127.0.0.1:8098",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
    "harness": {
        "label": "Trading Harness",
        "type": "server",
        "description": "Main trading loop (harness.py, direct)",
        "api_key": "",
        "base_url": "http://127.0.0.1:8098",
        "enabled": True,
        "last_check": None,
        "status": "disconnected",
    },
}


class ConnectionsManager:
    """Singleton that reads/writes connections.json."""

    _instance: Optional[ConnectionsManager] = None

    def __init__(self, filepath: str = None):
        self._path = Path(filepath or CONNECTIONS_FILE)
        self._data: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def manager(cls) -> ConnectionsManager:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # Map service → list of (field_name, env_var_name) for auto-import
    AUTO_IMPORT_ENV: dict = {
        "finnhub": [("api_key", "FINNHUB_API_KEY")],
        "fred": [("api_key", "FRED_API_KEY")],
        "kraken": [("api_key", "KRAKEN_API_KEY"), ("api_secret", "KRAKEN_SECRET_KEY")],
        "coinbase": [("api_key", "COINBASE_API_KEY"), ("api_secret", "COINBASE_SECRET_KEY")],
    }

    @classmethod
    def _auto_import_from_env(cls, service: str, data: dict) -> bool:
        """Import keys from environment if store has none yet. Returns True if anything changed."""
        import os
        changed = False
        for field, env_var in cls.AUTO_IMPORT_ENV.get(service, []):
            val = os.environ.get(env_var, "")
            if val and not data.get(field):
                data[field] = val
                changed = True
                logger.info("Auto-imported %s.%s from env var %s", service, field, env_var)
        return changed

    def _load(self):
        import os
        self._path.parent.mkdir(parents=True, exist_ok=True)
        changed = False
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text())
            except Exception:
                loaded = {}
            for key, default in DEFAULT_CONNECTIONS.items():
                if key in loaded:
                    merged = dict(default)
                    merged.update(loaded[key])
                    self._data[key] = merged
                    if self._auto_import_from_env(key, merged):
                        self._data[key] = merged
                        changed = True
                else:
                    self._data[key] = dict(default)
                    if self._auto_import_from_env(key, self._data[key]):
                        changed = True
        else:
            for key, value in DEFAULT_CONNECTIONS.items():
                self._data[key] = dict(value)
                if self._auto_import_from_env(key, self._data[key]):
                    changed = True
            changed = True  # always persist on first creation
        if changed:
            self._persist()

    def _persist(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    def get_all(self) -> dict:
        return dict(self._data)

    def get(self, service: str) -> Optional[Dict[str, Any]]:
        return self._data.get(service)

    def update(self, service: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if service not in self._data:
            return None
        self._data[service].update(fields)
        self._persist()
        return self._data[service]

    def set_key(self, service: str, key_name: str, value: str) -> Optional[Dict[str, Any]]:
        if service not in self._data:
            return None
        self._data[service][key_name] = value
        self._persist()
        return self._data[service]

    def check_connection(self, service: str) -> dict:
        """Test if a service is reachable."""
        import time
        from urllib.request import Request
        from urllib.error import URLError
        # NOTE: no local `urlopen` import — the module-level hardening shadow
        # (urlopen = guarded_urlopen, line 18) is the outbound path; a local
        # re-import of plain urlopen rebound past the guard (the L3 finding).

        cfg = self._data.get(service, {})
        now = time.time()
        result = {"status": "disconnected", "error": "", "latency_ms": 0}

        # Specific check per service type
        if service == "finnhub":
            key = cfg.get("api_key", "")
            if not key:
                result["error"] = "No API key"
            else:
                try:
                    t0 = time.time()
                    url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
                    with urlopen(Request(url), timeout=10) as r:
                        data = json.loads(r.read().decode())
                        if "c" in data:
                            result["status"] = "connected"
                            result["latency_ms"] = int((time.time() - t0) * 1000)
                        else:
                            result["error"] = str(data).get("error", "Invalid key")
                except Exception as e:
                    result["error"] = str(e)[:80]

        elif service in ("kraken", "coinbase"):
            try:
                import ccxt
                t0 = time.time()
                exchange_id = "kraken" if service == "kraken" else "coinbase"
                ex = getattr(ccxt, exchange_id)({"enableRateLimit": False})
                ticker = ex.fetch_ticker("BTC/USDT")
                if ticker and ticker.get("last", 0) > 0:
                    result["status"] = "connected"
                    result["latency_ms"] = int((time.time() - t0) * 1000)
                else:
                    result["error"] = "No ticker data"
            except Exception as e:
                result["error"] = str(e)[:80]

        elif service == "coingecko":
            try:
                t0 = time.time()
                url = "https://api.coingecko.com/api/v3/ping"
                with urlopen(Request(url), timeout=10) as r:
                    result["status"] = "connected"
                    result["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                result["error"] = str(e)[:80]

        elif service == "fear_greed":
            try:
                t0 = time.time()
                url = "https://api.alternative.me/fng/?limit=1"
                with urlopen(Request(url), timeout=10) as r:
                    data = json.loads(r.read().decode())
                    if data.get("data"):
                        result["status"] = "connected"
                        result["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                result["error"] = str(e)[:80]

        elif service == "fred":
            key = cfg.get("api_key", "")
            if not key:
                result["error"] = "No API key"
            else:
                try:
                    t0 = time.time()
                    url = f"https://api.stlouisfed.org/fred/series?series_id=GDP&api_key={key}&file_type=json"
                    with urlopen(Request(url), timeout=10) as r:
                        data = json.loads(r.read().decode())
                        if "seriess" in data:
                            result["status"] = "connected"
                            result["latency_ms"] = int((time.time() - t0) * 1000)
                        else:
                            result["error"] = "Invalid key"
                except Exception as e:
                    result["error"] = str(e)[:80]

        elif service == "llama_server":
            base = cfg.get("base_url", "http://127.0.0.1:8080")
            try:
                t0 = time.time()
                with urlopen(Request(f"{base}/health"), timeout=5) as r:
                    result["status"] = "connected"
                    result["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                result["error"] = str(e)[:80]

        elif service == "mcp_server":
            base = cfg.get("base_url", "http://127.0.0.1:8092")
            try:
                t0 = time.time()
                from urllib.error import HTTPError
                try:
                    with urlopen(Request(f"{base}/"), timeout=5) as r:
                        pass
                except HTTPError:
                    pass  # 404 still means server is running
                result["status"] = "connected"
                result["latency_ms"] = int((time.time() - t0) * 1000)
            except Exception as e:
                result["error"] = str(e)[:80]

        elif service == "dashboard":
            # Self-check — if we're serving this request, dashboard is running
            result["status"] = "connected"
            result["latency_ms"] = 0

        elif service == "harness":
            import time as time_mod
            try:
                state_path = CONNECTIONS_FILE.parent / "agent_state.json"
                if state_path.exists():
                    state = json.loads(state_path.read_text())
                    cycle = state.get("_cycle", 0)
                    last_cycle = state.get("_cycle")
                    if cycle and cycle > 0:
                        result["status"] = "connected"
                        result["latency_ms"] = 0
                        result["extra"] = {"cycle": cycle}
                    else:
                        result["error"] = "No cycle data in state"
                else:
                    result["error"] = "agent_state.json not found"
            except Exception as e:
                result["error"] = str(e)[:80]

        # Persist status
        self._data[service]["status"] = result["status"]
        self._data[service]["last_check"] = time.strftime("%H:%M:%S")
        self._persist()
        return result


def get_connection(service: str) -> Optional[Dict[str, Any]]:
    """Quick read without full manager — used by harness/exchange on startup."""
    return ConnectionsManager.manager().get(service)


def get_api_key(service: str, key_name: str = "api_key") -> str:
    """Get an API key for a service. Falls back to env var."""
    import os
    conn = get_connection(service)
    if conn:
        val = conn.get(key_name, "")
        if val:
            return val
    # Fallback: try env var
    env_map = {
        "finnhub": "FINNHUB_API_KEY",
        "fred": "FRED_API_KEY",
        "kraken": "KRAKEN_API_KEY",
        "coinbase": "COINBASE_API_KEY",
    }
    env_key = env_map.get(service, "")
    return os.environ.get(env_key, "")
