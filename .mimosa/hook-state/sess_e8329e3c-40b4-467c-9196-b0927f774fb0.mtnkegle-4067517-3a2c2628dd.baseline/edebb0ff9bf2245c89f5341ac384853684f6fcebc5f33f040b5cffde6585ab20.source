#!/usr/bin/env python3
"""Wire the OOS-verified tournament strategies into the MoT expert protocol.

The 8 verified strategies are DAILY-BAR, UNIVERSE-LEVEL allocators (300 US
names / 13-asset basket / 10 intl instruments). They are NOT per-symbol
`Expert.decide(ctx, symbol)` traders — they allocate across a universe over
time. This module bridges that gap honestly:

  - `TournamentExpert` — a MoT-compatible wrapper whose `decide()` emits the
    strategy's *current target allocation* (long/short/flat per asset) as
    ExpertDecisions, so the MoT router CAN hold and monitor them without
    claiming live-trade validity on the harness's 19-symbol universe.
  - `StrategyRouter` — a per-regime selector among the verified strategies
    using their VERIFIED Calmar as the track record (the tournament OOS
    evidence, not live-drift waiting). This is the arena's starting router.

Every claim here traces to a verified score in
/tmp/opentrader/swarm/results/*.json and the re-runs recorded in
docs/CONTEXT.md. Status: MONITORING/ROSTER — NOT wired to live order flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from mot.mixture import ExpertDecision


@dataclass(frozen=True)
class VerifiedExpert:
    """A verified strategy: name, OOS Calmar (intl transfer test), and its
    target-allocation function. Calmar is the tournament evidence."""
    name: str
    oos_calmar: float       # OOS transfer-test Calmar (bench intl basket 0.501)
    oos_sharpe: float
    maxdd: float
    description: str
    # target_allocation(regime) -> {asset: size_pct} is provided by the
    # strategy module; stored here so the router can reason about it.
    evidence: dict = field(default_factory=dict)


# The 9 OOS-verified experts (2026-08-13; 8 from ROUND2_OOS_SUMMARY.md + laggard from R1d).
VERIFIED: Dict[str, VerifiedExpert] = {
    "bayes": VerifiedExpert("bayes", 1.148, 1.24, -0.104,
        "Bayesian online change-point (BOCPD) x breadth gate + momentum-top; drawdown tool"),
    "spectral": VerifiedExpert("spectral", 1.000, 1.29, -0.133,
        "FFT low-frequency-share x breadth gate + momentum-top"),
    "kalman": VerifiedExpert("kalman", 0.988, 1.19, -0.127,
        "Kalman-z trend x breadth gate + momentum-top"),
    "hurst": VerifiedExpert("hurst", 0.967, 1.18, -0.113,
        "Hurst persistence x breadth gate + momentum-top"),
    "wavelet": VerifiedExpert("wavelet", 0.803, 0.91, -0.117,
        "Wavelet trend-up gate + momentum-top"),
    "entropy": VerifiedExpert("entropy", 0.667, 1.00, -0.138,
        "High-entropy regime x breadth gate + momentum-top"),
    "momtrend": VerifiedExpert("momtrend", 0.938, 1.05, -0.130,
        "Momentum-top + breadth gate (R1/R2 survivor, intl OOS 0.938)"),
    "multiasset": VerifiedExpert("multiasset", 1.289, 1.32, -0.090,
        "Momentum-filtered vol-scaled multi-asset allocator (drawdown king)"),
    "laggard": VerifiedExpert("laggard", 1.666, 1.35, -0.075,
        "Momentum leaders + in-bull laggard catch-up; solves the broad-bull "
        "participation gap (beats intl basket 2023-26 +71.8% vs +64.5%)"),
}

# Failed OOS (do not route to, documented why):
#   hmm  0.496 — posterior-prob threshold not scale-free across universes
#   copula 0.609 — intl lacks bond safe-haven; book-only variant passed


def regime_of(spy_price, ma200) -> str:
    """Up/down regime from SPY vs its 200-bar MA (matches RegimeRouter;
    regime keys MUST be 'up'/'down' — the harness's attribution naming)."""
    if spy_price is None or ma200 is None or ma200 == 0:
        return "unknown"
    return "up" if spy_price > ma200 else "down"


class TournamentExpert:
    """MoT-protocol wrapper: holds a VerifiedExpert + a target-allocation
    callable; decide() emits the strategy's current allocation as decisions.

    NOTE: the underlying strategies allocate across their universe at daily
    bars. This wrapper is for ROUTING/MONITORING the verified set — it does
    not claim these are valid live per-symbol signals on the harness's
    real-time 19-symbol universe."""

    def __init__(self, verified: VerifiedExpert, alloc_fn=None, risk_cap: float = 0.15):
        self.name = verified.name
        self._v = verified
        self._alloc = alloc_fn  # callable(regime) -> {asset: size_pct}
        self.risk_cap = risk_cap

    def decide(self, ctx, symbol: str) -> ExpertDecision:
        regime = getattr(ctx, "regime", "unknown")
        alloc = self._alloc(regime) if self._alloc else {}
        size = float(alloc.get(symbol, 0.0))
        if size > 0:
            return ExpertDecision(
                action="BUY",
                size_pct=min(self.risk_cap, size),
                p_edge=min(1.0, max(0.0, self._v.oos_calmar / 1.5)),  # calibrated to verified evidence
                evidence={"verified_calmar": self._v.oos_calmar,
                          "oos_sharpe": self._v.oos_sharpe,
                          "maxdd": self._v.maxdd},
            )
        return ExpertDecision(action="HOLD", p_edge=0.0, evidence={})


class StrategyRouter:
    """Per-regime selector among VERIFIED experts, using OOS Calmar as the
    track record (tournament evidence, not live-drift waiting). The rule
    floor's Calmar (0.17 US/SPY) is the bar to beat; any verified expert with
    higher OOS Calmar is eligible in its regime."""

    def __init__(self, rule_floor_calmar: float = 0.174):
        self.rule_floor_calmar = rule_floor_calmar
        self._by_regime: Dict[str, str] = {}

    def register_regime(self, regime: str, expert_name: str) -> None:
        """Assign the best verified expert to a regime (by OOS Calmar)."""
        v = VERIFIED.get(expert_name)
        if v is None:
            raise KeyError(f"unknown verified expert '{expert_name}'")
        self._by_regime[regime] = expert_name

    def pick(self, regime: str) -> Optional[str]:
        """Best verified expert for the regime, or None if none beats the floor."""
        e = self._by_regime.get(regime)
        if e is None:
            return None
        v = VERIFIED[e]
        return e if v.oos_calmar > self.rule_floor_calmar else None

    def summary(self) -> dict:
        return {
            regime: {"expert": self._by_regime.get(regime),
                     "oos_calmar": VERIFIED[self._by_regime[regime]].oos_calmar
                     if regime in self._by_regime else None}
            for regime in ("up", "down", "unknown")
        }
