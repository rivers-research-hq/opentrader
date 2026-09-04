#!/usr/bin/env python3
"""Programmatic Teacher — deterministic trading scenarios for training.

Port of ATLANTIS programmatic_teacher.py (6 scenario types).
Each scenario generates OHLCV bars, a description, and a ground-truth answer.
No LLM calls needed — deterministic and fast.
"""
import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Scenario:
    """A trading scenario for teacher/student training."""
    scenario_type: str
    description: str
    bars: List[dict]          # OHLCV: [{open, high, low, close, volume}, ...]
    ground_truth: str         # BUY, SELL, or HOLD
    confidence: float = 0.0   # How confident the teacher is (0-1)
    difficulty: str = "medium"
    explanation: str = ""     # Why this is the correct answer
    meta: dict = field(default_factory=dict)


def _make_bar(open_p: float, high: float, low: float, close: float,
              volume: float = None) -> dict:
    return {
        "open": round(open_p, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "close": round(close, 2),
        "volume": round(volume or random.uniform(100, 1000), 2),
    }


def _trend_bars(start: float, length: int, trend: float, vol: float,
                seed: int = None) -> List[dict]:
    """Generate bars with a given trend and volatility."""
    if seed is not None:
        random.seed(seed)
    bars = []
    price = start
    for i in range(length):
        change = random.gauss(trend, vol)
        price *= (1.0 + change)
        hi = price * (1.0 + abs(random.gauss(0, vol * 0.5)))
        lo = price * (1.0 - abs(random.gauss(0, vol * 0.5)))
        bars.append(_make_bar(price * (1 - vol * 0.3), hi, lo, price))
    return bars


def generate_breakout(seed: int = None) -> Scenario:
    """Trend consolidation followed by upside breakout. GT: BUY."""
    if seed is not None:
        random.seed(seed)
    # Consolidation range
    bars = _trend_bars(100.0, 30, 0.0, 0.005, seed)
    # Breakout: surge above range
    for i in range(20):
        bar = bars[-1]
        price = bar["close"] * (1.0 + random.gauss(0.008, 0.004))
        hi = price * 1.015
        lo = bar["close"] * 0.995
        bars.append(_make_bar(bar["close"], hi, lo, price))
    return Scenario(
        scenario_type="breakout_entry",
        description="Price consolidates in a tight range then breaks out above resistance "
                     "on increasing volume. Classic momentum entry opportunity.",
        bars=bars,
        ground_truth="BUY",
        confidence=0.85,
        difficulty="easy",
        explanation="Price broke above resistance with momentum. Entry at breakout confirmation.",
    )


def generate_false_breakout(seed: int = None) -> Scenario:
    """Price breaks above resistance then reverses. GT: SELL (or wait)."""
    if seed is not None:
        random.seed(seed)
    # Uptrend then false breakout above resistance
    bars = _trend_bars(100.0, 25, 0.003, 0.004, seed)
    # Spike above resistance
    for i in range(5):
        bar = bars[-1]
        price = bar["close"] * (1.0 + random.gauss(0.015, 0.005))
        hi = price * 1.02
        lo = bar["close"] * 0.995
        bars.append(_make_bar(bar["close"], hi, lo, price))
    # Reversal back below
    for i in range(15):
        bar = bars[-1]
        price = bar["close"] * (1.0 - random.gauss(0.006, 0.003))
        hi = bar["close"] * 1.005
        lo = price * 0.992
        bars.append(_make_bar(bar["close"], hi, lo, price))
    return Scenario(
        scenario_type="false_breakout",
        description="Price briefly breaks above resistance on a spike, but quickly reverses "
                     "and falls back below the breakout level. Classic false breakout / bear trap.",
        bars=bars,
        ground_truth="SELL",
        confidence=0.8,
        difficulty="medium",
        explanation="The breakout lacked follow-through and volume. Short or stay out.",
    )


def generate_trend_following(seed: int = None) -> Scenario:
    """Strong uptrend with pullback. GT: BUY on pullback."""
    if seed is not None:
        random.seed(seed)
    # Strong uptrend
    bars = _trend_bars(100.0, 20, 0.006, 0.003, seed)
    # Pullback
    for i in range(5):
        bar = bars[-1]
        price = bar["close"] * (1.0 - random.gauss(0.004, 0.002))
        hi = bar["close"] * 1.002
        lo = price * 0.995
        bars.append(_make_bar(bar["close"], hi, lo, price))
    # Resume uptrend
    for i in range(10):
        bar = bars[-1]
        price = bar["close"] * (1.0 + random.gauss(0.005, 0.003))
        hi = price * 1.01
        lo = bar["close"] * 0.998
        bars.append(_make_bar(bar["close"], hi, lo, price))
    return Scenario(
        scenario_type="trend_following",
        description="Strong uptrend with a shallow pullback to the 20-period moving average. "
                     "The trend resumes with momentum. Classic trend-following entry.",
        bars=bars,
        ground_truth="BUY",
        confidence=0.9,
        difficulty="easy",
        explanation="Uptrend intact, pullback found support. Enter at continuation.",
    )


def generate_mean_reversion(seed: int = None) -> Scenario:
    """Sharp spike above Bollinger bands. GT: SELL (reversion)."""
    if seed is not None:
        random.seed(seed)
    # Range-bound
    bars = _trend_bars(100.0, 25, 0.0, 0.003, seed)
    # Spike up
    for i in range(3):
        bar = bars[-1]
        price = bar["close"] * (1.0 + random.gauss(0.02, 0.005))
        hi = price * 1.01
        lo = bar["close"] * 1.001
        bars.append(_make_bar(bar["close"], hi, lo, price))
    # Reversion
    for i in range(10):
        bar = bars[-1]
        price = bar["close"] * (1.0 - random.gauss(0.005, 0.003))
        hi = bar["close"] * 1.003
        lo = price * 0.995
        bars.append(_make_bar(bar["close"], hi, lo, price))
    return Scenario(
        scenario_type="mean_reversion",
        description="Price spiked sharply above the upper Bollinger Band on low volume, "
                     "then reverts back toward the mean. Overextended move getting corrected.",
        bars=bars,
        ground_truth="SELL",
        confidence=0.75,
        difficulty="medium",
        explanation="Price extended beyond normal range. Mean reversion likely.",
    )


def generate_flash_crash(seed: int = None) -> Scenario:
    """Sudden sharp drop with quick recovery. GT: HOLD (don't panic sell)."""
    if seed is not None:
        random.seed(seed)
    # Normal trading
    bars = _trend_bars(100.0, 20, 0.001, 0.003, seed)
    # Flash crash
    for i in range(3):
        bar = bars[-1]
        price = bar["close"] * (1.0 - random.gauss(0.04, 0.01))
        hi = bar["close"] * 0.995
        lo = price * 0.99
        bars.append(_make_bar(bar["close"], hi, lo, price))
    # Quick recovery
    for i in range(12):
        bar = bars[-1]
        price = bar["close"] * (1.0 + random.gauss(0.015, 0.005))
        hi = price * 1.01
        lo = bar["close"] * 0.998
        bars.append(_make_bar(bar["close"], hi, lo, price))
    return Scenario(
        scenario_type="flash_crash",
        description="A sudden sharp price drop of ~8% over 3 bars with a V-shaped recovery. "
                     "Volume spiked during the crash. No fundamental news.",
        bars=bars,
        ground_truth="HOLD",
        confidence=0.8,
        difficulty="hard",
        explanation="Flash crashes typically reverse. Panic selling locks in losses.",
    )


def generate_range_accumulation(seed: int = None) -> Scenario:
    """Price in a tight range with no clear direction. GT: HOLD."""
    if seed is not None:
        random.seed(seed)
    bars = _trend_bars(100.0, 40, 0.0, 0.002, seed)
    return Scenario(
        scenario_type="range_accumulation",
        description="Price is trading in a tight range with decreasing volatility and volume. "
                     "No clear trend or breakout signal. Low momentum environment.",
        bars=bars,
        ground_truth="HOLD",
        confidence=0.9,
        difficulty="easy",
        explanation="No directional bias. Wait for a breakout or clearer signal.",
    )


# Registry of all programmatic patterns
PROGRAMMATIC_PATTERNS = {
    "breakout_entry": generate_breakout,
    "false_breakout": generate_false_breakout,
    "trend_following": generate_trend_following,
    "mean_reversion": generate_mean_reversion,
    "flash_crash": generate_flash_crash,
    "range_accumulation": generate_range_accumulation,
}


DIFFICULTY_MAP = {
    "breakout_entry": "easy",
    "false_breakout": "medium",
    "trend_following": "easy",
    "mean_reversion": "medium",
    "flash_crash": "hard",
    "range_accumulation": "easy",
}


class ProgrammaticTeacher:
    """Deterministic scenario generator — no LLM needed.

    Generates advesarial trading scenarios with known ground truth
    for training and evaluating student agents.
    """

    def __init__(self, seed: int = None):
        self.seed = seed
        self._call_count = 0

    def list_scenario_types(self) -> List[str]:
        return list(PROGRAMMATIC_PATTERNS.keys())

    def generate(self, scenario_type: str = None) -> Scenario:
        """Generate a single scenario. Picks randomly if type not specified."""
        if scenario_type is None:
            types = list(PROGRAMMATIC_PATTERNS.keys())
            weights = [3, 2, 3, 2, 1, 3]  # bias toward easier patterns
            scenario_type = random.choices(types, weights=weights, k=1)[0]

        gen_fn = PROGRAMMATIC_PATTERNS.get(scenario_type)
        if gen_fn is None:
            raise ValueError(f"Unknown scenario type: {scenario_type}. "
                             f"Available: {list(PROGRAMMATIC_PATTERNS.keys())}")

        self._call_count += 1
        s = gen_fn(seed=self.seed + self._call_count if self.seed else None)
        s.difficulty = DIFFICULTY_MAP.get(scenario_type, "medium")
        return s

    def generate_batch(self, count: int, weights: List[str] = None) -> List[Scenario]:
        """Generate multiple scenarios."""
        return [self.generate() for _ in range(count)]
