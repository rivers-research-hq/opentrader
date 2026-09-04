#!/usr/bin/env python3
"""State Manager — writes trading state for dashboard consumption.

Ported from ATLANTIS TraderHarness. Writes JSON files atomically.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("opentrader.state")


class StateManager:
    """Writes trade state to disk for dashboard display.

    Files:
        paper_state.json      → portfolio, positions, fills, metrics
        high_level_state.json → regime, strategy, posture
    """

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = str(Path.cwd() / "data")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "paper_state.json"
        self.high_level_path = self.state_dir / "high_level_state.json"

    def write(
        self,
        cycle: int,
        portfolio: dict,
        positions: list,
        fills: list,
        prices: dict,
        regime: dict = None,
        signals: list = None,
        models: dict = None,
        metrics: dict = None,
        initial_cash: float = None,
        portfolio_metrics: dict = None,
        trades: list = None,
        alerts: list = None,
        hodl_benchmark: dict = None,
        committee: dict = None,
        symbol_regimes: dict = None,
        skip_history: bool = False,
        data_provenance: dict = None,
        fundamentals_coverage: dict = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        state = self._build_state(
            cycle,
            portfolio,
            positions,
            fills,
            prices,
            regime,
            signals,
            models,
            metrics,
            initial_cash,
            portfolio_metrics,
            trades,
            alerts,
            hodl_benchmark,
            committee,
            symbol_regimes,
            now,
            data_provenance,
            fundamentals_coverage,
        )
        self._write_state(state)
        if not skip_history:
            self._write_cycle(cycle, state)
        return state

    def _build_state(
        self,
        cycle,
        portfolio,
        positions,
        fills,
        prices,
        regime,
        signals,
        models,
        metrics,
        initial_cash,
        portfolio_metrics,
        trades,
        alerts,
        hodl_benchmark,
        committee,
        symbol_regimes,
        now,
        data_provenance: dict = None,
        fundamentals_coverage: dict = None,
    ) -> dict:
        state = {
            "cycle": cycle,
            "timestamp": now,
            "initial_cash": initial_cash or 100_000.0,
            "cash": portfolio.get("cash", 0),
            "portfolio_value": portfolio.get("total_value", 0),
            "positions": positions,
            "prices": prices,
            "fills": fills[-50:] if fills else [],
            "data_provenance": data_provenance or {},
            "fundamentals_coverage": fundamentals_coverage or {},
            "signals": [
                {
                    "symbol": s.get("symbol", "")
                    if isinstance(s, dict)
                    else getattr(s, "symbol", ""),
                    "action": s.get("action", "")
                    if isinstance(s, dict)
                    else getattr(s, "action", ""),
                    "confidence": s.get("confidence", 0)
                    if isinstance(s, dict)
                    else getattr(s, "confidence", 0),
                    "position_pct": s.get("position_pct", 0)
                    if isinstance(s, dict)
                    else getattr(s, "position_pct", 0),
                    "reason": s.get("reason", "")
                    if isinstance(s, dict)
                    else getattr(s, "reason", ""),
                    "timestamp": s.get("timestamp", "") if isinstance(s, dict) else "",
                }
                for s in (signals or [])
            ],
            "models": models or {},
            "metrics": {
                "cycle_time_s": metrics.get("cycle_time_s", 0) if metrics else 0,
                "total_cycles": cycle,
                "total_fills": len(fills) if fills else 0,
                **(metrics or {}),
            },
            "portfolio_optimization": portfolio_metrics or {},
            "trades": trades or [],
            "alerts": alerts or [],
            "hodl_benchmark": hodl_benchmark or {},
            "Committee": committee or {},
            "symbol_regimes": symbol_regimes or {},
        }
        return state

    def _unique_tmp(self, target: Path) -> Path:
        """Per-writer temp file — two harnesses writing the same state must
        never share a .tmp name (one would clobber the other mid-write)."""
        return target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")

    def _write_state(self, state: dict):
        tmp_path = self._unique_tmp(self.state_path)
        try:
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp_path, self.state_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _write_cycle(self, cycle: int, state: dict):
        history_dir = self.state_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        cycle_path = history_dir / f"cycle_{cycle:04d}.json"
        with open(cycle_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        self._trim_history(history_dir)

    _MAX_HISTORY_FILES = 2000

    def _trim_history(self, history_dir: Path) -> None:
        """Rolling retention for per-cycle snapshots — one file per cycle
        grows ~8,640 files/day (~57MB+); cap to the most recent N."""
        try:
            files = sorted(history_dir.glob("cycle_*.json"))
            if len(files) <= self._MAX_HISTORY_FILES:
                return
            for f in files[: -self._MAX_HISTORY_FILES]:
                try:
                    f.unlink()
                except OSError:
                    pass
        except Exception:
            pass

    @staticmethod
    def state_key(state: dict) -> str:
        """Deterministic hash of meaningful trading state changes.

        Only includes fields that indicate actual trade/portfolio changes.
        Ignores purely cosmetic fields like timestamp, cycle number, etc.
        """
        positions = state.get("positions", [])
        pos_str = (
            ";".join(
                sorted(
                    f"{p.get('symbol', '')}:{p.get('quantity', p.get('size', 0)):.6f}:{p.get('entry_price') or 0:.2f}"
                    for p in positions
                )
            )
            if positions
            else ""
        )

        trades = state.get("trades", [])
        trade_str = (
            ";".join(
                f"{t.get('symbol', '')}:{t.get('side', '')}:{t.get('pnl', 0):.4f}"
                for t in trades[-5:]
            )
            if trades
            else ""
        )

        committee = state.get("Committee", {})
        comm_str = f"{committee.get('action', '')}:{committee.get('confidence', 0):.2f}"

        raw = (
            f"pos={pos_str}|"
            f"fil_ct={len(state.get('fills', []))}|"
            f"trade_ct={len(state.get('trades', []))}|"
            f"sig_ct={len(state.get('signals', []))}|"
            f"comm={comm_str}|"
            f"trd={trade_str}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def write_high_level(
        self,
        regime: str = "unknown",
        confidence: float = 0.0,
        thesis: str = "",
        posture: str = "defensive",
        available: bool = False,
        updated: str = None,
        models: dict = None,
        portfolio: dict = None,
    ) -> dict:
        state = {
            "regime": regime,
            "confidence": round(confidence, 2),
            "thesis": thesis,
            "posture": posture,
            "available": available,
            "updated": updated or datetime.now(timezone.utc).isoformat(),
            "models": models or {},
            "portfolio": portfolio or {},
        }
        tmp_path = self._unique_tmp(self.high_level_path)
        try:
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp_path, self.high_level_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return state

    @staticmethod
    def normalize_positions(positions) -> dict:
        """Normalize positions from either list or dict format.

        StateManager.write() stores positions as a list of dicts with 'symbol' key.
        Some legacy consumers expect a dict of symbol -> quantity/value.
        This helper handles both formats safely.
        """
        if isinstance(positions, dict):
            return positions
        if isinstance(positions, list):
            return {p["symbol"]: p for p in positions if isinstance(p, dict)}
        return {}

    def read(self) -> dict:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"State file corrupt or unreadable: {e}")
                return {}
        return {}

    def read_high_level(self) -> dict:
        if self.high_level_path.exists():
            with open(self.high_level_path) as f:
                return json.load(f)
        return {}
