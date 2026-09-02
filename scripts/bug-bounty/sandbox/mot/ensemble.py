#!/usr/bin/env python3
"""Specialist Ensemble — multi-agent voting for trading decisions.

Deploys multiple specialist agents, each using the same fine-tuned model
but with distinct trading personas and analysis focuses. Results are
aggregated through a consensus-voting coordinator.

Specialists:
  TechnicalAnalyst — RSI, MACD, support/resistance, chart patterns
  MomentumChaser — trend following, breakout confirmation, volume
  MeanReversionHunter — oversold/overbought, Bollinger bands, mean
  MacroSentiment — fear/greed, regime alignment, cross-asset
  PatternDayTrader — small quick wins, tight stops, scalp mindset

Config:
  thresholds.invest — min signal ratio to execute (default: 0.6)
  thresholds.divest — if 80%+ vote SELL, override all shows
  voting.smooth — running average of specialist accuracy by symbol

Usage:
  ensemble = Ensemble(pool, adapter="ptolemy-s0")
  ensemble.configure(thresholds={"invest": 0.5, "divest": 0.8})
  signal = ensemble.vote(market_context)
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.ensemble")


TECHNICAL_SYSTEM = """You are a Technical Analyst. Focus on:
- RSI (oversold <30, overbought >70)
- MACD crossovers and histogram divergence
- Support/resistance levels from recent price action
- Volume confirmation of moves
- Chart patterns (double tops, flags, wedges)

Given market data with OHLCV prices, identify entry/exit points.
Output JSON: {"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "position_pct": 0.0-0.2, "reasoning": "10-30 words", "signals": [specific indicators seen]}
Be precise about indicator levels. JSON only."""


MOMENTUM_SYSTEM = """You are a Momentum Chaser. Focus on:
- Strong directional trends (>3 consecutive bars in same direction)
- Breakout confirmation (price above recent high with volume)
- Moving average alignment (short-term MA > long-term MA)
- Rate of change (ROC) accelerating
- ADX > 25 confirming trend strength

You want to ride trends, not fight them. Buy strength, sell weakness.
Output JSON: {"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "position_pct": 0.0-0.2, "reasoning": "10-30 words", "trend_strength": "weak|moderate|strong"}
JSON only."""


MEAN_REVERSION_SYSTEM = """You are a Mean Reversion Hunter. Focus on:
- Oversold RSI (<30, especially <25) as buy signal
- Overbought RSI (>70, especially >80) as sell signal
- Bollinger Band touches (price at lower band = buy, upper band = sell)
- Distance from 20-period moving average (z-score)
- VWAP reversion opportunities

You buy when panic selling exhausts, sell when euphoria peaks.
Output JSON: {"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "position_pct": 0.0-0.2, "reasoning": "10-30 words", "z_score": float}
JSON only."""


MACRO_SYSTEM = """You are a Macro Sentiment Analyst. Focus on:
- Market regime (trending/ranging/crisis) and alignment
- Fear/greed indicators (extreme fear = accumulation zone)
- Cross-asset correlation (BTC leading alts, stocks correlation)
- Time-of-day patterns (volatility clusters, session opens)
- News sentiment impact on price action

You contextualize technical signals within broader market conditions.
Output JSON: {"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "position_pct": 0.0-0.2, "reasoning": "10-30 words", "regime": "trending|ranging|volatile"}
JSON only."""


PATTERN_DAY_SYSTEM = """You are a Pattern Day Trader. Focus on:
- Quick small wins (+0.5% to +2% targets)
- Tight stop losses (-0.5% to -1.5%)
- Scalping micro-structure (1-minute/5-minute chart patterns)
- High-probability setups only (confidence >0.75 to enter)
- Quick exits if thesis invalidated in 3-5 bars

You trade frequently with small positions, aiming for high win rate.
Output JSON: {"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "position_pct": 0.0-0.15, "reasoning": "10-30 words", "scalp_quality": "low|medium|high"}
JSON only."""


SPECIALISTS = {
    "technical": {
        "name": "TechnicalAnalyst",
        "system": TECHNICAL_SYSTEM,
        "weight": 1.0,
        "description": "Indicator-based support/resistance analysis",
    },
    "momentum": {
        "name": "MomentumChaser",
        "system": MOMENTUM_SYSTEM,
        "weight": 0.9,
        "description": "Trend following and breakout detection",
    },
    "mean_reversion": {
        "name": "MeanReversionHunter",
        "system": MEAN_REVERSION_SYSTEM,
        "weight": 0.85,
        "description": "Buy oversold, sell overbought reversals",
    },
    "macro": {
        "name": "MacroSentiment",
        "system": MACRO_SYSTEM,
        "weight": 1.0,
        "description": "Regime-aware cross-asset analysis",
    },
    "pattern_day": {
        "name": "PatternDayTrader",
        "system": PATTERN_DAY_SYSTEM,
        "weight": 0.8,
        "description": "Quick scalps with tight stops",
    },
}


@dataclass
class Vote:
    action: str           # BUY, SELL, HOLD
    confidence: float
    position_pct: float
    reasoning: str
    specialist: str
    latency_ms: float = 0.0
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleResult:
    action: str
    confidence: float
    position_pct: float
    reasoning: str           # consensus summary
    vote_count: int
    vote_breakdown: Dict[str, int]  # action -> count
    specialists: List[Vote]
    consensus_level: str     # "strong" (>80%), "moderate" (60-80%), "weak" (<60%)
    total_latency_ms: float


class Ensemble:
    """Multi-specialist voting system for trading decisions."""

    def __init__(self, pool: Any = None, adapter: str = "ptolemy-s0",
                 active_specialists: List[str] = None):
        self.pool = pool
        self.adapter = adapter
        self.active = active_specialists or list(SPECIALISTS.keys())

        self.thresholds: Dict[str, float] = {
            "invest": 0.5,       # min buy vote ratio to execute
            "divest": 0.75,      # sell ratio to force sell
            "min_confidence": 0.3,  # min per-specialist confidence
        }

        self.voting_smooth: Dict[str, float] = {}
        self.history: List[EnsembleResult] = []

    def vote(self, market_context: str,
             symbol: str = "BTC/USDT",
             timeout_per_specialist: float = 20.0) -> Optional[EnsembleResult]:
        if not self.pool:
            logger.warning("Ensemble: no model pool")
            return None

        votes: List[Vote] = []
        total_latency = 0.0

        for spec_key in self.active:
            spec = SPECIALISTS.get(spec_key)
            if not spec:
                continue

            t0 = time.time()
            try:
                raw = self.pool.generate(
                    self.adapter,
                    spec["system"],
                    f"Market Data ({symbol}):\n{market_context}",
                    max_tokens=200,
                    temperature=0.4,
                    json_output=True,
                    timeout=timeout_per_specialist,
                )
            except Exception as e:
                logger.debug(f"Ensemble {spec_key} error: {e}")
                continue

            elapsed = (time.time() - t0) * 1000
            total_latency += elapsed

            parsed = self._parse_vote(raw, spec_key)
            if parsed:
                parsed.latency_ms = elapsed
                if parsed.confidence >= self.thresholds.get("min_confidence", 0.3):
                    votes.append(parsed)

        if not votes:
            logger.info(f"Ensemble: no valid votes for {symbol}")
            return None

        result = self._aggregate(votes, symbol, total_latency)
        self.history.append(result)
        return result

    def _parse_vote(self, raw: Optional[str], specialist: str) -> Optional[Vote]:
        if not raw:
            return None
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("{") and "}" in line:
                try:
                    data = json.loads(line)
                    return Vote(
                        action=data.get("action", "HOLD").upper(),
                        confidence=float(data.get("confidence", 0.3)),
                        position_pct=float(data.get("position_pct", 0.05)),
                        reasoning=data.get("reasoning", data.get("reason", "no reason given")),
                        specialist=specialist,
                        raw=data,
                    )
                except (json.JSONDecodeError, ValueError):
                    continue
        return None

    def _aggregate(self, votes: List[Vote], symbol: str,
                   total_latency: float) -> EnsembleResult:
        counts: Dict[str, int] = {"BUY": 0, "SELL": 0, "HOLD": 0}
        buy_conf = 0.0
        sell_conf = 0.0

        for v in votes:
            action = v.action if v.action in counts else "HOLD"
            counts[action] += 1
            if action == "BUY":
                buy_conf += v.confidence
            elif action == "SELL":
                sell_conf += v.confidence

        total = sum(counts.values())
        buy_ratio = counts["BUY"] / total if total > 0 else 0
        sell_ratio = counts["SELL"] / total if total > 0 else 0

        if sell_ratio >= self.thresholds["divest"]:
            action = "SELL"
            conf = sell_conf / max(counts["SELL"], 1)
        elif buy_ratio >= self.thresholds["invest"]:
            action = "BUY"
            conf = buy_conf / max(counts["BUY"], 1)
        else:
            action = "HOLD"
            conf = 0.1

        if buy_ratio > 0.8 or sell_ratio > 0.8:
            consensus = "strong"
        elif buy_ratio > 0.6 or sell_ratio > 0.6:
            consensus = "moderate"
        else:
            consensus = "weak"

        avg_pct = sum(v.position_pct for v in votes) / max(len(votes), 1)

        return EnsembleResult(
            action=action,
            confidence=round(min(conf, 1.0), 3),
            position_pct=round(avg_pct, 4),
            reasoning=f"Ensemble ({len(votes)}/{len(self.active)}): "
                      f"BUY={counts['BUY']} SELL={counts['SELL']} HOLD={counts['HOLD']} "
                      f"[{symbol}]",
            vote_count=total,
            vote_breakdown=counts,
            specialists=votes,
            consensus_level=consensus,
            total_latency_ms=round(total_latency, 1),
        )

    def get_last_vote_breakdown(self) -> Optional[Dict[str, List[str]]]:
        if not self.history:
            return None
        r = self.history[-1]
        out: Dict[str, List[str]] = {"BUY": [], "SELL": [], "HOLD": []}
        for v in r.specialists:
            out[v.action].append(f"{v.specialist}: {v.reasoning[:60]}")
        return out
