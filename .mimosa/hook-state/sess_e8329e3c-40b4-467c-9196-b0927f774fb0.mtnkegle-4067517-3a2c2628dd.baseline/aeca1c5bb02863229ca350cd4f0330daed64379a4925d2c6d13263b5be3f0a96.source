#!/usr/bin/env python3
"""Asset Class Allocator — model-driven allocation across crypto/stocks/forex.

Invoked before portfolio optimization. The harness passes all active symbols;
the allocator classifies them by asset class, consults the LLM for macro-level
weight proposals, then scales individual position sizes to respect those weights.

Design:
  1. Classify symbols by asset class (crypto, stock, forex, futures)
  2. Build a prompt for the LLM with portfolio state, current allocations,
     regime/trend info, and fee impacts per class
  3. LLM returns target weights per class (must sum to ≤ 100%)
  4. Scale per-symbol allocations to fit within class budget
  5. Return adjusted weights for the portfolio optimizer

Integration point: harness.py Phase 1.5 → before portfolio optimization.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.asset_allocator")

ASSET_CLASS_RULES = {
    "crypto": {"vol": 0.60, "max_exposure": 0.50, "min_position_notional": 25.0, "tags": ["BTC", "ETH", "SOL"]},
    "stock":  {"vol": 0.18, "max_exposure": 0.60, "min_position_notional": 100.0, "tags": ["STK", "ETF"]},
    "forex":  {"vol": 0.10, "max_exposure": 0.30, "min_position_notional": 500.0, "tags": ["CASH", "FX"]},
    "futures": {"vol": 0.20, "max_exposure": 0.20, "min_position_notional": 1000.0, "tags": ["FUT"]},
    "bond":   {"vol": 0.08, "max_exposure": 0.40, "min_position_notional": 200.0, "tags": ["BOND", "TLT"]},
    "commodity": {"vol": 0.25, "max_exposure": 0.15, "min_position_notional": 150.0, "tags": ["GLD", "SLV"]},
    "etf":    {"vol": 0.15, "max_exposure": 0.50, "min_position_notional": 100.0, "tags": ["SPY", "QQQ"]},
}

DEFAULT_WEIGHTS = {
    "crypto": 0.40,
    "stock": 0.40,
    "etf": 0.10,
    "cash": 0.10,
}

_SECTOR_TO_CLASS = {
    "tech": "stock", "finance": "stock", "energy": "stock",
    "healthcare": "stock", "consumer": "stock", "communication": "stock",
    "industrial": "stock", "utility": "stock", "real_estate": "stock",
    "etf": "etf", "bond": "bond", "commodity": "commodity",
}


@dataclass
class AssetClassAllocation:
    name: str                        # asset class label
    weight: float                    # target portfolio weight (0.0-1.0)
    current_exposure: float          # current allocation
    symbols: List[str] = field(default_factory=list)
    signals: Dict[str, str] = field(default_factory=dict)
    max_exposure: float = 0.0
    volatility: float = 0.0
    min_notional: float = 0.0
    reason: str = ""


def _classify_symbol(symbol: str, sector: str = None) -> Tuple[str, str]:
    """Classify a symbol into an asset class and sub-class.

    Uses '/' convention: crypto pairs have '/', others are stocks/forex.
    """
    if "/" in symbol:
        base, quote = symbol.split("/", 1)
        if quote.upper() in ("USD", "USDT", "USDC"):
            base_upper = base.upper()
            if base_upper in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LTC", "BCH", "DOT", "AVAX"):
                return ("crypto", base_upper)
            return ("forex", base_upper)
        return ("forex", f"{base}/{quote}")

    sym_upper = symbol.upper()
    if sym_upper in ("SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "VEA", "VWO"):
        return ("etf", sym_upper)
    if sym_upper in ("TLT", "BND", "AGG", "LQD", "HYG", "IEF"):
        return ("bond", sym_upper)
    if sym_upper in ("GLD", "SLV", "USO", "UNG", "DBC"):
        return ("commodity", sym_upper)

    if sector and sector in _SECTOR_TO_CLASS:
        return (_SECTOR_TO_CLASS[sector], sym_upper)

    return ("stock", sym_upper)


def _build_allocation_prompt(
    classes: Dict[str, AssetClassAllocation],
    portfolio_value: float,
    cash: float,
    fee_summary: str,
    regime_hint: str,
) -> str:
    prefix = (
        f"You are a portfolio asset allocator. Current portfolio: ${portfolio_value:,.2f} total, "
        f"${cash:,.2f} cash. Propose asset class target weights (0.0-1.0, sum ≤ 1.0).\n\n"
    )
    prefix += "Constraints:\n"
    prefix += "  - Crypto max 50%, stocks max 60%, ETFs max 50%, cash reserve min 5%\n"
    prefix += "  - Higher volatility classes need wider stops and smaller positions\n"
    prefix += "  - Respect the round-trip fee cost per class — small positions in high-fee classes lose to commissions\n\n"
    prefix += f"Fee summary:\n{fee_summary}\n"
    if regime_hint:
        prefix += f"Regime: {regime_hint}\n"

    prefix += "\nCurrent allocations (class | target_weight | current_exposure | symbols):\n"
    for _, ac in sorted(classes.items()):
        sym_list = ", ".join(ac.symbols[:4])
        if len(ac.symbols) > 4:
            sym_list += f" (+{len(ac.symbols) - 4} more)"
        prefix += (
            f"  {ac.name:12s} | target={ac.weight:.2f} | current=${ac.current_exposure:,.0f} "
            f"| vol={ac.volatility:.1%} | {sym_list}\n"
        )

    prefix += (
        "\nReturn JSON only: {\"classes\": "
        "{\"crypto\": 0.40, \"stock\": 0.40, ...}, \"reason\": \"brief strategy\"}\n"
    )
    return prefix


def _heuristic_weights(
    classes: Dict[str, AssetClassAllocation],
    portfolio_value: float,
    cash: float,
) -> Dict[str, float]:
    cash_reserve = max(0.05, cash / max(portfolio_value, 1))
    budget = 1.0 - cash_reserve
    weights: Dict[str, float] = {"cash": cash_reserve}

    active = [(k, v) for k, v in classes.items()
              if v.symbols and k != "cash"]
    if not active:
        return {"cash": 1.0}

    n = len(active)
    for name, ac in active:
        base = budget * (1.0 / n)
        adj = base * (0.18 / max(ac.volatility, 0.05))
        weights[name] = min(adj, ac.max_exposure)

    total = sum(weights.values()) - cash_reserve
    if total > 0 and total != budget:
        scale = budget / total
        for k in weights:
            if k != "cash":
                weights[k] = min(weights[k] * scale, classes[k].max_exposure)

    return weights


class AssetClassAllocator:
    """Model-driven allocation across asset classes.

    Usage:
        allocator = AssetClassAllocator(llm_context_fn)
        results = allocator.allocate(all_signals, prices, portfolio, fee_context)
        # results maps symbol -> adjusted_weight for PortfolioOptimizer
    """

    def __init__(self, llm_call_fn=None, use_model: bool = True):
        self._llm_call = llm_call_fn
        self._use_model = use_model

    def classify(self, symbols: List[str], sectors: Dict[str, str] = None) -> Dict[str, AssetClassAllocation]:
        sectors = sectors or {}
        classes: Dict[str, AssetClassAllocation] = {}

        for sym in symbols:
            asset_class, sub = _classify_symbol(sym, sectors.get(sym))
            if asset_class not in classes:
                rules = ASSET_CLASS_RULES.get(asset_class, ASSET_CLASS_RULES["stock"])
                classes[asset_class] = AssetClassAllocation(
                    name=asset_class,
                    weight=DEFAULT_WEIGHTS.get(asset_class, 0.10),
                    current_exposure=0.0,
                    symbols=[],
                    signals={},
                    max_exposure=rules["max_exposure"],
                    volatility=rules["vol"],
                    min_notional=rules["min_position_notional"],
                )
            classes[asset_class].symbols.append(sym)

        return classes

    def allocate(
        self,
        signals: List[Any],
        prices: Dict[str, float],
        portfolio_value: float,
        cash: float,
        positions: Dict[str, float],
        fee_context: Optional["AccountContext"] = None,
        regime_hint: str = "",
    ) -> Dict[str, AssetClassAllocation]:
        active_symbols = list(set(s.symbol for s in signals if s.action in ("BUY", "SELL")))
        if not active_symbols:
            return {}

        classes = self.classify(active_symbols)

        # Compute current exposures
        for name, ac in classes.items():
            for sym in ac.symbols:
                pos_qty = positions.get(sym, 0)
                price = prices.get(sym, 0)
                ac.current_exposure += pos_qty * price

        # Build fee summary
        fee_summary = ""
        if fee_context:
            lines = []
            for name, ac in classes.items():
                sample_sym = ac.symbols[0] if ac.symbols else "default"
                buy, sell, rt, rt_pct = fee_context.fee_impact(sample_sym, ac.min_notional)
                lines.append(
                    f"  {name}: ~${rt:.2f} round-trip ({rt_pct:.1f}%) "
                    f"at ${ac.min_notional:.0f} min position"
                )
            fee_summary = "\n".join(lines)

        # Get weights: LLM if available, else heuristic
        weights: Dict[str, float]
        if self._use_model and self._llm_call and len(classes) > 1:
            prompt = _build_allocation_prompt(classes, portfolio_value, cash, fee_summary, regime_hint)
            try:
                response = self._llm_call(prompt)
                parsed = self._parse_response(response, classes)
                if parsed:
                    weights = parsed
                else:
                    weights = _heuristic_weights(classes, portfolio_value, cash)
                    logger.debug("Asset allocator: LLM parse failed, using heuristic weights")
            except Exception as e:
                logger.warning(f"Asset allocator LLM call failed: {e}, using heuristic")
                weights = _heuristic_weights(classes, portfolio_value, cash)
        else:
            weights = _heuristic_weights(classes, portfolio_value, cash)

        # Apply weights
        for name, ac in classes.items():
            w = weights.get(name, ac.weight)
            ac.weight = w
            budget = w * portfolio_value

            per_sym_share = budget / max(len(ac.symbols), 1)
            for sym in ac.symbols:
                price = prices.get(sym, 1)
                if price <= 0:
                    continue
                qty = per_sym_share / price
                min_qty = ac.min_notional / price
                ac.signals[sym] = (
                    f"class_budget={w:.2%} "
                    f"qty_est={qty:.4f} "
                    f"min_qty={min_qty:.4f} "
                    f"vol={ac.volatility:.0%}"
                )

            ac.reason = (
                f"weight={w:.2%} budget=${budget:,.0f} "
                f"vol={ac.volatility:.0%} max_exp={ac.max_exposure:.0%}"
            )

        logger.info(
            f"Asset allocator: {len(classes)} classes → "
            + ", ".join(f"{ac.name}={ac.weight:.0%}" for _, ac in sorted(classes.items()))
        )
        return classes

    def _parse_response(self, response: str, classes: Dict[str, AssetClassAllocation]) -> Optional[Dict[str, float]]:
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("{") and "classes" in line:
                try:
                    data = json.loads(line)
                    cls = data.get("classes", {})
                    weights = {"cash": 0.05}
                    for name, w in cls.items():
                        if isinstance(w, (int, float)):
                            weights[name] = float(w)
                    if sum(weights.values()) <= 1.05:
                        return weights
                except (json.JSONDecodeError, ValueError):
                    continue
        return None

    def adjust_signals(
        self,
        signals: List[Any],
        classes: Dict[str, AssetClassAllocation],
        portfolio_value: float,
    ) -> List[Any]:
        for sig in signals:
            sym = sig.symbol
            for ac in classes.values():
                if sym in ac.symbols and ac.weight > 0:
                    sig.position_pct = min(sig.position_pct, ac.weight * 1.2)
                    if ac.weight < 0.03:
                        sig.confidence = min(sig.confidence, 0.15)
                        sig.reason += f" [class_underweight:{ac.name}={ac.weight:.0%}]"
                    break
        return signals
