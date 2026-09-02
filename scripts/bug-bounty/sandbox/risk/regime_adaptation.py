#!/usr/bin/env python3
"""Regime-Adaptive Strategy Selection — adjusts prompts and risk params per market regime.

Phase 7 — Wires the regime classifier output into:
  1. Debate agent system prompts (Bull/Bear/Risk get regime-specific instructions)
  2. Risk config parameters (position sizing, stop tightness, exposure limits)

Each regime produces:
  - prompt_instructions dict: per-agent behavioral modifiers
  - risk_overrides dict: RiskConfig parameter adjustments

Usage:
    from risk.regime_adaptation import get_regime_instructions, get_regime_risk_overrides

    regime = {"regime": "trending_up", "confidence": 0.85, ...}
    prompts = get_regime_instructions(regime)
    risk_adj = get_regime_risk_overrides(regime)
"""

from typing import Dict, Optional


# ── Regime → Prompt Instructions ───────────────────────────────

REGIME_PROMPT_MAP = {
    "trending_up": {
        "bull": (
            "REGIME: Strong uptrend detected (high ADX, bullish structure). "
            "Be aggressive in identifying long entries. "
            "Trend-following setups have high probability — favor continuation patterns. "
            "Position sizes can go up to 20% of portfolio in strong trends."
        ),
        "bear": (
            "REGIME: Market is in an uptrend. "
            "Be skeptical of reversal calls unless there's clear evidence of exhaustion "
            "(divergence, overbought readings, volume fade). "
            "Your job is to size the risk, not to fight the trend."
        ),
        "risk": (
            "REGIME: Uptrend. "
            "Favor bullish verdicts when trend indicators confirm. "
            "Penalize bearish calls that lack clear reversal evidence. "
            "Trend strength reduces the penalty on position size."
        ),
    },
    "trending_down": {
        "bull": (
            "REGIME: Strong downtrend (high ADX, bearish structure). "
            "Be extremely cautious — counter-trend longs have low probability. "
            "Only consider longs if there's a clear reversal pattern "
            "(double bottom, divergence, support at key level). "
            "Reduce position size expectations to 0-5%."
        ),
        "bear": (
            "REGIME: Strong downtrend. "
            "Be aggressive — the trend is your friend. "
            "Look for continuation patterns, breakdowns, and momentum shorts. "
            "Position for downside with conviction."
        ),
        "risk": (
            "REGIME: Downtrend. "
            "Strongly favor bearish verdicts. "
            "Penalize bullish calls heavily unless they show exceptional risk/reward. "
            "Default to SELL or HOLD with high confidence."
        ),
    },
    "ranging": {
        "bull": (
            "REGIME: Sideways / ranging market (low ADX). "
            "Look for mean-reversion setups and range-bound trades. "
            "Buy near support levels, sell near resistance. "
            "Don't expect breakout follow-through — take profits quickly. "
            "Keep position sizes modest (5-10%)."
        ),
        "bear": (
            "REGIME: Ranging market. "
            "Look for overbought rejection at resistance. "
            "Be skeptical of both trend and reversal calls in range. "
            "Your best bets are fade-the-move setups."
        ),
        "risk": (
            "REGIME: Ranging. "
            "Balance bullish and bearish scores evenly — no direction has an edge. "
            "Favor HOLD unless one side has exceptional evidence. "
            "Shorter timeframes and smaller position sizes preferred."
        ),
    },
    "volatile": {
        "bull": (
            "REGIME: High volatility (wide Bollinger Bands). "
            "Opportunities are larger but risk is higher. "
            "Wider stop-losses are needed to avoid noise-driven exits. "
            "Reduce position size to account for vol expansion."
        ),
        "bear": (
            "REGIME: High volatility. "
            "Risk management is paramount. Widely swinging prices make "
            "directional bets dangerous. Consider the volatility-adjusted "
            "risk of every setup. Tight stops get taken out in vol."
        ),
        "risk": (
            "REGIME: High volatility regime. "
            "Reduce position size recommendations across the board. "
            "Volatility-adjusted sizing is critical. "
            "Higher uncertainty means higher confidence thresholds for any trade."
        ),
    },
    "bullish": {
        "bull": (
            "REGIME: Bullish across timeframes (higher highs, positive returns). "
            "Confidence is warranted — multiple timeframes confirm the bias. "
            "Look for pullback entries and continuation setups."
        ),
        "bear": (
            "REGIME: Bullish across timeframes. "
            "Challenge overextended bullish calls, but acknowledge the regime. "
            "Only SELL if there's clear divergence or reversal structure."
        ),
        "risk": (
            "REGIME: Bullish. "
            "Favor bullish verdicts. Weight trend-confirming signals higher. "
            "Bearish challenges need more evidence to outweigh the bullish regime."
        ),
    },
    "bearish": {
        "bull": (
            "REGIME: Bearish across timeframes. "
            "Counter-trend longs require exceptional risk/reward. "
            "Look for capitulation or support bounces, not trend reversals."
        ),
        "bear": (
            "REGIME: Bearish across timeframes. "
            "The regime confirms bearish bias. "
            "Look for continuation and breakdown entries. "
            "Be confident in selling into strength."
        ),
        "risk": (
            "REGIME: Bearish. "
            "Favor bearish verdicts. Strongly weight downside scenarios. "
            "Bullish calls require high-conviction evidence to override."
        ),
    },
}

# Default (unknown/insufficient_data) — conservative across the board
DEFAULT_INSTRUCTIONS: Dict[str, str] = {
    "bull": (
        "REGIME: Unknown or insufficient data. "
        "Be conservative — no directional edge identified. "
        "Reduce position size. Wait for clearer signals."
    ),
    "bear": (
        "REGIME: Unknown. "
        "Be cautious — without clear regime data, capital preservation is priority. "
        "Challenge any high-conviction calls."
    ),
    "risk": (
        "REGIME: Unknown. "
        "Be conservative. Require higher confidence for any non-HOLD verdict. "
        "Reduce position size recommendations."
    ),
}


def get_regime_instructions(regime_result: Optional[dict]) -> Dict[str, str]:
    """Generate per-agent prompt instructions from regime classification.

    Args:
        regime_result: Output from classify_regime() — dict with 'regime' key
                       and 'confidence' key. Can be None.

    Returns:
        dict with keys 'bull', 'bear', 'risk' — each is a string instruction
        to prepend to the agent's system prompt.
    """
    if not regime_result:
        return dict(DEFAULT_INSTRUCTIONS)

    regime = regime_result.get("regime", "unknown")
    confidence = regime_result.get("confidence", 0.0)

    # Get base instructions for the regime
    instructions = REGIME_PROMPT_MAP.get(regime, DEFAULT_INSTRUCTIONS)

    # Add confidence-based modifier
    if confidence < 0.4:
        low_conf = (
            " NOTE: Regime confidence is LOW — treat this as guidance, not certainty."
        )
        instructions = {k: v + low_conf for k, v in instructions.items()}

    elif confidence > 0.8:
        high_conf = (
            " NOTE: Regime confidence is HIGH — weight this regime signal strongly."
        )
        instructions = {k: v + high_conf for k, v in instructions.items()}

    return instructions


# ── Regime → Risk Config Overrides ─────────────────────────────

REGIME_RISK_MAP = {
    "trending_up": {
        "max_position_pct": 0.20,
        "max_total_exposure": 0.80,
        "kelly_fraction": 0.40,
        "trailing_stop_pct": 0.03,
        "position_stop_pct": 0.05,
    },
    "trending_down": {
        "max_position_pct": 0.08,
        "max_total_exposure": 0.35,
        "kelly_fraction": 0.20,
        "trailing_stop_pct": 0.02,
        "position_stop_pct": 0.03,
    },
    "ranging": {
        "max_position_pct": 0.18,
        "max_total_exposure": 0.60,
        "kelly_fraction": 0.35,
        "trailing_stop_pct": 0.025,
        "position_stop_pct": 0.04,
    },
    "volatile": {
        "max_position_pct": 0.12,
        "max_total_exposure": 0.45,
        "kelly_fraction": 0.22,
        "trailing_stop_pct": 0.05,
        "position_stop_pct": 0.07,
    },
    "bullish": {
        "max_position_pct": 0.20,
        "max_total_exposure": 0.70,
        "kelly_fraction": 0.38,
        "trailing_stop_pct": 0.03,
        "position_stop_pct": 0.05,
    },
    "bearish": {
        "max_position_pct": 0.08,
        "max_total_exposure": 0.35,
        "kelly_fraction": 0.20,
        "trailing_stop_pct": 0.02,
        "position_stop_pct": 0.03,
    },
}

# Default overrides (neutral)
DEFAULT_RISK_OVERRIDES: Dict[str, float] = {
    "max_position_pct": 0.18,
    "max_total_exposure": 0.60,
    "kelly_fraction": 0.35,
    "trailing_stop_pct": 0.025,
    "position_stop_pct": 0.04,
}


def get_regime_risk_overrides(regime_result: Optional[dict]) -> Dict[str, float]:
    """Get RiskConfig parameter overrides for the current regime.

    Returns a dict of RiskConfig attribute → new value.
    Only includes params that should change; None means no override.
    """
    if not regime_result:
        return {}

    regime = regime_result.get("regime", "unknown")
    overrides = REGIME_RISK_MAP.get(regime, None)
    if overrides is None:
        return {}

    confidence = regime_result.get("confidence", 0.0)
    # Blend toward neutral at low confidence
    if confidence < 0.5 and regime in REGIME_RISK_MAP:
        blend = confidence / 0.5  # 0.0 → use default, 1.0 → use full override
        defaults = DEFAULT_RISK_OVERRIDES
        return {
            k: defaults.get(k, v) + (v - defaults.get(k, v)) * blend
            for k, v in overrides.items()
        }

    return dict(overrides)


def format_regime_debug(regime_result: Optional[dict]) -> str:
    """Format regime info for logging."""
    if not regime_result:
        return "regime: unknown"
    r = regime_result
    ind = r.get("indicators", {})
    return (
        f"regime={r.get('regime','?')} "
        f"conf={r.get('confidence',0):.0%} "
        f"ADX={ind.get('adx',0):.0f} "
        f"BB={ind.get('bb_width',0):.3f} "
        f"slope={ind.get('ma_slope',0):.4f}"
    )
