#!/usr/bin/env python3
"""Multi-Exchange Router — routes crypto to CCXT, stocks to Finnhub.

The harness sees one unified exchange. Internally, calls are delegated
based on symbol convention: "/" separator → crypto, bare ticker → stock.

Usage:
    from exchange.multi_router import MultiExchangeRouter
    exchange = MultiExchangeRouter(
        crypto_name="kraken",
        stock_name="finnhub",
        initial_cash=100_000,
    )
    bars = exchange.get_bars("AAPL", "1h", 100)    # → Finnhub
    bars = exchange.get_bars("BTC/USDT", "1h", 100) # → Kraken
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import ExchangeBase, OHLCV, Balance, OrderResult, get_exchange

logger = logging.getLogger("opentrader.router")

# Timeframes both exchanges support
_SHARED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "1d", "1w"}


class MultiExchangeRouter(ExchangeBase):
    """Unified exchange that delegates to crypto or stock backend by symbol convention.

    Convention: symbols containing "/" are crypto pairs (e.g. BTC/USDT),
    bare tickers are stocks (e.g. AAPL, NVDA, SPY).
    """

    def __init__(self, name: str = "multi", config: dict = None):
        super().__init__(name, config)
        config = config or {}
        initial_cash = float(config.get("initial_cash", 100_000))

        crypto_name = config.get("crypto_exchange", "kraken")
        stock_name = config.get("stock_exchange", "finnhub")

        # Split cash 50/50 between crypto and stock exchanges.
        # Each sub-exchange manages its own isolated ledger.
        half_cash = initial_cash / 2.0

        self._crypto = get_exchange(crypto_name, {
            "initial_cash": half_cash,
            "api_key": config.get("crypto_api_key", ""),
            "api_secret": config.get("crypto_api_secret", ""),
        }) or get_exchange("paper", {"initial_cash": half_cash})

        self._stock = get_exchange(stock_name, {"initial_cash": half_cash})

        if self._stock is None:
            logger.warning(f"Stock exchange '{stock_name}' not found, using paper")
            self._stock = get_exchange("paper", {"initial_cash": half_cash})

        self._crypto_name: str = crypto_name
        self._stock_name: str = stock_name
        self._connected: bool = False

    def _route(self, symbol: str) -> ExchangeBase:
        """Route symbol to its exchange: "/" in symbol → crypto, else stock."""
        if "/" in symbol:
            return self._crypto
        return self._stock

    def _is_crypto(self, symbol: str) -> bool:
        return "/" in symbol

    def _is_stock(self, symbol: str) -> bool:
        return "/" not in symbol

    # ── Connection ───────────────────────────────────────────

    def connect(self) -> bool:
        ok_count = 0
        for label, ex in [("crypto", self._crypto), ("stock", self._stock)]:
            if ex is None:
                logger.error(f"MultiExchangeRouter: {label} exchange is None")
                continue
            if ex.connect():
                ok_count += 1
            else:
                logger.warning(f"MultiExchangeRouter: {label} ({ex.name}) failed to connect")
        # Succeed if at least one sub-exchange connected
        self._connected = ok_count > 0
        if self._connected:
            logger.info(
                f"MultiExchangeRouter: {ok_count}/2 connected "
                f"(crypto={self._crypto_name}, stock={self._stock_name})"
            )
        return self._connected

    # ── Data ─────────────────────────────────────────────────

    def get_bars(self, symbol: str, timeframe: str = "1h",
                 limit: int = 100) -> List[OHLCV]:
        return self._route(symbol).get_bars(symbol, timeframe, limit)

    def get_current_price(self, symbol: str) -> Optional[float]:
        return self._route(symbol).get_current_price(symbol)

    def get_fee_schedule(self, symbol: str = "default"):
        return self._route(symbol).get_fee_schedule(symbol)

    def get_prices_batch(self, symbols: list) -> dict:
        result = {}
        crypto_syms = [s for s in symbols if self._is_crypto(s)]
        stock_syms = [s for s in symbols if self._is_stock(s)]

        for sym_list, ex in [(crypto_syms, self._crypto), (stock_syms, self._stock)]:
            if not sym_list or ex is None:
                continue
            if hasattr(ex, "get_prices_batch"):
                batch = ex.get_prices_batch(sym_list)
                result.update(batch)
            else:
                for sym in sym_list:
                    try:
                        price = ex.get_current_price(sym)
                        if price:
                            result[sym] = price
                    except Exception:
                        pass

        return result

    def get_order_book_depth(self, symbol: str, limit: int = 10) -> Optional[dict]:
        """Spot order-book depth for crypto symbols (delegates to kraken backend)."""
        if not self._is_crypto(symbol):
            return None
        ex = self._route(symbol)
        if hasattr(ex, "get_order_book_depth"):
            return ex.get_order_book_depth(symbol, limit)
        return None

    def load_bars(self, symbol: str, bars: List[dict]) -> None:
        self._route(symbol).load_bars(symbol, bars)

    # ── Orders ───────────────────────────────────────────────

    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = "market",
                    price: Optional[float] = None) -> OrderResult:
        return self._route(symbol).place_order(
            symbol, side, quantity, order_type, price,
        )

    # ── Balance ──────────────────────────────────────────────

    def restore_ledger(
        self, cash: float, positions: Dict[str, float],
        cost_basis: Dict[str, float] = None, fills: list = None,
    ) -> None:
        """Restore both child ledgers from the persisted aggregate.

        Positions + cost basis are routed by symbol convention ("/" → crypto);
        the aggregate cash is split 50/50 (matching init) so get_balance()'s
        aggregate total matches the saved book.
        """
        cost_basis = cost_basis or {}
        crypto_pos = {s: q for s, q in positions.items() if self._is_crypto(s)}
        stock_pos = {s: q for s, q in positions.items() if self._is_stock(s)}
        crypto_cb = {s: v for s, v in cost_basis.items() if self._is_crypto(s)}
        stock_cb = {s: v for s, v in cost_basis.items() if self._is_stock(s)}
        half = float(cash) / 2.0
        for ex, pos, cb in (
            (self._crypto, crypto_pos, crypto_cb),
            (self._stock, stock_pos, stock_cb),
        ):
            if ex is not None and hasattr(ex, "restore_ledger"):
                ex.restore_ledger(half, pos, cb, fills)

    def get_balance(self) -> Balance:
        """Aggregate balances from both exchanges."""
        total_cash = 0.0
        total_value = 0.0
        all_positions: Dict[str, float] = {}

        for ex in [self._crypto, self._stock]:
            if ex is None:
                continue
            try:
                bal = ex.get_balance()
                total_cash += bal.cash
                total_value += bal.total_value
                all_positions.update(bal.positions)
            except Exception as e:
                logger.warning(f"MultiExchangeRouter: balance error from {ex.name}: {e}")

        return Balance(
            cash=round(total_cash, 2),
            total_value=round(total_value, 2),
            positions=all_positions,
        )

    # ── Discovery ────────────────────────────────────────────

    def discover_symbols(self, max_symbols: int = 20) -> List[str]:
        """Aggregate symbols from crypto and stock child exchanges."""
        symbols: List[str] = []
        for ex in [self._crypto, self._stock]:
            if ex is None:
                continue
            try:
                symbols.extend(ex.discover_symbols(max_symbols=max_symbols))
            except Exception as e:
                logger.debug(f"discover_symbols from {ex.name}: {e}")
        return symbols

    # ── Utilities ────────────────────────────────────────────

    def get_fills(self) -> List[dict]:
        fills = []
        for ex in [self._crypto, self._stock]:
            if ex is None:
                continue
            try:
                fills.extend(ex.get_fills())
            except Exception:
                pass
        return fills

    def reset(self, initial_cash: float = 100_000) -> None:
        half = initial_cash / 2.0
        for ex in [self._crypto, self._stock]:
            if ex is not None and hasattr(ex, "reset"):
                ex.reset(half)

    def disconnect(self) -> None:
        for ex in [self._crypto, self._stock]:
            if ex is not None:
                ex.disconnect()
        self._connected = False

    # ── Accessors for direct sub-exchange access ─────────────

    @property
    def crypto(self) -> ExchangeBase:
        return self._crypto

    @property
    def stock(self) -> ExchangeBase:
        return self._stock
