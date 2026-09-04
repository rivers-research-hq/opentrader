#!/usr/bin/env python3
"""Account context — fee schedules, capital constraints, and position advice.

Injected into the debate engine, risk manager, and portfolio optimizer
so every component understands the cost of trading at the current
portfolio size.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class FeeSchedule:
    """Trading fees for an exchange route — per-side costs."""

    maker_pct: float = 0.0  # Maker fee as fraction (e.g. 0.0016 = 0.16%)
    taker_pct: float = 0.0  # Taker fee as fraction
    fixed_per_trade: float = 0.0  # Fixed cost per side (e.g. $0.35 for IBKR stocks)
    min_fee: float = 0.0  # Minimum fee per side

    def buy_cost(self, notional: float, taker: bool = True) -> float:
        """Dollar cost of buying `notional` worth."""
        pct = self.taker_pct if taker else self.maker_pct
        return max(self.min_fee, pct * notional + self.fixed_per_trade)

    def sell_cost(self, notional: float, taker: bool = True) -> float:
        """Dollar cost of selling `notional` worth (same structure)."""
        return self.buy_cost(notional, taker)

    def round_trip_cost(self, notional: float) -> float:
        """Total cost of buy + sell."""
        return self.buy_cost(notional) + self.sell_cost(notional)

    def round_trip_pct(self, notional: float) -> float:
        """Round-trip cost as a percentage of notional."""
        if notional <= 0:
            return 0.0
        return self.round_trip_cost(notional) / notional

    def min_notional(self, max_cost_pct: float = 0.20) -> float:
        """Minimum notional where fees are <= max_cost_pct (e.g. 20%)."""
        # Binary search for the break-even notional
        lo, hi = 0.01, 1_000_000.0
        for _ in range(50):
            mid = (lo + hi) / 2
            if self.round_trip_pct(mid) <= max_cost_pct:
                hi = mid
            else:
                lo = mid
        return max(hi, 1.0)


# ── Fee schedules per exchange / asset class ─────────────────────

FEE_TABLES: Dict[str, Dict[str, FeeSchedule]] = {
    "kraken": {
        "default": FeeSchedule(maker_pct=0.0016, taker_pct=0.0026),
    },
    "ibkr": {
        "stock": FeeSchedule(fixed_per_trade=0.35, min_fee=0.35),
        "crypto": FeeSchedule(taker_pct=0.0018, min_fee=1.75),
        "forex": FeeSchedule(fixed_per_trade=0.0, min_fee=0.0),  # spread-based
        "futures": FeeSchedule(fixed_per_trade=0.85, min_fee=0.85),
        "options": FeeSchedule(fixed_per_trade=0.65, min_fee=0.65),
        "bond": FeeSchedule(fixed_per_trade=1.0, min_fee=1.0),
        "default": FeeSchedule(fixed_per_trade=0.35, min_fee=0.35),
    },
    "paper": {
        "default": FeeSchedule(),  # Zero fees
    },
    "finnhub": {
        # Finnhub is data-only, but the execution goes through IBKR
        "stock": FeeSchedule(fixed_per_trade=0.35, min_fee=0.35),
        "default": FeeSchedule(fixed_per_trade=0.35, min_fee=0.35),
    },
    "multi": {
        # MultiExchangeRouter: crypto routes through the crypto child (kraken
        # %-fees), stocks through the stock child (IBKR fixed). The router
        # picks per-symbol via the get_fees_for_route lookup below.
        "crypto": FeeSchedule(taker_pct=0.0026, maker_pct=0.0016),
        "stock": FeeSchedule(fixed_per_trade=0.35, min_fee=0.35),
        "default": FeeSchedule(taker_pct=0.0026, maker_pct=0.0016),
    },
}


@dataclass
class AccountContext:
    """Current account state with fee awareness.

    Generated once per cycle from exchange + portfolio + config.
    Passed to debate engine, risk manager, and portfolio optimizer.
    """

    capital: float = 100.0  # Total portfolio value
    cash_free: float = 100.0  # Cash available to deploy
    capital_deployed: float = 0.0  # Value currently in positions

    # Fee schedule lookup
    exchange: str = "paper"  # Exchange name for fee lookup
    route_map: Dict[str, str] = field(default_factory=dict)
    # route_map: {"BTC/USDT": "kraken", "AAPL": "ibkr"} — maps symbol to route

    @property
    def fee_table(self) -> Dict[str, FeeSchedule]:
        return FEE_TABLES.get(self.exchange, FEE_TABLES["paper"])

    def get_fees(self, symbol: str) -> FeeSchedule:
        """Get the fee schedule for a specific symbol."""
        route = self.route_map.get(symbol)
        if route is None or route not in FEE_TABLES:
            # Determine route by symbol convention when not explicitly mapped
            if symbol and "/" in symbol:
                quote = symbol.split("/")[-1].upper()
                if quote == "USDT":
                    route = "kraken"
                else:
                    route = "ibkr"  # forex pairs → IBKR spread-based fees
            else:
                route = "finnhub"
        table = FEE_TABLES.get(route, FEE_TABLES["paper"])
        # Try symbol-specific, then default
        return table.get(
            symbol.lower() if symbol else "default", table.get("default", FeeSchedule())
        )

    def fee_impact(self, symbol: str, notional: float) -> tuple:
        """Returns (buy_fee_dollars, sell_fee_dollars, round_trip_dollars, round_trip_pct)."""
        fs = self.get_fees(symbol)
        buy = fs.buy_cost(notional)
        sell = fs.sell_cost(notional)
        rt = buy + sell
        return (
            round(buy, 2),
            round(sell, 2),
            round(rt, 2),
            round(rt / notional * 100, 1) if notional > 0 else 0.0,
        )

    def min_position_notional(self, symbol: str, max_cost_pct: float = 0.20) -> float:
        """Minimum position size where round-trip fees <= max_cost_pct of position."""
        return max(self.get_fees(symbol).min_notional(max_cost_pct), 1.0)

    def break_even_move(self, symbol: str, notional: float) -> float:
        """Price move % needed just to cover round-trip fees."""
        _, _, _, rt_pct = self.fee_impact(symbol, notional)
        return rt_pct / 100  # Convert % to fraction

    def position_advice(self, symbol: str, notional: float) -> str:
        """Human-readable advice about position sizing vs. fees."""
        buy, sell, rt, rt_pct = self.fee_impact(symbol, notional)
        rt_fraction = rt_pct / 100

        if rt_pct > 15:
            return (
                f"CAUTION: Round-trip fees ${rt:.2f} ({rt_pct:.1f}% of position). "
                f"Need {rt_pct:.0f}%+ price move just to break even. "
                f"Consider larger position or skipping."
            )
        elif rt_pct > 5:
            return (
                f"Fee-aware: Round-trip ${rt:.2f} ({rt_pct:.1f}%). "
                f"Hold for meaningful move, don't day-trade this position."
            )
        elif rt_pct > 1:
            return f"Low-cost: Round-trip ${rt:.2f} ({rt_pct:.1f}%). Active trading OK."
        else:
            return (
                f"Negligible fees: Round-trip ${rt:.2f} ({rt_pct:.1f}%). Trade freely."
            )

    def summary_json(self) -> dict:
        """JSON-serializable summary for injection into the LLM debate context."""
        lines = []
        lines.append(
            f"Portfolio: ${self.capital:,.2f} total, ${self.cash_free:,.2f} free, ${self.capital_deployed:,.2f} deployed"
        )

        # Per-asset-class fee summary
        for route_name in sorted(set(self.route_map.values()) | {self.exchange}):
            fs = FEE_TABLES.get(route_name, {}).get("default", FeeSchedule())
            if fs.taker_pct > 0:
                lines.append(
                    f"  {route_name}: {fs.taker_pct:.2%} taker / {fs.maker_pct:.2%} maker"
                )
            elif fs.fixed_per_trade > 0:
                lines.append(
                    f"  {route_name}: ${fs.fixed_per_trade:.2f} per trade + ${fs.min_fee:.2f} min"
                )

        # Minimum position advice
        lines.append(
            f"Min position: ${self.min_position_notional('default'):.2f} (keep fees under 20%)"
        )
        lines.append(
            f"Commission impact: Aim for positions >5x the round-trip commission cost."
        )

        return {
            "capital": self.capital,
            "cash_free": self.cash_free,
            "capital_deployed": self.capital_deployed,
            "exchange": self.exchange,
            "summary": "\n".join(lines),
        }

    @classmethod
    def from_harness(cls, harness, exchange_name: str = None) -> "AccountContext":
        """Build AccountContext from a running harness instance."""
        bal = harness.exchange.get_balance()
        exchange = exchange_name or harness.exchange.name.lower()

        # Build route map from active symbols
        route_map = {}
        for sym in getattr(harness, "symbols", []):
            if "/" in sym:
                route_map[sym] = "kraken"
            else:
                route_map[sym] = "ibkr"

        return cls(
            capital=bal.total_value,
            cash_free=bal.cash,
            capital_deployed=bal.total_value - bal.cash,
            exchange=exchange,
            route_map=route_map,
        )
