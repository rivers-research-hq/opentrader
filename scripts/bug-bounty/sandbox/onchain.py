#!/usr/bin/env python3
"""Onchain Adapter — wraps AgentKit for OpenTrader harness execution.

Routes BUY signals to onchain token swaps via Coinbase DEX on Base Sepolia testnet.
Paper settlement still available for SELL/HOLD signals.

Usage (in harness):
    adapter = OnchainAdapter(key_path="/path/to/cdp_key.json")
    await adapter.initialize()
    wallet = adapter.wallet_info  # {address, network, balances}

No key material is ever logged or exposed.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("opentrader.onchain")

# ATLANTIS adapter path
_ATLANTIS = str(Path(__file__).resolve().parent.parent / "atlantis")
if _ATLANTIS not in sys.path:
    sys.path.insert(0, _ATLANTIS)


class OnchainAdapter:
    """Privacy-first onchain wallet + swap adapter for OpenTrader.

    Loads CDP key from a JSON file, never logs key material.
    Operates on Base Sepolia testnet by default.
    """

    def __init__(self, key_path: str = None, network: str = "base-sepolia"):
        self._network = network
        self._ak = None
        self._wallet_info: dict = {}
        self._initialized = False

        # Load CDP key from file
        self._key_id = None
        self._key_secret = None
        if key_path and os.path.exists(key_path):
            try:
                data = json.loads(Path(key_path).read_text())
                # Extract key UUID from the name path
                name = data.get("name", "")
                self._key_id = name  # full org/key path for CDP
                self._key_secret = data.get("privateKey", "")
                logger.info("CDP key loaded (id: ***%s)", self._key_id[-8:] if len(self._key_id) > 8 else "???")
            except Exception as e:
                logger.error("Failed to load CDP key: %s", e)
        elif key_path:
            logger.warning("CDP key file not found: %s", key_path)

    async def initialize(self) -> bool:
        if not self._key_id or not self._key_secret:
            logger.warning("No CDP key — onchain adapter unavailable")
            return False

        # CDP wallet provider reads from env vars — set them at runtime.
        # NOTE: These are visible to subprocesses and /proc/<pid>/environ.
        # Prefer setting them in the actual environment over hardcoding.
        import os as _os
        _os.environ["CDP_API_KEY_ID"] = self._key_id
        _os.environ["CDP_API_KEY_SECRET"] = self._key_secret
        _os.environ["CDP_WALLET_SECRET"] = _os.environ.get("CDP_WALLET_SECRET", "opentrader")
        _os.environ["CDP_NETWORK_ID"] = self._network

        # CDP wallet uses asyncio.run() internally — patch for nested loops
        import nest_asyncio
        nest_asyncio.apply()

        try:
            from adapters.agentkit import AgentKitAdapter, AgentKitConfig

            cfg = AgentKitConfig(
                enabled=True,
                network_id=self._network,
                wallet_type="cdp",
                api_key_id=self._key_id,
                api_key_secret=self._key_secret,
            )
            self._ak = AgentKitAdapter(cfg)
            ok = await self._ak.initialize()
            if ok:
                details = await self._ak.get_wallet_details()
                self._wallet_info = details
                self._initialized = True
                logger.info(
                    "Onchain wallet ready — network=%s address=%s",
                    self._network, details.get("address", "?")[:10] + "..."
                )
            else:
                logger.error("AgentKit initialization failed")
            return ok
        except Exception as e:
            logger.error("AgentKit init error: %s", e)
            return False

    @property
    def wallet_info(self) -> dict:
        return self._wallet_info

    @property
    def ready(self) -> bool:
        return self._initialized and self._ak is not None

    async def get_price(self, symbol: str) -> Optional[float]:
        """Get Pyth oracle price. symbol e.g. 'BTC/USD', 'ETH/USD'."""
        if not self._ak:
            return None
        try:
            result = await self._ak.get_price(symbol)
            return float(result) if result else None
        except Exception:
            return None

    async def swap(self, from_token: str, to_token: str, amount: float) -> Optional[dict]:
        """Execute an onchain token swap via Coinbase DEX."""
        if not self._ak:
            return None
        try:
            result = await self._ak.swap(from_token, to_token, amount)
            return result
        except Exception as e:
            logger.error("Swap failed: %s", e)
            return None

    async def get_balances(self) -> dict:
        """Get all token balances."""
        if not self._ak:
            return {}
        try:
            details = await self._ak.get_wallet_details()
            return details.get("balances", {})
        except Exception:
            return {}

    async def close(self):
        self._initialized = False
        logger.info("Onchain adapter closed")
