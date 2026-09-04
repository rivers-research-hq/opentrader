#!/usr/bin/env python3
"""SLM Regime Classifier — statistical regime detection from OHLCV.

No ML model needed. Uses classic technical indicators to classify
market regime: trending_up, trending_down, ranging, volatile, bearish.

The model agent gets this as context so it doesn't waste inference
cycles figuring out basic market structure.

Indicators used:
  - ADX (Average Directional Index): trend strength
  - Bollinger Band width: volatility regime
  - MA slope: direction
  - Volume profile: conviction
  - Higher-highs / lower-lows: structure
"""
import math
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.regime")


def _sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average."""
    if len(values) < period:
        return [sum(values) / len(values)] * len(values)
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(sum(values[:i+1]) / (i+1))
        else:
            result.append(sum(values[i-period+1:i+1]) / period)
    return result


def _ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(result[-1] + alpha * (v - result[-1]))
    return result


def _tr(high: float, low: float, prev_close: float) -> float:
    """True Range."""
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def _adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Average Directional Index — trend strength (0-100)."""
    if len(closes) < period + 1:
        return 0.0

    tr_values = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(closes)):
        tr = _tr(highs[i], lows[i], closes[i-1])
        tr_values.append(tr)

        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]

        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0)

        if down_move > up_move and down_move > 0:
            minus_dm.append(down_move)
        else:
            minus_dm.append(0)

    # Smooth with EMA
    atr = sum(tr_values[:period]) / period
    pdi = sum(plus_dm[:period]) / period / max(atr, 0.001)
    ndi = sum(minus_dm[:period]) / period / max(atr, 0.001)

    dx = abs(pdi - ndi) / max(pdi + ndi, 0.001) * 100

    # SMA of DX over period
    dx_values = [dx]
    for i in range(period, len(plus_dm)):
        atr = (atr * (period - 1) + tr_values[i]) / period
        pdi = (pdi * (period - 1) + plus_dm[i]) / max(atr, 0.001) / period * 100
        ndi = (ndi * (period - 1) + minus_dm[i]) / max(atr, 0.001) / period * 100
        dx = abs(pdi - ndi) / max(pdi + ndi, 0.001) * 100
        dx_values.append(dx)

    return sum(dx_values[-period:]) / period if len(dx_values) >= period else dx_values[-1]


def _bb_width(closes: List[float], period: int = 20, std_mult: float = 2.0) -> float:
    """Bollinger Band width as fraction of mid band — volatility indicator."""
    if len(closes) < period:
        return 0.05
    recent = closes[-period:]
    ma = sum(recent) / period
    variance = sum((x - ma) ** 2 for x in recent) / period
    std = math.sqrt(variance)
    width = (2 * std_mult * std) / max(ma, 0.01)
    return width


def _ma_slope(closes: List[float], period: int = 10) -> float:
    """Slope of moving average as fraction per bar."""
    if len(closes) < period:
        return 0.0
    ma = _sma(closes, period)
    recent = ma[-period:]
    if len(recent) < 2:
        return 0.0
    # Linear regression slope
    n = len(recent)
    x_avg = (n - 1) / 2
    y_avg = sum(recent) / n
    num = sum((i - x_avg) * (y - y_avg) for i, y in enumerate(recent))
    den = sum((i - x_avg) ** 2 for i in range(n))
    slope = num / max(den, 0.001)
    return slope / max(recent[0], 0.01)  # Normalize


def _volume_ratio(volumes: List[float], short: int = 5, long_: int = 20) -> float:
    """Volume ratio: short avg / long avg. >1.2 = high conviction."""
    if len(volumes) < long_:
        return 1.0
    short_avg = sum(volumes[-short:]) / short
    long_avg = sum(volumes[-long_:]) / long_
    return short_avg / max(long_avg, 0.001)


def _structure(closes: List[float], lookback: int = 10) -> str:
    """Identify price structure: HH/HL (uptrend), LH/LL (downtrend), or mixed."""
    if len(closes) < lookback:
        return "mixed"
    segment = closes[-lookback:]
    highs = []
    lows = []
    # Find swing points
    for i in range(1, len(segment) - 1):
        if segment[i] > segment[i-1] and segment[i] > segment[i+1]:
            highs.append((i, segment[i]))
        if segment[i] < segment[i-1] and segment[i] < segment[i+1]:
            lows.append((i, segment[i]))

    if len(highs) < 2 or len(lows) < 2:
        return "mixed"

    higher_highs = highs[-1][1] > highs[-2][1]
    higher_lows = lows[-1][1] > lows[-2][1]
    lower_highs = highs[-1][1] < highs[-2][1]
    lower_lows = lows[-1][1] < lows[-2][1]

    if higher_highs and higher_lows:
        return "strong_uptrend"
    elif higher_highs:
        return "uptrend"
    elif lower_highs and lower_lows:
        return "strong_downtrend"
    elif lower_lows:
        return "downtrend"
    return "mixed"


def classify_regime(bars: List[dict]) -> dict:
    """Classify market regime from OHLCV bars.

    Args:
        bars: List of OHLCV dicts with open/high/low/close/volume keys

    Returns:
        dict with regime, confidence, thesis, and supporting metrics
    """
    if not bars or len(bars) < 20:
        return {
            "regime": "insufficient_data",
            "confidence": 0.0,
            "thesis": "Need at least 20 bars for regime classification",
            "symbol": bars[0].get("symbol", "unknown") if bars else "unknown",
        }

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b.get("volume", 0) for b in bars]
    current_price = closes[-1]

    # Compute indicators
    adx_val = _adx(highs, lows, closes)
    bb_w = _bb_width(closes)
    slope = _ma_slope(closes)
    vol_ratio = _volume_ratio(volumes)
    struct = _structure(closes)

    # Price action over multiple timeframes
    ret_5 = (closes[-1] / closes[-5] - 1) if len(closes) >= 5 else 0
    ret_10 = (closes[-1] / closes[-10] - 1) if len(closes) >= 10 else 0
    ret_20 = (closes[-1] / closes[-20] - 1) if len(closes) >= 20 else 0
    ret_40 = (closes[-1] / closes[-40] - 1) if len(closes) >= 40 else 0

    # Volatility check
    if len(closes) >= 10:
        returns = [abs(closes[i] / closes[i-1] - 1) for i in range(1, 10)]
        avg_volatility = sum(returns) / len(returns)
    else:
        avg_volatility = 0.02

    # ── Classification logic ──

    thesis_parts = []
    regime = "ranging"
    confidence = 0.5

    # Strong/moderate trend with ADX
    # Thresholds lowered for crypto: 1% in 20 bars is meaningful on 1h candles
    # (annualized ~438% on 1h bars, vs ~6% for stocks on daily bars)
    if adx_val > 20:
        if slope > 0.0003 and ret_20 > 0.01:
            regime = "trending_up"
            confidence = min(0.85, 0.45 + adx_val / 150 + abs(slope) * 80)
            thesis_parts.append(f"uptrend (ADX={adx_val:.0f}, slope={slope:.4f})")
        elif slope < -0.0003 and ret_20 < -0.01:
            regime = "trending_down"
            confidence = min(0.85, 0.45 + adx_val / 150 + abs(slope) * 80)
            thesis_parts.append(f"downtrend (ADX={adx_val:.0f}, slope={slope:.4f})")

    # Weak trend / ranging
    if adx_val < 20 and abs(slope) < 0.0005:
        if bb_w < 0.05:
            regime = "ranging"
            confidence = 0.6
            thesis_parts.append("low volatility range (tight Bollinger bands)")
        elif bb_w > 0.15:
            regime = "volatile"
            confidence = 0.65
            thesis_parts.append(f"high volatility (BB width={bb_w:.2f})")
        else:
            regime = "ranging"
            confidence = 0.5
            thesis_parts.append("sideways with moderate volatility")

    # Bearish (negative across all timeframes)
    if ret_5 < -0.01 and ret_10 < -0.005 and ret_20 < -0.005:
        if "trending_down" not in regime:
            regime = "bearish"
            confidence = max(confidence, 0.7)
            thesis_parts.append(f"across-tf decline (5d={ret_5:+.1%}, 20d={ret_20:+.1%})")
    # Bullish (positive across timeframes)
    elif ret_5 > 0.01 and ret_10 > 0.005 and ret_20 > 0.005:
        if "trending_up" not in regime:
            regime = "bullish"
            confidence = max(confidence, 0.65)
            thesis_parts.append(f"across-tf advance (5d={ret_5:+.1%}, 20d={ret_20:+.1%})")

    # Volume confirmation
    if vol_ratio > 1.3 and confidence > 0.5:
        thesis_parts.append(f"volume confirming {vol_ratio:.1f}x avg")
    elif vol_ratio < 0.7 and regime == "ranging":
        thesis_parts.append("low volume consolidation")

    # Structure
    if "strong" in struct:
        thesis_parts.append(f"{struct.replace('_', ' ')}")
        if "uptrend" in struct:
            confidence = min(0.9, confidence + 0.1)
        elif "downtrend" in struct:
            confidence = min(0.9, confidence + 0.1)

    # Volatility spike detection
    recent_vol = 0
    if len(closes) >= 5:
        recent_returns = [abs(closes[i] / closes[i-1] - 1) for i in range(-4, 0)]
        recent_vol = sum(recent_returns) / len(recent_returns)
    if recent_vol > avg_volatility * 2 and regime == "ranging":
        regime = "volatile"
        confidence = max(confidence, 0.6)
        thesis_parts.append(f"volatility spike ({recent_vol:.2%} vs {avg_volatility:.2%} avg)")

    # Build thesis string
    thesis = ", ".join(thesis_parts) if thesis_parts else "mixed signals, no clear regime"

    return {
        "regime": regime,
        "confidence": round(confidence, 2),
        "thesis": thesis[:200],  # cap length
        "symbol": bars[-1].get("symbol", "unknown") if bars else "unknown",
        "price": current_price,
        "indicators": {
            "adx": round(adx_val, 1),
            "bb_width": round(bb_w, 4),
            "ma_slope": round(slope, 6),
            "volume_ratio": round(vol_ratio, 2),
            "structure": struct,
            "return_5d": round(ret_5, 4),
            "return_10d": round(ret_10, 4),
            "return_20d": round(ret_20, 4),
            "return_40d": round(ret_40, 4),
        },
    }


def format_regime_for_prompt(regime_result: dict) -> str:
    """Format regime result for model prompt context."""
    r = regime_result
    ind = r.get("indicators", {})
    return (
        f"Regime: {r.get('regime', 'unknown')} "
        f"(confidence: {r.get('confidence', 0):.0%})\n"
        f"Thesis: {r.get('thesis', '')}\n"
        f"ADX: {ind.get('adx', 0):.0f} | "
        f"BB Width: {ind.get('bb_width', 0):.3f} | "
        f"MA Slope: {ind.get('ma_slope', 0):.4f}\n"
        f"5d Return: {ind.get('return_5d', 0):+.1%} | "
        f"20d Return: {ind.get('return_20d', 0):+.1%}\n"
        f"Structure: {ind.get('structure', 'n/a')} | "
        f"Vol Ratio: {ind.get('volume_ratio', 0):.1f}x"
    )


# ── CLI test ──

if __name__ == "__main__":
    from synthetic import generate_bars
    bars = generate_bars(count=200, seed=42)
    result = classify_regime(bars)
    import pprint
    pprint.pprint(result)
    print()
    print(format_regime_for_prompt(result))
