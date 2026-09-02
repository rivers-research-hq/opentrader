"""Scenario specification and World containers for the multiverse generator.

A ScenarioSpec is a declarative description of one market reality: a regime, an
optional tail event, a volatility multiplier, a drift, a correlation regime, and
a duration. A World is a concrete realization — a dict of OHLCV DataFrames
(symbol -> DataFrame with open/high/low/close/volume and a DatetimeIndex) that
matches ``setup_search.data.load_ohlcv``'s output shape, so it can be consumed by
``setup_search.engine.run_backtest`` through the multiverse war.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

REGIME_BULL = "bull"
REGIME_BEAR = "bear"
REGIME_RANGE = "range"
REGIME_CRISIS = "crisis"
REGIMES = (REGIME_BULL, REGIME_BEAR, REGIME_RANGE, REGIME_CRISIS)

# Matches the 5y archive universe (SPY = regime marker + 16 tradeables).
DEFAULT_UNIVERSE = [
    "SPY",
    "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "JPM",
    "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX",
]


@dataclass
class ScenarioSpec:
    name: str = "default"
    regime: str = REGIME_RANGE
    event: Optional[str] = None          # tail-event id from tail_library, if any
    regime_break: Optional[tuple] = None  # (bar_frac, regime) mid-world flip, if any
    n_bars: int = 500
    drift: float = 0.0003                # per-bar expected return (annual-ish scale)
    vol_mult: float = 1.0                # volatility multiplier vs baseline
    correlation: float = 0.4             # cross-symbol correlation (0..1)
    jump_p: float = 0.01                 # per-bar jump probability in baseline regime
    seed: Optional[int] = None
    symbols: List[str] = field(default_factory=lambda: list(DEFAULT_UNIVERSE))


@dataclass
class World:
    spec: ScenarioSpec
    data: Dict[str, pd.DataFrame]        # symbol -> OHLCV df, align-ready
    labels: Optional[dict] = None        # per-bar ground-truth labels if any
    generated_by: str = "parametric"

    def align_ready(self) -> dict:
        """Return the data dict in the exact shape run_war consumes."""
        return self.data
