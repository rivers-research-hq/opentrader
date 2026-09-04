#!/usr/bin/env python3
"""Finnhub WebSocket realtime price feed.

Connects to ``wss://ws.finnhub.io?token=<api_key>``, subscribes to trade
streams, and updates a thread-safe price cache.

Finnhub WebSocket protocol:
  - *subscribe*:  ``{"type":"subscribe", "symbol":"AAPL"}``
  - *trade*:      ``{"data":[{"p":120.85,"s":"AAPL","t":1575526691134,"v":100}],"type":"trade"}``
  - *ping*:       server sends ``{"type":"ping"}`` every ~60 s; reply with ``{"type":"pong"}``

Free-tier limit: 50 symbols concurrently subscribed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from .realtime import RealtimeFeed

logger = logging.getLogger("opentrader.realtime.finnhub")

FINNHUB_WS_URL = "wss://ws.finnhub.io"


class FinnhubRealtimeFeed(RealtimeFeed):
    """Finnhub WebSocket adapter — subscribes to real-time trade data.

    Usage inside ``FinnhubExchange``::

        self._realtime = FinnhubRealtimeFeed(self, ["AAPL", "MSFT"], config)
        self._realtime.start()
        ...

    Price updates arrive as inbound ``type=trade`` frames; each trade's
    ``p`` field is cached as the latest price for that symbol.
    """

    def __init__(
        self,
        exchange: Any,
        symbols: Optional[List[str]] = None,
        config: Optional[dict] = None,
    ) -> None:
        super().__init__(exchange, symbols, config)
        self._api_key: str = getattr(exchange, "_api_key", "")

    # ── RealtimeFeed hooks ──────────────────────────────────────────

    def _build_wsapp(self) -> Any:
        import websocket

        url = f"{FINNHUB_WS_URL}?token={self._api_key}"
        logger.debug("Finnhub WS url: %s", url)
        return websocket.WebSocketApp(url)

    def _on_open(self, ws: Any) -> None:
        self._ws_connected = True
        logger.info(
            "Finnhub WS connected, subscribing to %d symbols", len(self._symbols)
        )
        self._subscribe_inner(ws, self._symbols)

    def _on_message(self, ws: Any, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type", "")
        if msg_type == "ping":
            ws.send(json.dumps({"type": "pong"}))
            return

        if msg_type == "trade":
            for trade in data.get("data", []):
                symbol = trade.get("s")
                price = trade.get("p")
                ts_ms = trade.get("t", 0)
                if symbol and price is not None:
                    self._update_price(symbol, float(price), ts_ms / 1000.0)

    def _subscribe_inner(self, ws: Any, symbols: List[str]) -> None:
        for sym in symbols:
            try:
                ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
                logger.debug("Finnhub WS subscribed: %s", sym)
            except Exception as exc:
                logger.warning(
                    "Finnhub WS subscribe failed for %s: %s", sym, exc
                )
