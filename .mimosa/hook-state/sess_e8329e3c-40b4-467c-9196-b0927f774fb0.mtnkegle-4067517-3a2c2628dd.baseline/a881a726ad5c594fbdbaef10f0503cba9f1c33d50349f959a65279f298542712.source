#!/usr/bin/env python3
"""Sidecar Exchange Adapter — wraps the Rust exchange-engine sidecar process.

Offloads compute-heavy PaperExchange ops to a subprocess (~2.5 MB RSS vs
~135 MB for the pure-Python PaperExchange).
"""

from typing import Any, Dict, List, Optional, Tuple

from .base import ExchangeBase, OHLCV, OrderResult, Balance, register_exchange
from exchange_engine.python.sidecar import SidecarClient


class ExchangeSidecarAdapter(ExchangeBase):
    """ExchangeBase subclass that delegates to a Rust sidecar process."""

    def __init__(self, name: str = "sidecar", config: dict = None):
        super().__init__(name, config)
        self._sidecar: Optional[SidecarClient] = None
        initial_cash = float(config.get("initial_cash", 100_000)) if config else 100_000.0
        self._cash: float = initial_cash
        self._positions: Dict[str, float] = {}
        self._cost_basis: Dict[str, float] = {}
        self._fills: List[dict] = []

    # ── lifecycle ────────────────────────────────────────────────────

    def connect(self) -> bool:
        if self._sidecar is not None:
            self._sync_from_sidecar()
            self._connected = True
            return True
        try:
            self._sidecar = SidecarClient()
            self._sidecar.start()
            self._sync_from_sidecar()
            self._connected = True
            return True
        except Exception:
            return False

    def disconnect(self) -> None:
        if self._sidecar:
            self._sidecar.stop()
            self._sidecar = None
        self._connected = False

    def connect_stream(self) -> bool:
        return self._connected

    def _sync_from_sidecar(self) -> None:
        if not self._sidecar:
            return
        try:
            bal = self._sidecar.get_balance()
            self._cash = float(bal.get("cash", 0))
            self._positions = {k: float(v) for k, v in bal.get("positions", {}).items()}
            fills = self._sidecar.get_fills()
            self._fills = fills if isinstance(fills, list) else []
        except Exception:
            pass

    # ── market data ──────────────────────────────────────────────────

    def get_bars(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> List[OHLCV]:
        if not self._sidecar:
            return []
        raw = self._sidecar.get_bars(symbol, timeframe, limit)
        return [OHLCV.from_dict(b) for b in raw]

    def get_current_price(self, symbol: str) -> Optional[float]:
        if not self._sidecar:
            return None
        return self._sidecar.get_current_price(symbol)

    def push_bar(self, symbol: str, bar: dict) -> None:
        if self._sidecar:
            self._sidecar.push_bar(symbol, bar)

    def load_bars(self, symbol: str, bars: List[dict]) -> None:
        if self._sidecar:
            self._sidecar.load_bars(symbol, bars)

    # ── order entry ──────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        if not self._sidecar:
            return OrderResult("", symbol, side, quantity, 0, "rejected", "")
        result = self._sidecar.place_order(symbol, side, quantity, price)
        self._sync_from_sidecar()
        return OrderResult(
            order_id=result.get("order_id", ""),
            symbol=symbol,
            side=side,
            quantity=float(result.get("quantity", quantity)),
            price=float(result.get("price", 0)),
            status=result.get("status", "filled"),
            timestamp=result.get("timestamp", ""),
            raw=result,
        )

    def get_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0)

    # ── account ──────────────────────────────────────────────────────

    def get_balance(self) -> Balance:
        if not self._sidecar:
            return Balance(cash=self._cash, total_value=self._cash, positions=self._positions)
        bal = self._sidecar.get_balance()
        self._cash = float(bal.get("cash", 0))
        self._positions = {k: float(v) for k, v in bal.get("positions", {}).items()}
        total = float(bal.get("total_value", self._cash))
        return Balance(cash=self._cash, total_value=total, positions=self._positions)

    def get_fills(self) -> List[dict]:
        if not self._sidecar:
            return self._fills
        fills = self._sidecar.get_fills()
        self._fills = fills if isinstance(fills, list) else []
        return self._fills

    def get_account_info(self) -> dict:
        if not self._sidecar:
            return {}
        return self._sidecar.get_state()

    # ── admin ────────────────────────────────────────────────────────

    def reset(self, initial_cash: float = 100_000) -> None:
        self._cash = initial_cash
        self._positions.clear()
        self._cost_basis.clear()
        self._fills.clear()
        if self._sidecar:
            self._sidecar.reset(initial_cash)

    def set_slippage(self, pct: float) -> None:
        if self._sidecar:
            self._sidecar.set_slippage(pct)

    def set_partial_fill(self, prob: float, ratio: float = 0.7) -> None:
        if self._sidecar:
            self._sidecar.set_partial_fill(prob, ratio)

    def discover_symbols(self) -> List[str]:
        if not self._sidecar:
            return []
        return self._sidecar.discover_symbols()

    def has_symbol(self, symbol: str) -> bool:
        if self._sidecar:
            try:
                p = self._sidecar.get_current_price(symbol)
                return p is not None and p > 0
            except Exception:
                return False
        return False


register_exchange("sidecar", ExchangeSidecarAdapter)
