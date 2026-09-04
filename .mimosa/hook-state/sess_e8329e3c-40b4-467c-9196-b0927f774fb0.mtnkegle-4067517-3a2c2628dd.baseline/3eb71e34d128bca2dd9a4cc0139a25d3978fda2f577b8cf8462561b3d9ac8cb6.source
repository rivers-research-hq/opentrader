#!/usr/bin/env python3
"""Synthetic market data — generate realistic OHLCV for testing.

Produces price series with realistic properties:
  - Geometric Brownian Motion with regime changes
  - Volume clustering
  - Bid-ask microstructure noise
"""
import math
import random
from datetime import datetime, timezone, timedelta
from typing import List, Optional


def make_timestamp(days_ago: int = 30, idx: int = 0,
                   timeframe_hours: int = 1) -> int:
    """Generate a UNIX timestamp for a given offset."""
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    ts = base + timedelta(hours=idx * timeframe_hours)
    return int(ts.timestamp())


def generate_bars(
    symbol: str = "BTC/USDT",
    count: int = 500,
    start_price: float = 50000.0,
    volatility: float = 0.02,
    trend: float = 0.0002,
    timeframe: str = "1h",
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate synthetic OHLCV bars.

    Args:
        symbol: Trading pair label
        count: Number of bars to generate
        start_price: Starting price
        volatility: Daily volatility (std of returns)
        trend: Drift per bar
        timeframe: Bar label
        seed: Random seed for reproducibility

    Returns:
        List of OHLCV dicts
    """
    if seed is not None:
        random.seed(seed)

    bars = []
    price = start_price

    # Extract hours from timeframe string
    tf_map = {"1m": 1/60, "5m": 5/60, "15m": 15/60, "1h": 1, "4h": 4, "1d": 24}
    tf_hours = tf_map.get(timeframe, 1)

    for i in range(count):
        # Volatility with regime changes
        vol = volatility * (1 + 0.5 * math.sin(i / 20))  # cyclic vol
        daily_vol = vol / math.sqrt(24 / tf_hours) if tf_hours > 0 else vol

        # Random walk
        ret = random.gauss(trend, daily_vol)

        # Occasional jumps
        if random.random() < 0.01:
            jump_dir = 1 if random.random() > 0.5 else -1
            ret += jump_dir * daily_vol * 3

        # Intra-bar high/low
        hi_lo = daily_vol * 0.5 * abs(random.gauss(0, 1))
        open_ = price
        close = price * (1 + ret)
        high = max(open_, close) + hi_lo * price
        low = min(open_, close) - hi_lo * price * 0.5

        # Volume (correlated with volatility)
        volume = random.lognormvariate(math.log(100 + abs(ret) * 5000), 0.5)

        bars.append({
            "timestamp": make_timestamp(days_ago=30, idx=i, timeframe_hours=tf_hours),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": max(0.01, round(low, 2)),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })
        price = close

    return bars


def generate_correlated_bars(
    symbol: str = "BTC/USDT",
    count: int = 200,
    start_price: float = 50000.0,
    end_price: float = 55000.0,
    volatility: float = 0.015,
    timeframe: str = "1h",
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate synthetic bars with a known trend (start→end)."""
    if seed is not None:
        random.seed(seed)

    bars = []
    trend_per_bar = (end_price / start_price) ** (1 / max(1, count)) - 1
    tf_map = {"1m": 1/60, "5m": 5/60, "15m": 15/60, "1h": 1, "4h": 4, "1d": 24}
    tf_hours = tf_map.get(timeframe, 1)

    price = start_price
    for i in range(count):
        daily_vol = volatility / math.sqrt(24 / tf_hours) if tf_hours > 0 else volatility
        ret = random.gauss(trend_per_bar, daily_vol)
        hi_lo = daily_vol * 0.4 * abs(random.gauss(0, 1))
        open_ = price
        close = price * (1 + ret)
        high = max(open_, close) + hi_lo * price
        low = min(open_, close) - hi_lo * price * 0.5
        volume = random.lognormvariate(math.log(50 + abs(ret) * 3000), 0.5)
        bars.append({
            "timestamp": make_timestamp(days_ago=14, idx=i, timeframe_hours=tf_hours),
            "open": round(open_, 2),
            "high": round(high, 2),
            "low": max(0.01, round(low, 2)),
            "close": round(close, 2),
            "volume": round(volume, 4),
        })
        price = close

    return bars


def generate_trending_bars(
    symbol: str = "BTC/USDT",
    count: int = 200,
    start_price: float = 50000.0,
    end_price: float = 55000.0,
    volatility: float = 0.015,
    timeframe: str = "1h",
    seed: Optional[int] = None,
) -> List[dict]:
    """Generate synthetic bars with a known trend (start->end)."""
    if seed is not None:
        random.seed(seed)
    bars = []
    trend_per_bar = (end_price / start_price) ** (1 / max(1, count)) - 1
    tf_map = {"1m": 1/60, "5m": 5/60, "15m": 15/60, "1h": 1, "4h": 4, "1d": 24}
    tf_hours = tf_map.get(timeframe, 1)
    price = start_price
    for i in range(count):
        daily_vol = volatility / math.sqrt(24 / tf_hours) if tf_hours > 0 else volatility
        ret = random.gauss(trend_per_bar, daily_vol)
        hi_lo = daily_vol * 0.4 * abs(random.gauss(0, 1))
        open_ = price
        close = price * (1 + ret)
        high = max(open_, close) + hi_lo * price
        low = min(open_, close) - hi_lo * price * 0.5
        volume = random.lognormvariate(math.log(50 + abs(ret) * 3000), 0.5)
        bars.append({
            "timestamp": make_timestamp(days_ago=14, idx=i, timeframe_hours=tf_hours),
            "open": round(open_, 2), "high": round(high, 2),
            "low": max(0.01, round(low, 2)), "close": round(close, 2),
            "volume": round(volume, 4),
        })
        price = close
    return bars


if __name__ == "__main__":
    # Quick test: generate and display stats
    bars = generate_bars(count=100, seed=42)
    prices = [b["close"] for b in bars]
    print(f"Generated {len(bars)} bars")
    print(f"Price range: ${min(prices):.2f} - ${max(prices):.2f}")
    print(f"Start: ${prices[0]:.2f} → End: ${prices[-1]:.2f}")
    print(f"Return: {(prices[-1]/prices[0]-1)*100:.1f}%")
    print(f"Sample bar: {bars[0]}")
