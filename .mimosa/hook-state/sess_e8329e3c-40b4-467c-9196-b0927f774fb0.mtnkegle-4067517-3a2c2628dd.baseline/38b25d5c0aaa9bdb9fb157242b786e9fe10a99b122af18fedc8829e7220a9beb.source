#!/usr/bin/env python3
"""Mixture of Traders — core architecture (wayfinder #39).

- ExpertDecision: the uniform contract every expert emits.
- Expert: the Protocol every market model implements (rule config, ADIR
  debate, value head, future sentiment/crypto/international experts).
- RegimeRouter: the mixture — regime-based (SPY vs 200d) selection with a
  RULE-FLOOR PRIOR. The rule floor holds all weight until an expert earns it
  via validated per-regime track records; weight shifts (+0.1/window, cap 0.5)
  only after consecutive validated windows; any failure resets to the floor.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol
import math


def _isfinite(v) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


@dataclass
class ExpertDecision:
    action: str  # BUY / SELL / HOLD
    size_pct: float = 0.0  # portfolio fraction 0..1
    p_edge: float = 0.0  # calibrated 0..1 probability of positive edge
    evidence: Dict[str, Any] = field(default_factory=dict)


class Expert(Protocol):
    name: str

    def decide(self, ctx: Any, symbol: str) -> ExpertDecision:
        """Given the market/context state, propose a decision for `symbol`."""
        ...


class RuleExpert:
    """The validated rule config as an expert (the incumbent floor)."""

    def __init__(self, cfg: Optional[dict] = None, rule_gate=None):
        self.name = "rule"
        self.cfg = cfg
        self.rule_gate = rule_gate  # optional screen module

    def decide(self, ctx: Any, symbol: str) -> ExpertDecision:
        # The rule decides take iff its screen passes; p_edge from the screen score.
        score = getattr(ctx, "rule_score", 0.0)
        regime_ok = getattr(ctx, "regime_ok", True)
        action = "BUY" if (regime_ok and score >= self.cfg.get("buy_thresh", 0.0)) else "HOLD"
        return ExpertDecision(
            action=action,
            size_pct=self.cfg.get("risk_pct", 0.05) if action == "BUY" else 0.0,
            p_edge=min(1.0, max(0.0, (score + 1.0) / 2.0)),
            evidence={"score": score, "regime_ok": regime_ok},
        )


class AdirExpert:
    """The ADIR debate as an expert (proposes; gated by the router)."""

    def __init__(self):
        self.name = "adir"

    def decide(self, ctx: Any, symbol: str) -> ExpertDecision:
        signal = getattr(ctx, "debate_signal", None)
        if signal is None:
            return ExpertDecision(action="HOLD", p_edge=0.0, evidence={})
        return ExpertDecision(
            action=signal.action,
            size_pct=getattr(signal, "position_pct", 0.0),
            p_edge=min(1.0, max(0.0, getattr(signal, "confidence", 0.0))),
            evidence={"reason": getattr(signal, "reason", "")},
        )


class RegimeRouter:
    """Mixture router: per-regime argmax by mean per-trade impact, rule-floor prior."""

    def __init__(self, rule_floor: str = "rule", min_evidence: int = 5,
                 shift: float = 0.1, cap: float = 0.5):
        self.rule_floor = rule_floor
        self.min_evidence = min_evidence
        self.shift = shift
        self.cap = cap
        self.track: Dict[str, Dict[str, Dict[str, float]]] = {}  # regime -> expert -> {sum,n}
        self.weights: Dict[str, Dict[str, float]] = {}  # regime -> expert -> w

    def regime_of(self, spy: Any, date) -> str:
        try:
            ma200 = spy.rolling(200, min_periods=60).mean()
            v = ma200.get(date)
            return "bull" if v is not None and float(spy[date]) > float(v) else "bear"
        except Exception:
            return "unknown"

    def record(self, regime: str, expert: str, impact: float) -> None:
        if not _isfinite(impact):
            return  # a NaN/inf impact would silently corrupt the track record
        self.track.setdefault(regime, {}).setdefault(expert, {"sum": 0.0, "n": 0})
        self.track[regime][expert]["sum"] += impact
        self.track[regime][expert]["n"] += 1

    def mean_impact(self, regime: str, expert: str) -> Optional[float]:
        t = self.track.get(regime, {}).get(expert)
        if not t or t["n"] == 0:
            return None
        return t["sum"] / t["n"]

    def pick(self, regime: str) -> str:
        """Which expert acts in this regime (rule-floor prior).

        The rule holds unless an expert with >= min_evidence strictly beats the
        rule's own mean impact in this regime. If the rule has no record yet, the
        floor holds (no baseline to beat). Eligibility comes from the weight
        schedule when step() has run; until then every tracked expert is
        eligible, so the earning mechanism is reachable without step()."""
        if regime not in self.track:
            return self.rule_floor
        rule_imp = self.mean_impact(regime, self.rule_floor)
        if rule_imp is None:
            return self.rule_floor
        w = self.weights.get(regime)
        candidates = [
            e for e in self.track[regime]
            if e != self.rule_floor and (w is None or w.get(e, 0.0) > 0)
        ]
        best, best_impact = self.rule_floor, rule_imp
        for e in candidates:
            imp = self.mean_impact(regime, e)
            n = self.track[regime].get(e, {}).get("n", 0)
            if imp is None or n < self.min_evidence:
                continue
            if imp > best_impact:
                best, best_impact = e, imp
        return best

    def step(self, validated_windows: Dict[str, int]) -> None:
        """After consecutive validated windows per (regime, expert), shift weight
        +shift toward the expert (cap), or reset to the floor on a failure."""
        for regime, expert in validated_windows:
            self.weights.setdefault(regime, {self.rule_floor: 1.0})
            if validated_windows[(regime, expert)] >= 1:
                cur = self.weights[regime].get(expert, 0.0)
                self.weights[regime][expert] = min(self.cap, cur + self.shift)
                self.weights[regime][self.rule_floor] = 1.0 - self.weights[regime][expert]
            else:
                self.weights[regime] = {self.rule_floor: 1.0}
