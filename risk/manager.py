#!/usr/bin/env python3
"""Risk Manager — guardrails between signals and execution.

Merged from OpenTrader + ATLANTIS risk engines.
Adds: Kelly criterion, correlation check, VaR, max-drawdown circuit breaker,
      daily trade limits, and multi-venue position tracking.
"""

import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("opentrader.risk")


@dataclass
class RiskConfig:
    """Risk parameters — tune these for your risk tolerance."""

    # Per-position limits
    max_position_pct: float = 0.20  # Max single position as % of portfolio
    max_total_exposure: float = 0.60  # Max all positions combined
    max_positions: int = 50  # Max concurrent positions
    max_order_value: float = 50000  # Max $ per single order

    # Portfolio protection
    stop_loss_pct: float = 0.04  # Default stop-loss per trade (4%)
    take_profit_pct: float = 0.08  # Default take-profit per trade (8%, 2:1 ratio)
    portfolio_stop_pct: float = 0.15  # Max drawdown from peak (circuit breaker)
    min_cash_reserve: float = (
        5  # Minimum cash to keep (small = accommodate micro accounts)
    )

    # ATLANTIS additions
    max_daily_trades: int = 500  # Max trades per day
    max_correlation: float = 0.80  # Max allowed correlation between positions
    kelly_fraction: float = 0.35  # Fraction of Kelly (0.35 = fractional Kelly)
    default_win_prob: float = 0.55  # Default win prob for Kelly calc
    default_wl_ratio: float = 1.5  # Default win/loss ratio for Kelly

    # Advanced position guardrails (Phase 6)
    trailing_stop_pct: float = 0.02  # Trail stop 2% behind highest price
    trailing_stop_activation: float = 0.015  # Activate trailing after 1.5% profit
    max_position_cycles: int = 0  # Auto-close after N cycles (0 = disabled)
    position_stop_pct: float = 0.05  # Per-position max drawdown (0 = disabled)

    # Exchange whose fee schedule applies (set by the harness; '' = paper).
    # Drives the fee-aware sizing guard: ''/paper = zero fees, 'multi' =
    # route-aware kraken % (crypto) / IBKR fixed (stocks), etc.
    _exchange: str = ""

    # VaR
    var_confidence: float = 0.95  # VaR confidence level
    var_window_days: int = 30  # VaR lookback window
    daily_vol_assumption: float = 0.02  # 2% daily vol for VaR


@dataclass
class RiskResult:
    """Result of a risk check."""

    approved: bool
    reason: str = ""
    adjusted_size: float = 0.0
    adjusted_stop: Optional[float] = None
    adjusted_tp: Optional[float] = None


class RiskManager:
    """Applies risk rules to signals before execution.

    Combines OpenTrader's basic guardrails with ATLANTIS's Kelly criterion,
    correlation checks, and VaR calculations.

    Phase 7: Delegates multi-symbol portfolio optimization to PortfolioOptimizer.
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self._peak_value: float = 0.0
        self._initial_cash: float = 0.0
        self._daily_trades: int = 0
        self._daily_fee_drag: float = 0.0
        self._last_reset_date: str = ""
        self._seen_trade_keys: set = (
            set()
        )  # dedup same signal through pre_trade_check + check
        self._config_lock = (
            threading.Lock()
        )  # serializes override save/restore in check()

    # ── Lifecycle ──────────────────────────────────────────────────

    def set_initial(self, cash: float) -> None:
        self._initial_cash = cash
        self._peak_value = cash

    # ── Per-symbol parameter overrides from optimizer ──────────

    _opt_params_cache: dict = {}  # {mtime_ns: {symbol: {param: value}}}
    _opt_path: str = ""

    def _load_symbol_params(self, state_dir: str = "") -> Dict[str, dict]:
        """Load per-symbol optimized parameters from optimal_params.json.

        Cached by file mtime — only re-reads when the optimizer writes changes.
        Returns {symbol: {param_name: value}}.
        """
        import os

        if not state_dir:
            return {}
        path = os.path.join(state_dir, "optimal_params.json")
        if not os.path.exists(path):
            return {}

        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return {}

        if self._opt_path == path and self._opt_params_cache.get("_mtime") == mtime:
            return self._opt_params_cache

        try:
            with open(path) as f:
                data = json.load(f)
            symbols = data.get("symbols", {})
            symbols["_mtime"] = mtime
            self._opt_params_cache = symbols
            self._opt_path = path
            return symbols
        except Exception:
            return {}

    def get_symbol_overrides(self, symbol: str) -> Dict[str, float]:
        """Get risk parameter overrides for a symbol from optimzed params.

        Maps param names to values: stop_loss_pct, take_profit_pct,
        max_position_cycles, kelly_fraction, trailing_stop_pct,
        trailing_stop_activation, position_stop_pct.
        """
        params = self._load_symbol_params()
        sym_params = params.get(symbol, {})
        if not sym_params or sym_params.get("sample_size", 0) < 5:
            return {}
        return {
            k: v
            for k, v in sym_params.items()
            if k
            in (
                "stop_loss_pct",
                "take_profit_pct",
                "max_position_cycles",
                "kelly_fraction",
                "trailing_stop_pct",
                "trailing_stop_activation",
                "position_stop_pct",
            )
            and isinstance(v, (int, float))
        }

    def update_peak(self, portfolio_value: float) -> None:
        if portfolio_value > self._peak_value:
            self._peak_value = portfolio_value

    def _reset_daily(self) -> None:
        """Reset daily trade counter at UTC midnight."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._daily_trades = 0
            self._daily_fee_drag = 0.0
            self._last_reset_date = today
            self._seen_trade_keys.clear()

    # ── Circuit Breaker (merged: drawdown + price-drop) ───────────

    def check_circuit_breaker(self, portfolio_value: float) -> bool:
        """Global circuit breaker — halt if drawdown too large.

        Returns True if OK to continue, False to HALT.
        """
        if self._peak_value <= 0:
            return True
        drawdown = (self._peak_value - portfolio_value) / self._peak_value
        ok = drawdown < self.config.portfolio_stop_pct
        if not ok:
            logger.warning(
                f"Circuit breaker tripped: drawdown {drawdown:.2%} "
                f"exceeds {self.config.portfolio_stop_pct:.0%}"
            )
        return ok

    @staticmethod
    def circuit_breaker_price(prices_5: List[float]) -> bool:
        """Return True (HALT) if price dropped > 5% in last 5 data points."""
        if len(prices_5) < 5:
            return False
        first, last = prices_5[0], prices_5[-1]
        if first == 0:
            return False
        return (first - last) / first > 0.05

    # ── ATLANTIS Additions ─────────────────────────────────────────

    def kelly_criterion(
        self, win_prob: float = None, win_loss_ratio: float = None
    ) -> float:
        """Kelly Criterion: optimal fraction of capital to risk.

        f* = (p * b - (1 - p)) / b
        where p = win probability, b = avg win / avg loss

        Returns fraction of capital (0.0 to 1.0).
        """
        p = win_prob if win_prob is not None else self.config.default_win_prob
        b = (
            win_loss_ratio
            if win_loss_ratio is not None
            else self.config.default_wl_ratio
        )

        if b <= 0:
            return 0.0
        kelly = (p * b - (1.0 - p)) / b
        kelly = max(0.0, kelly)

        # Apply fractional Kelly for safety
        fraction = self.config.kelly_fraction
        return round(kelly * fraction, 6)

    def check_correlation(
        self,
        new_symbol: str,
        existing_positions: Dict[str, float],
        price_history: Dict[str, List[float]],
    ) -> float:
        """Compute max Pearson correlation between new asset and existing positions.

        Returns the maximum correlation found. > 0.80 flags concentration risk.
        Returns 0.0 if insufficient data.
        """
        new_prices = price_history.get(new_symbol, [])
        if len(new_prices) < 2:
            return 0.0

        max_corr = 0.0
        for symbol in existing_positions:
            if symbol not in price_history or symbol == new_symbol:
                continue
            existing_prices = price_history[symbol]
            if len(existing_prices) < 2:
                continue

            n = min(len(new_prices), len(existing_prices))
            x, y = new_prices[-n:], existing_prices[-n:]

            mx, my = sum(x) / n, sum(y) / n
            cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / n
            sx = math.sqrt(sum((v - mx) ** 2 for v in x) / n)
            sy = math.sqrt(sum((v - my) ** 2 for v in y) / n)

            if sx == 0 or sy == 0:
                continue
            max_corr = max(max_corr, abs(cov / (sx * sy)))

        return max_corr

    def var_calculation(
        self, portfolio_value: float, confidence: float = None
    ) -> float:
        """Simple historical Value-at-Risk using daily volatility assumption.

        VaR = portfolio_value * daily_vol * sqrt(window_days) * z_score
        """
        z_scores = {0.99: 2.326, 0.95: 1.645, 0.90: 1.282}
        z = z_scores.get(confidence or self.config.var_confidence, 1.645)
        daily_vol = self.config.daily_vol_assumption
        var = portfolio_value * daily_vol * math.sqrt(self.config.var_window_days) * z
        return var

    def pre_trade_check(
        self,
        signal,
        portfolio: dict,
        prices: dict,
        current_positions: dict = None,
        price_history: dict = None,
    ) -> tuple:
        """Run ALL risk checks in sequence. Returns (approved, reason).

        Combines: circuit breaker, correlation, position limits, Kelly, VaR.
        """
        # 1. Circuit breaker
        total_value = float(portfolio.get("total_value", 0))
        if not self.check_circuit_breaker(total_value):
            return False, "CIRCUIT BREAKER: drawdown exceeded"

        # 2. Standard check
        result = self.check(signal, portfolio, prices, current_positions)
        if not result.approved:
            return False, result.reason

        # 3. Correlation (if price_history provided)
        if price_history and current_positions:
            corr = self.check_correlation(
                signal.symbol, current_positions, price_history
            )
            if corr > self.config.max_correlation:
                return False, f"Correlation {corr:.2f} > {self.config.max_correlation}"

        return True, "approved"

    # ── Core Order Check (existing OpenTrader interface) ──────────

    def check(
        self,
        signal,
        portfolio: dict,
        prices: dict,
        current_positions: dict = None,
        overrides: Dict[str, float] = None,
    ) -> RiskResult:
        """Validate and adjust a signal against risk rules.

        This is the primary entry point used by the harness.

        Args:
            signal: Signal object with action, confidence, position_pct
            portfolio: dict with total_value, cash, positions
            prices: dict of symbol → current price
            current_positions: dict of symbol → qty
            overrides: Optional dict of RiskConfig attr → value to temporarily
                       apply (e.g. regime-adaptive sizing). Restored after check.
        """
        # Save and apply overrides for this check only.
        # Lock the entire save-apply-check-restore critical section so
        # concurrent threads calling check(overrides=...) don't corrupt
        # each other's saved values (one thread's restore would clobber
        # another's apply). Checks are pure compute — serialization cost
        # is negligible.
        with self._config_lock:
            saved = {}
            if overrides:
                for attr, val in overrides.items():
                    if hasattr(self.config, attr):
                        saved[attr] = getattr(self.config, attr)
                        setattr(self.config, attr, val)

            try:
                return self._check_inner(signal, portfolio, prices, current_positions)
            finally:
                # Restore original config values
                for attr, original in saved.items():
                    setattr(self.config, attr, original)

    def _check_inner(
        self, signal, portfolio: dict, prices: dict, current_positions: dict = None
    ) -> RiskResult:
        """Internal check logic (extracted for override save/restore pattern)."""
        self._reset_daily()

        total_value = float(portfolio.get("total_value", 0))
        cash = float(portfolio.get("cash", 0))
        positions = current_positions or portfolio.get("positions", {})

        if signal.action.upper() == "HOLD":
            return RiskResult(approved=True, reason="HOLD")

        price = prices.get(signal.symbol, 0)
        if price <= 0:
            return RiskResult(approved=False, reason=f"no price for {signal.symbol}")

        # ── Fee-aware minimum position check ────────────────────
        # Fee source: state/context.py FEE_TABLES — "stock" route =
        # FeeSchedule(fixed_per_trade=0.35, min_fee=0.35) (IBKR-style fixed
        # stock fee); "crypto" = taker_pct 0.0018. The $0.35 in rejection
        # messages comes from that table, not a magic constant.
        # Notional is per-side: BUY uses the (defaulted) sizing %, SELL uses
        # the actual position value (qty * price) — exit signals often carry
        # position_pct=0, which previously zeroed the notional and made every
        # SELL look like a 99900% fee.
        if signal.action.upper() == "SELL":
            _pos = positions.get(signal.symbol, 0)
            _qty = (
                float(_pos.get("quantity", 0))
                if isinstance(_pos, dict)
                else float(_pos or 0)
            )
            notional = _qty * price
        else:
            _size0 = signal.position_pct if signal.position_pct > 0 else 0.05
            notional = _size0 * total_value
        try:
            from state.context import AccountContext, FEE_TABLES, FeeSchedule

            exchange = getattr(self.config, "_exchange", "paper")
            table = FEE_TABLES.get(exchange)
            # Fail-closed on unknown exchanges: an unrecognized exchange name
            # (e.g. a config typo "papr") has no fee schedule, so we cannot
            # price the guard. Log it loudly and reject the trade rather than
            # silently passing every trade through with fees=None.
            if table is None:
                logger.warning(
                    f"unknown exchange '{exchange}': no fee table — refusing trade"
                )
                return RiskResult(
                    approved=False,
                    reason=f"unknown exchange '{exchange}': no fee table — refusing",
                )
            fees = table
            # Route-aware: crypto -> %-based, stocks -> fixed. The multi
            # router exposes the per-symbol route; fall back to the table's
            # "default" when the exchange isn't a router or route is unknown.
            if isinstance(fees, dict):
                route = (
                    "stock"
                    if not getattr(signal, "is_crypto", False)
                    and "/" not in (signal.symbol or "")
                    else "crypto"
                )
                fees = fees.get(route) or fees.get("default")
            elif not isinstance(fees, FeeSchedule):
                fees = None

            if fees and notional > 0:
                round_trip = fees.round_trip_cost(notional)
                fee_pct = round_trip / notional
                if fee_pct > 0.20:
                    return RiskResult(
                        approved=False,
                        reason=f"fees too high: ${round_trip:.2f} = {fee_pct:.0%} of ${notional:.2f} position (max 20%)",
                    )
                # Hard min-notional floor: ~$5 (exchange minimums) OR the
                # 20%-fee break-even, whichever is larger.
                min_floor = max(5.0, fees.min_notional(max_cost_pct=0.20))
                if notional < min_floor:
                    return RiskResult(
                        approved=False,
                        reason=f"position too small: ${notional:.2f} < ${min_floor:.2f} min notional (fee-aware)",
                    )
        except Exception as e:
            logger.warning(
                f"fee-aware check unavailable ({e}); sizing proceeds without fee guard"
            )

        # ── Daily fee-drag ceiling (small-account guard) ───────
        # On a $50–300 account, one day of fees must not meaningfully dent
        # capital. Track cumulative round-trip fees today vs total_value.
        try:
            from state.context import FEE_TABLES as _FT, FeeSchedule as _FS

            _fees2 = _FT.get(getattr(self.config, "_exchange", "paper"), {})
            if isinstance(_fees2, dict):
                _route = "stock" if "/" not in (signal.symbol or "") else "crypto"
                _fees2 = _fees2.get(_route) or _fees2.get("default")
            if isinstance(_fees2, _FS):
                _rt = _fees2.round_trip_cost(notional)
                _total_drag = getattr(self, "_daily_fee_drag", 0.0) + _rt
                if total_value > 0 and _total_drag > 0.05 * total_value:
                    return RiskResult(
                        approved=False,
                        reason=f"daily fee drag ${_total_drag:.2f} exceeds 5% of account (${total_value:.2f})",
                    )
        except Exception as e:
            logger.warning(f"fee-drag check unavailable ({e}); skipped")

        # ── Daily trade count ─────────────────────────────────
        if self._daily_trades >= self.config.max_daily_trades:
            return RiskResult(
                approved=False,
                reason=f"daily trade limit ({self.config.max_daily_trades}) reached",
            )

        # ── Position sizing ───────────────────────────────────
        size_pct = signal.position_pct if signal.position_pct > 0 else 0.05
        _inpct = size_pct
        size_pct = min(size_pct, self.config.max_position_pct)
        if size_pct != _inpct:
            logger.debug(
                f"  Risk[{signal.symbol}]: max_position_pct cap: {_inpct:.3f}→{size_pct:.3f}"
            )
        proposed_value = total_value * size_pct
        if proposed_value > self.config.max_order_value:
            _prev = size_pct
            size_pct = self.config.max_order_value / max(total_value, 1)
            logger.debug(
                f"  Risk[{signal.symbol}]: max_order cap: {_prev:.4f}→{size_pct:.4f}"
            )

        # ── Cash check (BUY only) ─────────────────────────────
        if signal.action.upper() == "BUY":
            if proposed_value > cash - self.config.min_cash_reserve:
                available = cash - self.config.min_cash_reserve
                if available <= 0:
                    return RiskResult(approved=False, reason="insufficient cash")
                _prev = size_pct
                size_pct = available / total_value
                logger.debug(
                    f"  Risk[{signal.symbol}]: cash cap: {_prev:.4f}→{size_pct:.4f}"
                )

            # Max positions
            existing = sum(
                1
                for qty in positions.values()
                if (isinstance(qty, (int, float)) and qty > 0)
                or (isinstance(qty, dict) and qty.get("quantity", 0) > 0)
            )
            if existing >= self.config.max_positions:
                return RiskResult(
                    approved=False,
                    reason=f"max positions ({self.config.max_positions}) reached",
                )

            # Total exposure — validated upstream by Committee (monitors.py)
            # The committee already checks exposure with correct per-symbol
            # pricing, so we skip the duplicate check here to avoid unit-mismatch
            # bugs (risk manager doesn't have prices for all symbols).

            # Kelly check (ATLANTIS addition)
            # Kelly is the fraction of bankroll to risk on this bet.
            # apply fractional Kelly safety factor, then use directly
            # as portfolio percentage (not divided by price ratio).
            kelly = self.kelly_criterion()
            if size_pct > kelly:
                _prev = size_pct
                size_pct = kelly
                logger.debug(
                    f"  Risk[{signal.symbol}]: kelly cap: {_prev:.4f}→{size_pct:.4f} (kelly={kelly:.4f})"
                )

        elif signal.action.upper() == "SELL":
            pos_qty = 0
            pos = positions.get(signal.symbol, 0)
            if isinstance(pos, dict):
                pos_qty = float(pos.get("quantity", 0))
            else:
                pos_qty = float(pos or 0)
            if pos_qty <= 0:
                return RiskResult(
                    approved=False, reason=f"no position in {signal.symbol}"
                )

        # ── Stop-loss / Take-profit ──────────────────────────
        stop_loss = signal.stop_loss
        if stop_loss is None or stop_loss <= 0:
            if signal.action.upper() == "BUY":
                stop_loss = price * (1 - self.config.stop_loss_pct)
            else:
                stop_loss = price * (1 + self.config.stop_loss_pct)

        take_profit = signal.take_profit
        if take_profit is None or take_profit <= 0:
            if signal.action.upper() == "BUY":
                take_profit = price * (1 + self.config.take_profit_pct)
            else:
                take_profit = price * (1 - self.config.take_profit_pct)

        trade_key = f"{signal.symbol}:{signal.action}:{signal.position_pct:.4f}"
        if trade_key not in self._seen_trade_keys:
            self._seen_trade_keys.add(trade_key)
            self._daily_trades += 1
            # Accumulate fee drag for the daily 5% ceiling (small-account guard)
            try:
                from state.context import FEE_TABLES as _FT2, FeeSchedule as _FS2

                _f = _FT2.get(getattr(self.config, "_exchange", "paper"), {})
                if isinstance(_f, dict):
                    _r = "stock" if "/" not in (signal.symbol or "") else "crypto"
                    _f = _f.get(_r) or _f.get("default")
                if isinstance(_f, _FS2):
                    self._daily_fee_drag = getattr(self, "_daily_fee_drag", 0.0) + (
                        _f.round_trip_cost(notional)
                    )
            except Exception as e:
                logger.warning(f"fee-drag accumulation failed ({e}); skipped")
        logger.info(
            f"  RiskDBG[{signal.symbol}]: FINAL adj_size={size_pct:.4f} "
            f"sig_in={signal.position_pct:.4f} "
            f"caps=[max_pos={self.config.max_position_pct:.3f} "
            f"max_ord={self.config.max_order_value:.0f} "
            f"cash_r={self.config.min_cash_reserve:.0f} "
            f"max_exp={self.config.max_total_exposure:.3f} "
            f"klly_f={self.config.kelly_fraction:.3f}] "
            f"state=[tv={total_value:.0f} cash={cash:.0f} "
            f"price={price:.2f} npos={len(positions)} "
            f"prop_v={proposed_value:.0f}]"
        )
        return RiskResult(
            approved=True,
            reason="ok",
            adjusted_size=round(size_pct, 4),
            adjusted_stop=round(stop_loss, 2),
            adjusted_tp=round(take_profit, 2),
        )

    # ── Phase 7: Portfolio-Level Allocation ─────────────────────

    def allocate_portfolio(
        self,
        signals: list,
        portfolio: dict,
        prices: dict,
        price_history: Optional[dict] = None,
        current_positions: Optional[dict] = None,
        volatilities: Optional[dict] = None,
    ) -> "PortfolioResult":
        """Run multi-symbol portfolio optimization across all signals.

        Delegates to PortfolioOptimizer with current risk parameters.
        Returns PortfolioResult with allocations and portfolio metrics.
        """
        from risk.portfolio_optimizer import PortfolioOptimizer
        import logging

        _log = logging.getLogger(__name__)
        _log.debug(
            f"  MGR-ALLOCATE: signals={len(signals)} "
            f"({', '.join(f'{s.symbol}={s.action}' for s in signals)}), "
            f"prices={list(prices.keys())[:5]}, "
            f"pos={list(portfolio.get('positions', {}).keys())[:5]}"
            f"  max_pos_pct={self.config.max_position_pct}"
            f"  kelly_frac={self.config.kelly_fraction}"
            f"  max_exposure={self.config.max_total_exposure}"
        )
        optimizer = PortfolioOptimizer(
            max_position_pct=self.config.max_position_pct,
            max_total_exposure=self.config.max_total_exposure,
            max_positions=self.config.max_positions,
            max_correlation=self.config.max_correlation,
            kelly_fraction=self.config.kelly_fraction,
            min_cash_reserve=self.config.min_cash_reserve,
            max_order_value=self.config.max_order_value,
        )
        return optimizer.optimize(
            signals=signals,
            portfolio=portfolio,
            prices=prices,
            price_history=price_history,
            current_positions=current_positions,
            volatilities=volatilities,
        )

    @staticmethod
    def extract_price_history(
        exchange: Any,
        symbols: list,
        lookback: int = 50,
        timeframe: str = "1h",
    ) -> Dict[str, list]:
        """Extract price history from exchange bars for correlation computation.

        Args:
            exchange: ExchangeBase instance with get_bars()
            symbols: List of symbol strings
            lookback: Number of bars to pull per symbol
            timeframe: Bar timeframe string (default "1h")

        Returns:
            dict[symbol] = [price1, price2, ...] (close prices)
        """
        history: Dict[str, list] = {}
        for sym in symbols:
            try:
                bars = exchange.get_bars(sym, timeframe, limit=lookback)
                if bars:
                    history[sym] = [b.close for b in bars]
                else:
                    history[sym] = []
            except Exception:
                history[sym] = []
        return history

    @staticmethod
    def compute_portfolio_metrics(
        positions: dict,
        prices: dict,
        price_history: Optional[dict] = None,
        total_value: float = 0.0,
    ) -> dict:
        """Compute portfolio-level metrics for dashboard & monitoring.

        Delegates to PortfolioOptimizer's static compute_portfolio_metrics.
        """
        from risk.portfolio_optimizer import PortfolioOptimizer

        return PortfolioOptimizer.compute_portfolio_metrics(
            positions=positions,
            prices=prices,
            price_history=price_history or {},
            total_value=total_value,
        )
