"""Curated tail-event library — the crisis realities the everyday generator
under-samples.

Neural generators (GANs) are notorious for smoothing over tails: they learn the
modal path and under-sample exactly the black-swan events a trader needs to be
robust to. This library is the countermeasure. Each event is a *bar-level shock
profile* that can be injected onto any base path (generated or real), so the
multiverse gets grounded crisis fidelity for events the archive lacks (2011/2013
debt-ceiling, 2020 COVID) and the generator's own tail is never trusted alone.

Each event carries its real-world analogs + primary-ish sources so the shock
parameters are calibrated to what actually happened, not invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TailEvent:
    id: str
    name: str
    description: str
    analogs: list
    sources: list
    # Shock profile consumed by scenarios.parametric.inject_event:
    #   vol_mult      multiplier applied to per-bar vol during the shock window
    #   drift_impact  additional per-bar drift during the shock window (neg = down)
    #   recovery      'v' (fast snap-back), 'u' (slow recovery), 'grind' (no recovery,
    #                 persistent vol), 'gap' (overnight jump, thin books)
    #   window_frac   fraction of the series that is the shock (0..1)
    #   gap_risk      probability of a multi-sigma overnight gap per bar in the window
    shock: Dict[str, float] = field(default_factory=dict)


EVENTS: Dict[str, TailEvent] = {}


def _reg(id, name, description, analogs, sources, shock):
    e = TailEvent(id=id, name=name, description=description,
                  analogs=analogs, sources=sources, shock=shock)
    EVENTS[id] = e


_reg(
    "us_debt_ceiling",
    "US debt-ceiling / UST-spread risk-off",
    "Treasury yield spike + equity de-rate + credit-spread widening as a US "
    "sovereign-payment standoff unfolds. Slow onset, multi-week-to-month shock, "
    "partial recovery once resolved. The user's named tail: a US-based trader is "
    "directly exposed to this reality.",
    ["2011 US debt-ceiling crisis", "2013 sequestration/debt-limit", "2023 debt-ceiling standoff"],
    ["https://en.wikipedia.org/wiki/2011_United_States_debt-ceiling_crisis",
     "https://en.wikipedia.org/wiki/2023_United_States_debt-ceiling_crisis"],
    {"vol_mult": 2.5, "drift_impact": -0.004, "recovery": "u", "window_frac": 0.25, "gap_risk": 0.02},
)

_reg(
    "covid_crash",
    "Pandemic fast-crash with V-recovery",
    "Rapid -25-35% drawdown over ~4 weeks as risk is indiscriminately sold, then a "
    "powerful V-recovery as policy response lands. Tests whether a policy holds cash "
    "through the trough instead of capitulating at the bottom.",
    ["Mar-2020 COVID crash"],
    ["https://en.wikipedia.org/wiki/2020_stock_market_crash"],
    {"vol_mult": 4.0, "drift_impact": -0.015, "recovery": "v", "window_frac": 0.15, "gap_risk": 0.05},
)

_reg(
    "bear_grind_2022",
    "Prolonged bear grind",
    "Slow, persistent -20-30% grind over many months with elevated vol and "
    "dead-cat bounces, no V-recovery. Kills trend-chasing momentum strategies and "
    "exposes buy-the-dip rules that worked in bull regimes.",
    ["2022 bear market"],
    ["https://en.wikipedia.org/wiki/2022_stock_market_decline"],
    {"vol_mult": 1.8, "drift_impact": -0.002, "recovery": "grind", "window_frac": 0.5, "gap_risk": 0.02},
)

_reg(
    "yen_unwind",
    "Carry-trade unwind contagion",
    "Sharp 1-2 week -10%+ global selloff as yen carry trades liquidate under a vol "
    "spike, correlated across assets, then a fast partial recovery. Tests gap and "
    "stop-loss behavior during a correlated stampede.",
    ["Aug-2024 yen-carry unwind"],
    ["https://en.wikipedia.org/wiki/Carry_(investment)"],
    {"vol_mult": 3.5, "drift_impact": -0.01, "recovery": "v", "window_frac": 0.1, "gap_risk": 0.08},
)

_reg(
    "flash_crash",
    "Flash crash / liquidity vacuum",
    "Intraday-hourly -5-10% vertical move and snap-back as liquidity evaporates; "
    "stops get gapped and filled at bad prices. Tests the order-fill assumptions a "
    "paper sandbox normally hides.",
    ["2010 Flash Crash", "2019 JPY flash crash"],
    ["https://en.wikipedia.org/wiki/2010_Flash_Crash"],
    {"vol_mult": 5.0, "drift_impact": -0.02, "recovery": "v", "window_frac": 0.05, "gap_risk": 0.15},
)

_reg(
    "liquidity_gap",
    "Liquidity gap / thin books",
    "Volume collapses and prices gap between bars; wide open-close ranges, stop-outs "
    "at adverse fills. The multi-asset analogue of a margin-call cascade.",
    ["LTCM 1998", "3x leveraged ETF deleveraging events"],
    ["https://en.wikipedia.org/wiki/Long-Term_Capital_Management"],
    {"vol_mult": 2.0, "drift_impact": -0.003, "recovery": "u", "window_frac": 0.2, "gap_risk": 0.2},
)

_reg(
    "currency_crisis",
    "Emerging-market currency crisis",
    "Local-currency devaluation + capital flight; the international 'brewing problem' "
    "class — one region's shock transmits through correlated exposure.",
    ["1997 Asian financial crisis", "2022-23 EM stress"],
    ["https://en.wikipedia.org/wiki/1997_Asian_financial_crisis"],
    {"vol_mult": 3.0, "drift_impact": -0.008, "recovery": "grind", "window_frac": 0.2, "gap_risk": 0.1},
)

_reg(
    "fed_hike_surprise",
    "Rate-hike / hawkish-surprise de-rate",
    "Duration-sensitive selloff as the central bank surprises hawkish; growth and "
    "long-duration equities lead down, defensives hold relatively. Slow-to-medium "
    "shock, persistent.",
    ["2022 Fed hiking cycle", "2013 Taper Tantrum"],
    ["https://en.wikipedia.org/wiki/2013_taper_tantrum"],
    {"vol_mult": 2.2, "drift_impact": -0.005, "recovery": "u", "window_frac": 0.2, "gap_risk": 0.03},
)


def list_events() -> list:
    return [{"id": e.id, "name": e.name} for e in EVENTS.values()]


def get_event(event_id: str) -> Optional[TailEvent]:
    return EVENTS.get(event_id)
