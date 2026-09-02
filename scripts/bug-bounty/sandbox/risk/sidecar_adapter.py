#!/usr/bin/env python3
"""Sidecar Risk Adapter — delegates RiskManager computation to the Rust sidecar."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from .manager import RiskManager, RiskConfig, RiskResult

logger = logging.getLogger("opentrader.risk.sidecar")


class RiskSidecarAdapter(RiskManager):
    """RiskManager subclass that delegates compute-heavy methods to a Rust sidecar.

    Inherits Python-only methods (allocate_portfolio, extract_price_history,
    compute_portfolio_metrics, get_symbol_overrides) directly from RiskManager.
    """

    def __init__(self, config: RiskConfig = None, sidecar_client: Any = None):
        super().__init__(config)
        self._sidecar = sidecar_client
        self._needs_config_sync: bool = True

    def set_sidecar(self, client: Any) -> None:
        self._sidecar = client
        self._needs_config_sync = True

    def _sync_config(self) -> None:
        if not self._sidecar or not self._needs_config_sync:
            return
        cfg = {
            "max_position_pct": self.config.max_position_pct,
            "max_total_exposure": self.config.max_total_exposure,
            "max_positions": self.config.max_positions,
            "max_order_value": self.config.max_order_value,
            "stop_loss_pct": self.config.stop_loss_pct,
            "take_profit_pct": self.config.take_profit_pct,
            "portfolio_stop_pct": self.config.portfolio_stop_pct,
            "min_cash_reserve": self.config.min_cash_reserve,
            "max_daily_trades": self.config.max_daily_trades,
            "max_correlation": self.config.max_correlation,
            "kelly_fraction": self.config.kelly_fraction,
            "default_win_prob": self.config.default_win_prob,
            "default_wl_ratio": self.config.default_wl_ratio,
            "trailing_stop_pct": self.config.trailing_stop_pct,
            "trailing_stop_activation": self.config.trailing_stop_activation,
            "max_position_cycles": self.config.max_position_cycles,
            "position_stop_pct": self.config.position_stop_pct,
            "var_confidence": self.config.var_confidence,
            "var_window_days": self.config.var_window_days,
            "daily_vol_assumption": self.config.daily_vol_assumption,
        }
        try:
            self._sidecar.risk_set_config(cfg)
            self._needs_config_sync = False
        except Exception as exc:
            logger.warning(f"Config sync to sidecar failed: {exc}")

    def _mark_dirty(self) -> None:
        self._needs_config_sync = True

    def set_initial(self, cash: float) -> None:
        super().set_initial(cash)
        self._mark_dirty()
        if self._sidecar:
            try:
                self._sidecar.risk_set_initial(cash)
            except Exception:
                pass

    def update_peak(self, portfolio_value: float) -> None:
        super().update_peak(portfolio_value)
        if self._sidecar:
            try:
                self._sidecar.risk_update_peak(portfolio_value)
            except Exception:
                pass

    # ── individual compute methods ───────────────────────────────────

    def check_circuit_breaker(self, portfolio_value: float) -> bool:
        if self._sidecar:
            self._sync_config()
            try:
                return self._sidecar.risk_check_circuit_breaker(portfolio_value)
            except Exception as exc:
                logger.debug(f"Sidecar circuit_breaker failed, fallback: {exc}")
        return super().check_circuit_breaker(portfolio_value)

    def kelly_criterion(
        self, win_prob: float = None, win_loss_ratio: float = None
    ) -> float:
        if self._sidecar:
            self._sync_config()
            try:
                return self._sidecar.risk_kelly_criterion(win_prob, win_loss_ratio)
            except Exception as exc:
                logger.debug(f"Sidecar kelly failed, fallback: {exc}")
        return super().kelly_criterion(win_prob, win_loss_ratio)

    def var_calculation(
        self, portfolio_value: float, confidence: float = None
    ) -> float:
        if self._sidecar:
            self._sync_config()
            try:
                return self._sidecar.risk_var_calculation(portfolio_value, confidence)
            except Exception as exc:
                logger.debug(f"Sidecar VaR failed, fallback: {exc}")
        return super().var_calculation(portfolio_value, confidence)

    # ── core check ───────────────────────────────────────────────────

    def check(
        self,
        signal,
        portfolio: dict,
        prices: dict,
        current_positions: dict = None,
        overrides: Dict[str, float] = None,
    ) -> Any:
        if not self._sidecar:
            return super().check(signal, portfolio, prices, current_positions, overrides)

        saved = {}
        if overrides:
            for attr, val in overrides.items():
                if hasattr(self.config, attr):
                    saved[attr] = getattr(self.config, attr)
                    setattr(self.config, attr, val)
                    self._mark_dirty()

        try:
            self._sync_config()
            result = self._sidecar.risk_check(
                signal=signal,
                portfolio_total_value=float(portfolio.get("total_value", 0)),
                portfolio_cash=float(portfolio.get("cash", 0)),
                prices=prices,
                current_positions=current_positions,
            )
            from .manager import RiskResult

            return RiskResult(
                approved=result.get("approved", False),
                reason=result.get("reason", ""),
                adjusted_size=float(result.get("adjusted_size", 0)),
                adjusted_stop=result.get("adjusted_stop"),
                adjusted_tp=result.get("adjusted_tp"),
            )
        except Exception as exc:
            logger.debug(f"Sidecar check failed, fallback: {exc}")
            return super().check(signal, portfolio, prices, current_positions, overrides)
        finally:
            for attr, original in saved.items():
                setattr(self.config, attr, original)
            if saved:
                self._mark_dirty()

    def pre_trade_check(
        self,
        signal,
        portfolio: dict,
        prices: dict,
        current_positions: dict = None,
        price_history: dict = None,
    ) -> tuple:
        if not self._sidecar:
            return super().pre_trade_check(
                signal, portfolio, prices, current_positions, price_history
            )

        self._sync_config()
        try:
            return self._sidecar.risk_pre_trade_check(
                signal=signal,
                portfolio_total_value=float(portfolio.get("total_value", 0)),
                portfolio_cash=float(portfolio.get("cash", 0)),
                prices=prices,
                current_positions=current_positions,
                price_history=price_history,
            )
        except Exception as exc:
            logger.debug(f"Sidecar pre_trade_check failed, fallback: {exc}")
            return super().pre_trade_check(
                signal, portfolio, prices, current_positions, price_history
            )
