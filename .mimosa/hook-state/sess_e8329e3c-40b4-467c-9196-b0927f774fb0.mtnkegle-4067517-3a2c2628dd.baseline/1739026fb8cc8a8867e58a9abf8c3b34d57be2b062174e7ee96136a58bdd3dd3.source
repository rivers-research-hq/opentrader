#!/usr/bin/env python3
"""Paper Exchange — simulated trading for OpenTrader.

No real money, no API keys. Uses a simple internal ledger.
Ported from ATLANTIS TraderHarness.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .base import ExchangeBase, OHLCV, OrderResult, Balance, register_exchange


class PaperExchange(ExchangeBase):
    """Simulated exchange with in-memory ledger.

    Supports optional slippage and partial fills for realism.
    """

    def __init__(self, name: str = "paper", config: dict = None):
        super().__init__(name, config)
        self._cash: float = (
            float(config.get("initial_cash", 100_000)) if config else 100_000.0
        )
        self._positions: Dict[str, float] = {}
        self._cost_basis: Dict[str, float] = {}
        self._fills: List[dict] = []
        self._prices: Dict[str, float] = {}
        self._bars: Dict[str, List[OHLCV]] = {}
        self._order_counter: int = 1

        # Slippage and partial fill config
        self._slippage_pct: float = (
            float(config.get("slippage_pct", 0.0)) if config else 0.0
        )
        self._partial_fill_prob: float = (
            float(config.get("partial_fill_prob", 0.0)) if config else 0.0
        )
        self._partial_fill_ratio: float = (
            float(config.get("partial_fill_ratio", 0.7)) if config else 0.7
        )

    def connect(self) -> bool:
        self._connected = True
        return True

    def load_bars(self, symbol: str, bars: List[dict]) -> None:
        """Pre-load OHLCV bars from synthetic data or file."""
        self._bars[symbol] = [OHLCV.from_dict(b) for b in bars]
        if self._bars[symbol]:
            self._prices[symbol] = self._bars[symbol][-1].close

    _MAX_BARS_PER_SYMBOL: int = 10_000

    def push_bar(self, symbol: str, bar: dict) -> None:
        """Push a single new bar (for live simulation)."""
        ohlcv = OHLCV.from_dict(bar)
        if symbol not in self._bars:
            self._bars[symbol] = []
        self._bars[symbol].append(ohlcv)
        # Trim oldest bars to prevent unbounded memory growth
        if len(self._bars[symbol]) > self._MAX_BARS_PER_SYMBOL:
            self._bars[symbol] = self._bars[symbol][-self._MAX_BARS_PER_SYMBOL :]
        self._prices[symbol] = ohlcv.close

    def get_bars(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> List[OHLCV]:
        bars = self._bars.get(symbol, [])
        return bars[-limit:] if len(bars) > limit else bars

    def get_current_price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        import random

        base_price = price if price else self._prices.get(symbol, 0)
        if base_price <= 0:
            return OrderResult(
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=0,
                status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw={"error": "no price data"},
            )

        # Apply slippage: buys get worse price, sells get worse price
        slippage = self._slippage_pct
        if side.upper() == "BUY":
            fill_price = base_price * (1.0 + slippage)
        else:
            fill_price = base_price * (1.0 - slippage)

        # Partial fill: reduce quantity by random ratio
        effective_qty = quantity
        fill_pct = 1.0
        if self._partial_fill_prob > 0 and random.random() < self._partial_fill_prob:
            fill_ratio = self._partial_fill_ratio + random.random() * (
                1.0 - self._partial_fill_ratio
            )
            effective_qty *= fill_ratio
            fill_pct = fill_ratio

        cost = fill_price * effective_qty

        if side.upper() == "BUY":
            if cost > self._cash:
                affordable_qty = self._cash / fill_price
                if affordable_qty <= 0:
                    return OrderResult(
                        order_id=f"paper_{self._order_counter}",
                        symbol=symbol,
                        side=side,
                        quantity=effective_qty,
                        price=fill_price,
                        status="rejected",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        raw={"error": "insufficient cash"},
                    )
                effective_qty = affordable_qty
                fill_pct = effective_qty / max(quantity, 1e-12)
                cost = fill_price * effective_qty
            self._cash -= cost
            self._positions[symbol] = self._positions.get(symbol, 0) + effective_qty
            self._cost_basis[symbol] = self._cost_basis.get(symbol, 0) + cost

        elif side.upper() == "SELL":
            pos = self._positions.get(symbol, 0)
            if pos <= 0:
                return OrderResult(
                    order_id=f"paper_{self._order_counter}",
                    symbol=symbol,
                    side=side,
                    quantity=effective_qty,
                    price=fill_price,
                    status="rejected",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw={"error": "no position"},
                )
            effective_qty = min(effective_qty, pos)
            fill_pct = effective_qty / max(quantity, 1e-12)
            self._cash += fill_price * effective_qty
            self._positions[symbol] -= effective_qty
            # Decrement cost basis proportionally to the fraction sold, using
            # the realized average entry — otherwise avg entry inflates after
            # partial sells (cost basis would sum ALL buys against residual qty).
            avg_entry = self._cost_basis.get(symbol, 0) / max(pos, 1e-12)
            self._cost_basis[symbol] = max(
                0.0,
                self._cost_basis.get(symbol, 0) - avg_entry * effective_qty,
            )
            if self._positions[symbol] <= 0:
                del self._positions[symbol]
                self._cost_basis.pop(
                    symbol, None
                )  # safe delete — may not exist on restore

        order_id = f"paper_{self._order_counter}"
        self._order_counter += 1
        fill = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": round(effective_qty, 8),
            "price": round(fill_price, 2),
            "cost": round(cost, 2),
            "cash_after": round(self._cash, 2),
            "fill_pct": round(fill_pct, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._fills.append(fill)
        if len(self._fills) > 5000:
            del self._fills[:-5000]
        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=round(effective_qty, 8),
            price=fill_price,
            status="filled",
            timestamp=fill["timestamp"],
            raw=fill,
        )

    def get_balance(self) -> Balance:
        portfolio_value = self._cash
        for sym, qty in self._positions.items():
            price = self._prices.get(sym, 0)
            portfolio_value += price * qty
        return Balance(
            cash=round(self._cash, 2),
            total_value=round(portfolio_value, 2),
            positions={k: round(v, 8) for k, v in self._positions.items()},
        )

    def get_fills(self) -> List[dict]:
        return self._fills

    def set_slippage(self, pct: float) -> None:
        """Set slippage as a decimal fraction (e.g. 0.0005 = 5bps)."""
        self._slippage_pct = pct

    def set_partial_fill(self, prob: float, ratio: float = 0.7) -> None:
        """Set partial fill probability and min fill ratio."""
        self._partial_fill_prob = prob
        self._partial_fill_ratio = ratio

    def reset(self, initial_cash: float = 100_000) -> None:
        self._cash = initial_cash
        self._positions.clear()
        self._cost_basis.clear()
        self._fills.clear()
        self._bars.clear()
        self._prices.clear()
        self._order_counter = 1

    def restore_ledger(
        self, cash: float, positions: Dict[str, float],
        cost_basis: Dict[str, float], fills: list = None,
    ) -> None:
        """Restore the in-memory ledger from persisted state.

        Sets the attrs get_balance() reads so a restart resumes the real book
        instead of reverting to init cash / zero positions.
        """
        self._cash = float(cash)
        self._positions = dict(positions)
        self._cost_basis = dict(cost_basis)
        if fills is not None:
            self._fills = list(fills)

    def discover_symbols(self) -> List[str]:
        """Return symbols currently loaded into the paper exchange."""
        return list(self._bars.keys()) if self._bars else list(self._prices.keys())


register_exchange("paper", PaperExchange)
