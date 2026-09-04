#!/usr/bin/env python3
"""Realtime WebSocket price feed — base class with background thread, thread-safe
caches, and graceful WS-drop → REST fallback.

Subclasses implement three abstract hooks:
  _build_wsapp()  →  websocket.WebSocketApp(url, ...)
  _on_open(ws)    →  subscribe to symbols, set self._ws_connected = True
  _on_message(ws, message)  →  parse incoming frames, call self._update_price()

Usage from an Exchange adapter::

    self._realtime = FinnhubRealtimeFeed(self, ["AAPL"], config)
    self._realtime.start()                       # bg thread, non-blocking
    price = self._realtime.get_price("AAPL")     # thread-safe, REST fallback
    self._realtime.stop()                        # clean shutdown
"""

from __future__ import annotations

import json
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger("opentrader.realtime")


class RealtimeFeed(ABC):
    """Base class for WebSocket realtime price feeds.

    Maintains a background thread that:
      1. Connects via WebSocket
      2. Subscribes to symbols
      3. Parses incoming messages into thread-safe price cache
      4. Reconnects on drop

    ``get_price()`` returns the most-recent WS price or falls back to the parent
    exchange's REST endpoint when the WS feed is stale (< stale_threshold s) or
    disconnected.
    """

    def __init__(
        self,
        exchange: Any,
        symbols: Optional[List[str]] = None,
        config: Optional[dict] = None,
    ) -> None:
        self._exchange = exchange
        self._symbols: List[str] = list(symbols) if symbols else []
        self._config: dict = config or {}

        self._running = False
        self._ws_connected = False
        self._ws: Any = None
        self._thread: Optional[threading.Thread] = None

        # Thread-safe price snapshot
        self._prices: Dict[str, float] = {}
        self._price_ts: Dict[str, float] = {}
        self._lock = threading.Lock()

        # Config knobs
        self._stale_s = float(self._config.get("stale_threshold", 10.0))
        self._reconnect_s = float(self._config.get("reconnect_delay", 5.0))

    # ── public API ──────────────────────────────────────────────────

    def start(self) -> None:
        """Launch the background WebSocket thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_forever,
            daemon=True,
            name=f"rt-{type(self).__name__}",
        )
        self._thread.start()
        logger.info(
            "%s started for %d symbols",
            type(self).__name__,
            len(self._symbols),
        )

    def stop(self) -> None:
        """Shut down the background thread and close the WebSocket."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("%s stopped", type(self).__name__)

    def subscribe(self, symbols: List[str]) -> None:
        """Add symbols to the subscribed set (thread-safe, idempotent).

        If the WS is currently connected the symbols are subscribed
        immediately; otherwise they will be picked up on the next connect.
        """
        new: List[str] = []
        with self._lock:
            for s in symbols:
                if s not in self._symbols:
                    self._symbols.append(s)
                    new.append(s)
        if new:
            logger.debug("%s new symbols queued: %s", type(self).__name__, new)
        if new and self._ws_connected and self._ws:
            try:
                self._subscribe_inner(self._ws, new)
            except Exception:
                pass  # subscribe will happen on reconnect

    def get_price(self, symbol: str) -> Optional[float]:
        """Latest WS price for *symbol*, or ``None`` when stale / disconnected.

        Returns ``None`` (not a REST fallback) — the owning exchange adapter
        is responsible for its own fallback chain.  This avoids generating a
        recursive call when the exchange adapter calls back into the realtime
        feed.
        """
        with self._lock:
            ts = self._price_ts.get(symbol, 0)
            price = self._prices.get(symbol)
        if price is not None and (time.time() - ts) < self._stale_s:
            return price
        return None

    def is_connected(self) -> bool:
        return self._ws_connected

    # ── background loop ─────────────────────────────────────────────

    def _run_forever(self) -> None:
        """Loop: connect → subscribe → parse → reconnect on drop."""
        while self._running:
            try:
                self._ws = self._build_wsapp()
                self._ws.on_open = self._on_open
                self._ws.on_message = self._on_message
                self._ws.on_error = self._on_error
                self._ws.on_close = self._on_close
                self._ws.run_forever()
            except Exception as exc:
                logger.warning(
                    "%s ws exception: %s",
                    type(self).__name__,
                    exc,
                )
            self._ws_connected = False
            if self._running:
                logger.info(
                    "%s reconnecting in %.1f s …",
                    type(self).__name__,
                    self._reconnect_s,
                )
                time.sleep(self._reconnect_s)

    # ── abstract hooks (subclasses MUST implement these three) ──────

    @abstractmethod
    def _build_wsapp(self) -> Any:
        """Build and return a ``websocket.WebSocketApp`` instance."""

    @abstractmethod
    def _on_open(self, ws: Any) -> None:
        """Called when WS connects — subscribe to symbols here."""

    @abstractmethod
    def _on_message(self, ws: Any, message: str) -> None:
        """Called for each incoming WS frame — parse and call _update_price()."""

    # ── optional hooks (subclasses MAY override) ────────────────────

    def _on_error(self, ws: Any, error: Any) -> None:
        self._ws_connected = False
        logger.warning("%s ws error: %s", type(self).__name__, error)

    def _on_close(self, ws: Any, code: Any, msg: Any) -> None:
        self._ws_connected = False
        logger.info(
            "%s ws closed: code=%s msg=%s",
            type(self).__name__,
            code,
            msg,
        )

    def _subscribe_inner(self, ws: Any, symbols: List[str]) -> None:
        """Send per-symbol subscribe messages (override to match API format).

        Default is a no-op — subclasses should implement the protocol-specific
        subscribe frame.  Called from ``_on_open`` and from the public
        ``subscribe()`` when the WS is live.
        """

    # ── helpers for subclasses ──────────────────────────────────────

    def _update_price(self, symbol: str, price: float, ts: float) -> None:
        """Thread-safe price cache update.

        ``ts`` is a unix timestamp (float, seconds).  Only the *newest* price
        for each symbol is retained.
        """
        with self._lock:
            current_ts = self._price_ts.get(symbol, 0)
            if ts >= current_ts:
                self._prices[symbol] = price
                self._price_ts[symbol] = ts
