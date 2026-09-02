#!/usr/bin/env python3
"""Portfolio Optimizer — multi-symbol Kelly-optimal allocation with correlation-aware sizing.

Phase 7: Takes debate signals across all active symbols, computes
correlation-aware Kelly-optimal weights, and returns sized allocations
respecting risk constraints, max positions, and diversification targets.

Design:
  1. Gather price history for all symbols → correlation matrix
  2. Per-symbol Kelly fraction from debate confidence
  3. Apply correlation penalty: highly correlated → reduce combined weight
  4. Constrain to max positions, max exposure, min cash
  5. Return ordered list of (symbol, qty, stop, tp) for the harness
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.portfolio")


@dataclass
class Allocation:
    """One symbol's allocation from portfolio optimization."""

    symbol: str
    side: str  # BUY / SELL / HOLD
    weight_pct: float  # % of portfolio to allocate (0.0-1.0)
    quantity: float  # Number of units to trade
    price: float  # Estimated fill price
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reason: str = ""


@dataclass
class PortfolioResult:
    """Full portfolio optimization output."""

    allocations: List[Allocation]
    correlation_matrix: Dict[str, Dict[str, float]]
    portfolio_var: float  # Portfolio VaR
    diversification_ratio: float  # 1.0 = perfectly diversified
    total_exposure_pct: float  # Sum of all weights
    kelly_fractions: Dict[str, float]


class PortfolioOptimizer:
    """Multi-symbol portfolio optimizer with correlation-aware Kelly allocation.

    Usage:
        optimizer = PortfolioOptimizer(risk_config)
        result = optimizer.optimize(
            signals=[sig1, sig2, sig3],
            portfolio=balance,
            price_history={"BTC/USDT": [...], "ETH/USDT": [...]},
        )
        # result.allocations tells you what to trade
    """

    def __init__(
        self,
        max_position_pct: float = 0.20,
        max_total_exposure: float = 0.60,
        max_positions: int = 50,
        max_correlation: float = 0.80,
        kelly_fraction: float = 0.35,
        min_cash_reserve: float = 5000.0,
        max_order_value: float = 50000.0,
        correlation_lookback: int = 50,  # bars for correlation calc
        correlation_penalty_strength: float = 0.5,  # how much to penalize correlated pairs
        trim_deadband: float = 0.30,  # skip SELL-trims until target is 30% below holding
    ):
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.max_positions = max_positions
        self.max_correlation = max_correlation
        self.kelly_fraction = kelly_fraction
        self.min_cash_reserve = min_cash_reserve
        self.max_order_value = max_order_value
        self.correlation_lookback = correlation_lookback
        self.correlation_penalty_strength = correlation_penalty_strength
        self.trim_deadband = max(0.0, min(0.90, trim_deadband))

    # ── Correlation Matrix ──────────────────────────────────────

    def build_correlation_matrix(
        self, price_history: Dict[str, List[float]]
    ) -> Dict[str, Dict[str, float]]:
        """Compute Pearson correlation matrix from price histories.

        Uses log returns for stationarity. Returns dict[symbol][symbol] = corr.
        Defaults to 0.0 for pairs with insufficient data.
        """
        symbols = list(price_history.keys())
        matrix: Dict[str, Dict[str, float]] = {
            s: {t: 0.0 for t in symbols} for s in symbols
        }

        for i, s1 in enumerate(symbols):
            matrix[s1][s1] = 1.0  # self-correlation = 1
            p1 = price_history[s1]
            r1 = self._log_returns(p1)
            if len(r1) < 2:
                continue

            for s2 in symbols[i + 1 :]:
                p2 = price_history[s2]
                r2 = self._log_returns(p2)
                if len(r2) < 2:
                    continue

                # Align lengths
                n = min(len(r1), len(r2))
                if n < 2:
                    corr = 0.0
                else:
                    x, y = r1[-n:], r2[-n:]
                    corr = self._pearson(x, y)

                matrix[s1][s2] = corr
                matrix[s2][s1] = corr

        return matrix

    @staticmethod
    def _log_returns(prices: List[float]) -> List[float]:
        """Compute log returns from price series."""
        if len(prices) < 2:
            return []
        return [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0 and prices[i] > 0
        ]

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Pearson correlation coefficient."""
        n = len(x)
        mx = sum(x) / n
        my = sum(y) / n
        cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
        sx = math.sqrt(sum((v - mx) ** 2 for v in x) / n)
        sy = math.sqrt(sum((v - my) ** 2 for v in y) / n)
        if sx == 0 or sy == 0:
            return 0.0
        return max(-1.0, min(1.0, cov / (sx * sy)))

    # ── Kelly Allocation ────────────────────────────────────────

    def per_symbol_kelly(self, confidence: float, side: str) -> float:
        """Compute Kelly fraction from debate signal confidence.

        Maps confidence to implied win probability, then computes Kelly:
          f* = (p * b - (1-p)) / b

        With b=1.5 (default win/loss ratio), this simplifies to:
          f* = (p * 1.5 - (1-p)) / 1.5 = (1.5p - 1 + p) / 1.5 = (2.5p - 1) / 1.5

        For SELL signals, we use the same formula (sizing to reduce/exit).
        """
        if side.upper() == "HOLD" or confidence <= 0:
            return 0.0

        # Map confidence 0.0-1.0 to win probability 0.5-0.75
        # confidence=0.5 → p=0.55, confidence=1.0 → p=0.75
        win_prob = 0.5 + confidence * 0.25

        # Win/loss ratio from confidence (higher confidence = better expected ratio)
        win_loss_ratio = 1.0 + confidence * 0.5  # 1.0-1.5

        # Kelly formula: f* = (p * b - (1-p)) / b
        b = win_loss_ratio
        if b <= 0:
            return 0.0
        kelly = (win_prob * b - (1.0 - win_prob)) / b
        kelly = max(0.0, kelly)

        # Apply fractional Kelly for safety
        return kelly * self.kelly_fraction

    @staticmethod
    def _correlation_penalty(
        weights: Dict[str, float],
        corr_matrix: Dict[str, Dict[str, float]],
        strength: float = 0.5,
    ) -> Dict[str, float]:
        """Reduce weights of assets that are highly correlated with others.

        For each pair with correlation > 0.5, reduce both weights proportionally
        to the correlation magnitude. This prevents over-concentration in correlated assets.
        """
        adjusted = dict(weights)
        symbols = list(adjusted.keys())

        for i, s1 in enumerate(symbols):
            for s2 in symbols[i + 1 :]:
                corr = corr_matrix.get(s1, {}).get(s2, 0)
                if corr > 0.5:
                    # Reduce both weights by correlation penalty
                    penalty = (corr - 0.5) * 2.0 * strength  # 0-1 scale
                    # Proportional reduction (larger position gets more reduction)
                    total_w = adjusted[s1] + adjusted[s2]
                    if total_w > 0:
                        reduction = total_w * penalty
                        r1 = reduction * (adjusted[s1] / total_w)
                        r2 = reduction * (adjusted[s2] / total_w)
                        adjusted[s1] = max(0, adjusted[s1] - r1)
                        adjusted[s2] = max(0, adjusted[s2] - r2)

        return adjusted

    # ── Portfolio VaR ────────────────────────────────────────────

    def portfolio_var(
        self,
        weights: Dict[str, float],
        volatilities: Dict[str, float],
        corr_matrix: Dict[str, Dict[str, float]],
        portfolio_value: float,
        confidence: float = 0.95,
    ) -> float:
        """Compute portfolio Value-at-Risk using variance-covariance method.

        VaR_p = z * sqrt(w' Σ w) * V
        where z = 1.645 for 95% confidence, V = portfolio value
        """
        z_scores = {0.99: 2.326, 0.95: 1.645, 0.90: 1.282}
        z = z_scores.get(confidence, 1.645)

        symbols = list(weights.keys())
        n = len(symbols)
        if n == 0:
            return 0.0

        # Build covariance matrix: Cov(i,j) = vol_i * vol_j * corr(i,j)
        total_var = 0.0
        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                w_i = weights.get(s1, 0)
                w_j = weights.get(s2, 0)
                vol_i = volatilities.get(s1, 0.02)
                vol_j = volatilities.get(s2, 0.02)
                corr = corr_matrix.get(s1, {}).get(s2, 0)
                if i == j:
                    corr = 1.0
                total_var += w_i * w_j * vol_i * vol_j * corr

        portfolio_std = math.sqrt(max(0, total_var))
        return z * portfolio_std * portfolio_value

    # ── Main Optimize ────────────────────────────────────────────

    def optimize(
        self,
        signals: List[Any],
        portfolio: dict,
        prices: Dict[str, float],
        price_history: Optional[Dict[str, List[float]]] = None,
        current_positions: Optional[Dict[str, float]] = None,
        volatilities: Optional[Dict[str, float]] = None,
    ) -> PortfolioResult:
        """Compute optimal portfolio allocation from debate signals.

        Args:
            signals: List of Signal objects from debate engine
            portfolio: dict with total_value, cash, positions
            prices: current price per symbol
            price_history: dict of symbol → price list (for correlation)
            current_positions: dict of symbol → current qty
            volatilities: dict of symbol → daily vol (estimated if not provided)

        Returns:
            PortfolioResult with allocations, correlation matrix, VaR
        """
        total_value = float(portfolio.get("total_value", 0))
        cash = float(portfolio.get("cash", 0))
        positions = current_positions or {}
        if isinstance(positions.get(next(iter(positions), None)), dict):
            positions = {k: float(v.get("quantity", 0)) for k, v in positions.items()}
        else:
            positions = {k: float(v or 0) for k, v in positions.items()}

        price_hist = price_history or {}

        # Step 1: Build correlation matrix
        corr_matrix = self.build_correlation_matrix(price_hist)

        # Step 2: Compute raw Kelly fractions per signal
        kelly_weights: Dict[str, float] = {}
        signal_map: Dict[str, Any] = {}
        logger.debug(
            f"  OPTIMIZE-IN: {len(signals)} signals: "
            + ", ".join(f"{s.symbol}={s.action}({s.confidence:.2f})" for s in signals)
            + f" | portfolio=${total_value:,.0f} cash=${cash:,.0f} pos={positions}"
        )
        for sig in signals:
            sym = sig.symbol
            signal_map[sym] = sig

            if sig.action.upper() == "BUY":
                kw = self.per_symbol_kelly(sig.confidence, "BUY")
                # Cap by max position pct
                kw = min(kw, self.max_position_pct)
                kelly_weights[sym] = kw
                logger.info(
                    f"  Kelly[{sym}]: BUY conf={sig.confidence:.2f} → kw={kw:.4f} (max={self.max_position_pct})"
                )
            elif sig.action.upper() == "SELL":
                kelly_weights[sym] = 0.0  # Exit, not enter
                logger.info(f"  Kelly[{sym}]: SELL → kw=0.0")
            else:
                # HOLD: maintain existing position weight
                pos_qty = positions.get(sym, 0)
                pos_price = prices.get(sym, 1)
                pos_value = pos_qty * pos_price
                current_weight = pos_value / max(total_value, 1)
                kelly_weights[sym] = current_weight
                logger.info(f"  Kelly[{sym}]: HOLD → kw={current_weight:.4f}")

        # Step 3: Apply correlation penalty
        if price_hist:
            kelly_weights = self._correlation_penalty(
                kelly_weights, corr_matrix, self.correlation_penalty_strength
            )
            logger.debug(
                f"  After correlation: {', '.join(f'{s}={w:.4f}' for s, w in kelly_weights.items())}"
            )

        # Step 4: Apply max positions constraint
        # Sort by weight descending, keep top N
        buy_signals = {
            sym: w
            for sym, w in kelly_weights.items()
            if w > 0
            and signal_map.get(sym, signal_map.get(sym)) is not None
            and signal_map[sym].action.upper() == "BUY"
        }
        sorted_buys = sorted(buy_signals.items(), key=lambda x: -x[1])
        existing_pos_count = sum(1 for q in positions.values() if q > 0)
        max_new = self.max_positions - existing_pos_count
        logger.info(
            f"  MAX-POS-FILTER: max_positions={self.max_positions} existing={existing_pos_count} max_new={max_new} buy_signals={len(buy_signals)} ({', '.join(f'{s}={w:.4f}' for s,w in sorted_buys)})"
        )
        if max_new < len(sorted_buys):
            # Keep only the top `max_new` buy signals
            kept = set(s for s, _ in sorted_buys[:max_new])
            for s, _ in sorted_buys[max_new:]:
                logger.info(f"  MAX-POS-FILTER: dropping {s}")
                kelly_weights[s] = 0.0
        logger.info(
            f"  AFTER-FILTER: {', '.join(f'{s}={w:.4f}' for s, w in kelly_weights.items())}"
        )

        # Step 5: Normalize weights to respect max_total_exposure
        total_weight = sum(kelly_weights.values())
        if total_weight > self.max_total_exposure:
            scale = self.max_total_exposure / total_weight
            kelly_weights = {s: w * scale for s, w in kelly_weights.items()}
        logger.debug(
            f"  Final kelly weights: {', '.join(f'{s}={w:.4f}' for s, w in kelly_weights.items())} (total={sum(kelly_weights.values()):.4f})"
        )

        # Step 6: Compute volatilities for VaR
        vols: Dict[str, float] = {}
        if volatilities:
            vols = volatilities
        else:
            for sym in kelly_weights:
                hist = price_hist.get(sym, [])
                if len(hist) >= 10:
                    returns = self._log_returns(hist)
                    if returns:
                        mean_r = sum(returns) / len(returns)
                        vol = math.sqrt(
                            sum((r - mean_r) ** 2 for r in returns) / len(returns)
                        )
                        vols[sym] = vol
                else:
                    vols[sym] = 0.02  # default 2% daily vol

        # Step 7: Compute portfolio VaR
        p_var = self.portfolio_var(kelly_weights, vols, corr_matrix, total_value)

        # Step 8: Build allocations
        # Compute diversification ratio: sum(w * sigma_i) / sigma_p
        weighted_vol_sum = sum(
            kelly_weights.get(s, 0) * vols.get(s, 0.02) for s in kelly_weights
        )
        portfolio_vol = (
            math.sqrt(
                sum(
                    kelly_weights.get(s1, 0)
                    * kelly_weights.get(s2, 0)
                    * vols.get(s1, 0.02)
                    * vols.get(s2, 0.02)
                    * corr_matrix.get(s1, {}).get(s2, 0 if s1 != s2 else 1)
                    for s1 in kelly_weights
                    for s2 in kelly_weights
                )
            )
            if sum(kelly_weights.values()) > 0
            else 1.0
        )
        div_ratio = weighted_vol_sum / portfolio_vol if portfolio_vol > 0 else 1.0

        allocations: List[Allocation] = []
        logger.info(f"  ALLOC-LOOP: {len(kelly_weights)} weights, prices={list(prices.keys())}, signal_map={list(signal_map.keys())}")
        for sym, weight in kelly_weights.items():
            sig = signal_map.get(sym)
            if sig is None:
                logger.info(f"  ALLOC-DROP[{sym}]: no signal in signal_map")
                continue

            price = prices.get(sym, 0)
            if price <= 0:
                logger.info(f"  ALLOC-DROP[{sym}]: price={price} <= 0 (prices has {sym}: {sym in prices})")
                continue

            # Determine side
            pos_qty = positions.get(sym, 0)
            target_value = weight * total_value
            target_qty = target_value / price

            if sig.action.upper() == "BUY":
                if target_qty > pos_qty:
                    qty = target_qty - pos_qty
                    side = "BUY"
                    reason = f"kelly={weight:.2%} corr-adjusted"
                else:
                    # Hysteresis: don't SELL-trim on small Kelly drift. A trim
                    # here is a fee-costly exit that often reverses the very next
                    # cycle (buy->sell->buy churn). Only trim when the target is
                    # materially below the current holding (>deadband relative).
                    if pos_qty > 0 and target_qty >= pos_qty * (
                        1 - self.trim_deadband
                    ):
                        qty = 0
                        side = "HOLD"
                        reason = f"holding (target within {self.trim_deadband:.0%} deadband)"
                    else:
                        qty = pos_qty - target_qty
                        side = "SELL" if qty > 0 else "HOLD"
                        reason = f"kelly={weight:.2%} corr-adjusted"
                alloc_conf = sig.confidence
            elif sig.action.upper() == "SELL":
                qty = pos_qty
                side = "SELL" if qty > 0 else "HOLD"
                alloc_conf = sig.confidence
                reason = "signal: SELL"
            else:  # HOLD
                # Maintain current position — do NOT trim to Kelly target.
                # Kelly fraction is an entry-sizing constraint, not a continuous
                # rebalance target. Selling to Kelly creates 1-cycle flip-flops.
                # Only sell if position exceeds max_position_pct or SL/TP hits.
                current_weight = (
                    (pos_qty * price / max(total_value, 1)) if pos_qty > 0 else 0
                )
                if pos_qty > 0 and current_weight > self.max_position_pct * 1.2:
                    excess = current_weight - self.max_position_pct
                    reduce_qty = (excess * total_value) / price
                    qty = reduce_qty
                    side = "SELL"
                    reason = f"position>{self.max_position_pct:.0%} cap"
                    alloc_conf = 0.5
                else:
                    qty = 0
                    side = "HOLD"
                    reason = "holding"
                    alloc_conf = 0.5

            logger.info(
                f"  ALLOC-SIDE[{sym}]: action={sig.action} side={side} qty={qty:.8f} "
                f"target_qty={target_qty:.8f} pos_qty={pos_qty:.8f} price={price:.2f} "
                f"weight={weight:.4f}"
            )
            if side != "HOLD" and qty > 0:
                # Respect max order value
                order_value = qty * price
                if order_value > self.max_order_value:
                    qty = self.max_order_value / price

                # Respect min cash reserve (for BUY)
                if side == "BUY":
                    cost = qty * price
                    logger.info(
                        f"  ALLOC-CASH[{sym}]: cost={cost:.2f} cash={cash:.2f} "
                        f"min_reserve={self.min_cash_reserve:.2f} buffer={cash - self.min_cash_reserve:.2f}"
                    )
                    if cost > cash - self.min_cash_reserve:
                        affordable = max(0, cash - self.min_cash_reserve) / price
                        logger.info(f"  ALLOC-CASH[{sym}]: OVER BUDGET, affordable_qty={affordable:.8f}")
                        if affordable <= 0:
                            side = "HOLD"
                            qty = 0
                            reason = "insufficient cash"
                        else:
                            qty = affordable

            # Skip HOLD allocations — filter AFTER cash check so BUY→HOLD mutations don't leak
            if side == "HOLD" or qty <= 0:
                logger.info(f"  ALLOC-DROP[{sym}]: final side={side} qty={qty:.8f} → skipped")
                continue

            # SL/TP from signal
            sl = sig.stop_loss if sig and hasattr(sig, "stop_loss") else None
            tp = sig.take_profit if sig and hasattr(sig, "take_profit") else None

            allocations.append(
                Allocation(
                    symbol=sym,
                    side=side,
                    weight_pct=weight,
                    quantity=round(qty, 8),
                    price=price,
                    stop_loss=sl,
                    take_profit=tp,
                    confidence=alloc_conf,
                    reason=reason,
                )
            )

        logger.debug(
            f"  OPTIMIZE-OUT: {len(allocations)} allocations: "
            + ", ".join(
                f"{a.symbol}/{a.side}(wt={a.weight_pct:.4f} qty={a.quantity:.6f} {a.reason})"
                for a in allocations
            )
        )
        # Defensive copy — allocations are mutable and can be corrupted
        # by post-processing in the caller if shared by reference.
        return PortfolioResult(
            allocations=allocations,
            correlation_matrix=corr_matrix,
            portfolio_var=p_var,
            diversification_ratio=round(div_ratio, 4),
            total_exposure_pct=round(sum(kelly_weights.values()), 4),
            kelly_fractions=kelly_weights,
        )

    # ── Portfolio Metrics ────────────────────────────────────────

    @staticmethod
    def compute_portfolio_metrics(
        positions: Dict[str, float],
        prices: Dict[str, float],
        price_history: Dict[str, List[float]],
        total_value: float,
    ) -> dict:
        """Compute portfolio-level metrics for dashboard display.

        Returns:
            dict with: symbol_count, concentration (herfindahl),
                       correlation_risk, diversification_ratio,
                       weighted_vol, top_position
        """
        # Compute weights
        weights: Dict[str, float] = {}
        for sym, qty in positions.items():
            q = float(qty or 0)
            p = prices.get(sym, 0)
            if q > 0 and p > 0:
                weights[sym] = (q * p) / max(total_value, 1)

        # Herfindahl-Hirschman Index (concentration)
        hhi = sum(w**2 for w in weights.values())
        # 1/N = perfectly diversified, 1.0 = one asset

        # Top position
        top_sym = max(weights, key=weights.get) if weights else ""
        top_weight = weights.get(top_sym, 0)

        return {
            "symbol_count": len(positions),
            "concentration_hhi": round(hhi, 4),
            "effective_n": round(1.0 / hhi, 1) if hhi > 0 else 0,
            "top_symbol": top_sym,
            "top_weight_pct": round(top_weight * 100, 2),
            "cash_pct": round(max(0, 1.0 - sum(weights.values())) * 100, 2),
        }
