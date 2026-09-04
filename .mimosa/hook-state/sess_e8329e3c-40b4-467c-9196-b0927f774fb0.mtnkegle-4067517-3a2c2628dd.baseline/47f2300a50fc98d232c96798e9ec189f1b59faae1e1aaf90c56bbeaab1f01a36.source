#!/usr/bin/env python3
"""Multi-Timeframe Indicator Computation for OpenTrader.

Computes technical indicators across multiple timeframes (1h, 4h, 1d)
for use in the ADIR debate context.
"""

import json
import logging
from typing import Dict, List, Optional

from .regime_classifier import (
    _sma,
    _ema,
    _adx,
    _bb_width,
    _ma_slope,
    _volume_ratio,
    _structure,
    classify_regime,
)
from data import generate_bars

logger = logging.getLogger("opentrader.multi_tf")


# ── Indicator Helpers (reused from regime_classifier) ──────────────────────


def _rsi(values: List[float], period: int = 14) -> float:
    """Relative Strength Index."""
    if len(values) < period + 1:
        return 0.0
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [d if d > 0 else 0 for d in diffs]
    losses = [-d if d < 0 else 0 for d in diffs]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def _macd(
    values: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple:
    """MACD line, signal line, histogram."""
    ma_fast = _ema(values, fast)
    ma_slow = _ema(values, slow)
    macd = [fa - sb for fa, sb in zip(ma_fast, ma_slow)]
    ma_signal = _ema(macd, signal)
    hist = [m - s for m, s in zip(macd, ma_signal)]
    if not macd or not ma_signal:
        return 0, 0, 0
    return round(macd[-1], 4), round(ma_signal[-1], 4), round(hist[-1], 4)


def compute_multi_tf_indicators(bars: List[dict], symbol: str) -> dict:
    """Compute technical indicators across 1h, 4h, 1d timeframes.

    Args:
        bars: OHLCV bars in 1h timeframe
        symbol: Symbol name (for logging)

    Returns:
        dict with keys: {
            "1h": {"rsi": float, "macd": float, "sma20": float, "vol": float},
            "4h": {same},
            "1d": {same},
        }
    """
    indicators: Dict[str, Dict[str, float]] = {}

    # Build multi-timeframe bars from 1h bars
    tf_bars = {
        "1h": bars,
        "4h": _downsample_bars(bars, 4),
        "1d": _downsample_bars(bars, 24),
    }

    for tf, b in tf_bars.items():
        if not b:
            indicators[tf] = {
                "rsi": 0,
                "macd": 0,
                "sma20": 0,
                "vol": 0,
                "trend": "unknown",
            }
            continue

        closes = [c.get("close", 0) for c in b if "close" in c]
        highs = [c.get("high", 0) for c in b if "high" in c]
        lows = [c.get("low", 0) for c in b if "low" in c]
        volumes = [c.get("volume", 0) for c in b if "volume" in c]

        if not closes:
            indicators[tf] = {
                "rsi": 0,
                "macd": 0,
                "sma20": 0,
                "vol": 0,
                "trend": "unknown",
            }
            continue

        rsi = _rsi(closes, 14)
        macd_line, macd_signal, hist = _macd(closes, 12, 26, 9)
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else closes[-1]
        vol = (max(highs) - min(highs)) / max(closes[-1], 0.01) if highs else 0
        trend = _structure(closes, 10)

        indicators[tf] = {
            "rsi": round(rsi, 1),
            "macd": round(macd_line, 4),
            "macd_hist": round(hist, 4),
            "sma20": round(sma20, 2),
            "vol": round(vol, 4),
            "trend": trend,
            "close": round(closes[-1], 2),
        }

    return indicators


def _downsample_bars(bars: List[dict], period: int) -> List[dict]:
    """Downsample bars by grouping into blocks of `period` bars."""
    if not bars:
        return []

    downsampled = []
    for i in range(0, len(bars), period):
        block = bars[i : i + period]
        if not block:
            break

        o = min((b.get("open", 0) for b in block if "open" in b), default=0)
        h = max((b.get("high", 0) for b in block if "high" in b), default=0)
        l = min((b.get("low", 0) for b in block if "low" in b), default=0)
        c = (b.get("close", 0) for b in block if "close" in b)
        close_val = list(c)[-1] if c else 0

        # Use the last close in the block as the close for the downsampled bar
        close_list = [b.get("close", 0) for b in block if "close" in b]
        if close_list:
            close_val = close_list[-1]

        v = sum((b.get("volume", 0) for b in block if "volume" in b), 0)

        downsampled.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": close_val,
                "volume": v,
            }
        )

    return downsampled


# ── Format for prompt context ──────────────────────────────────────────


def format_multi_tf_prompt(indicators: dict, symbol: str) -> str:
    """Format multi-timeframe indicators as a prompt block."""
    lines = []
    for tf in ("1h", "4h", "1d"):
        data = indicators.get(tf, {})
        if data.get("close", 0) == 0:
            lines.append(f"{tf}: insufficient data")
            continue

        rsi = data.get("rsi", 0)
        macd = data.get("macd", 0)
        sma20 = data.get("sma20", 0)
        vol = data.get("vol", 0)
        trend = data.get("trend", "unknown")
        close = data.get("close", 0)

        # RSI interpretation
        if rsi > 70:
            rsi_str = "OVERBOUGHT"
        elif rsi < 30:
            rsi_str = "OVERSOLD"
        elif rsi > 50:
            rsi_str = "BULLISH"
        else:
            rsi_str = "BEARISH"

        lines.append(
            f"{tf} → {close:.0f}  RSI={rsi:.0f} ({rsi_str})  MACD={macd:+.2f}  SMA20={sma20:.0f}  Vol={vol:.2%}  Trend={trend}"
        )

    return "\n".join(lines)


# ── Integration helper ─────────────────────────────────────────────────


def build_multi_tf_context(harness_state: dict) -> str:
    """Build multi-timeframe context from harness state for prompt injection."""
    # Find the symbol's bars from the state
    for symbol in harness_state.get("symbols", []):
        bars = harness_state.get("bars", {})
        if (
            symbol in bars
            and isinstance(bars[symbol], list)
            and len(bars[symbol]) >= 20
        ):
            indicators = compute_multi_tf_indicators(bars[symbol], symbol)
            return format_multi_tf_prompt(indicators, symbol)
    return ""
