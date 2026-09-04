#!/usr/bin/env python3
"""Resource-asset world simulation — scarce + renewable resources as tradable
assets inside multiverse worlds (#56 carry-forward, user directive 2026-08-11).

Two asset classes, both emitted as OHLCV DataFrames in the exact shape
`collect_from_data` / `run_war` consume ({symbol: DataFrame, SPY = marker}):

SCARCE (finite stock, depletion): gold, oil, rare earths, lithium, copper,
uranium. Price follows the Hotelling depletion law — a scarcity premium
grows as remaining stock falls; when stock crosses a critical floor the
world can gap (supply shock). The scarcity premium is the tradable edge:
the asset's momentum carries a depletion component real archives lack.

RENEWABLE (replenishing flow): solar, wind, carbon credits, water, timber.
Stock regenerates at a rate with seasonal + weather noise; price
mean-reverts to a supply/demand equilibrium that shifts with the world's
regime. The regeneration curve gives a slowly mean-reverting tradable
component — structurally different from both equities and scarce assets.

Both classes interact with the world regime: crisis worlds squeeze supply
(scarce prices spike, renewable flow drops), bull worlds see demand growth.
This lets the arena/hive discover cross-asset edges the 17-symbol equity
universe cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Asset registry
# ---------------------------------------------------------------------------

SCARCE_ASSETS = {
    "GOLD":  {"stock0": 200_000.0, "depletion": 0.0004, "floor": 0.25, "vol": 0.011},
    "OIL":   {"stock0": 1_200_000.0, "depletion": 0.0010, "floor": 0.20, "vol": 0.020},
    "RARE":  {"stock0": 80_000.0, "depletion": 0.0018, "floor": 0.30, "vol": 0.024},
    "LITH":  {"stock0": 300_000.0, "depletion": 0.0022, "floor": 0.25, "vol": 0.026},
    "COPPER": {"stock0": 900_000.0, "depletion": 0.0008, "floor": 0.20, "vol": 0.016},
    "URAN":  {"stock0": 60_000.0, "depletion": 0.0012, "floor": 0.35, "vol": 0.022},
}

RENEWABLE_ASSETS = {
    "SOLAR": {"regen": 0.0030, "capacity": 1_000.0, "vol": 0.014, "season": 0.30},
    "WIND":  {"regen": 0.0035, "capacity": 900.0, "vol": 0.020, "season": 0.20},
    "CARBON": {"regen": 0.0008, "capacity": 5_000.0, "vol": 0.025, "season": 0.10},
    "WATER": {"regen": 0.0020, "capacity": 2_500.0, "vol": 0.018, "season": 0.40},
    "TIMBER": {"regen": 0.0012, "capacity": 1_800.0, "vol": 0.012, "season": 0.15},
}

# Stored/inventory assets (world-archetypes-deep-dive.md §1): price is a
# function of inventory vs the seasonal norm — a carry-bearing state variable
# that equities never expose. Low inventory -> price spikes (gap risk);
# high inventory -> mean reversion down. NG = natural gas (EIA storage
# weekly), GRAIN = storable softs with harvest seasonality.
STORED_ASSETS = {
    "NG":   {"capacity": 3_900.0, "inject": 0.004, "withdraw": 0.006, "vol": 0.024,
             "season": 0.45, "gap_p": 0.03},
    "GRAIN": {"capacity": 2_000.0, "inject": 0.002, "withdraw": 0.004, "vol": 0.018,
              "season": 0.55, "gap_p": 0.02},
}

# Registry keys: what the generator iterates.
SCARCE_KEYS = list(SCARCE_ASSETS.keys())
RENEWABLE_KEYS = list(RENEWABLE_ASSETS.keys())
STORED_KEYS = list(STORED_ASSETS.keys())
RESOURCE_KEYS = SCARCE_KEYS + RENEWABLE_KEYS + STORED_KEYS


def _ohlcv(sym: str, close: np.ndarray, index: pd.DatetimeIndex, vol: np.ndarray, rng: np.random.RandomState) -> pd.DataFrame:
    n = len(close)
    prev = np.empty(n)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    open_ = prev
    hi_lo = np.abs(rng.normal(0, 1, n)) * vol * 0.5
    high = np.maximum(open_, close) + hi_lo
    low = np.minimum(open_, close) - hi_lo * 0.6
    d_close = np.abs(close[1:] - close[:-1]) * 50.0
    vol_vec = np.concatenate([
        [rng.lognormal(np.log(1e6 + 1e-3), 0.5)],
        rng.lognormal(np.log(1e6 + d_close), 0.5),
    ])
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol_vec},
        index=index,
    )
    df.columns.name = None
    return df


def _scarce_path(sym: str, n: int, regime: str, crisis: bool, rng: np.random.RandomState) -> tuple:
    """Hotelling depletion path: scarcity premium grows as stock falls."""
    p = SCARCE_ASSETS[sym]
    stock = np.empty(n)
    stock[0] = p["stock0"]
    price = np.empty(n)
    price[0] = 100.0
    demand = 1.0 + (0.10 if regime == "bull" else -0.05 if regime == "bear" else 0.0)
    crisis_mult = 1.8 if crisis else 1.0  # crises squeeze supply
    for t in range(1, n):
        frac = stock[t - 1] / p["stock0"]
        depletion = p["depletion"] * demand * (crisis_mult if t > n * 0.6 else 1.0)
        stock[t] = max(0.0, stock[t - 1] * (1.0 - depletion))
        # scarcity premium: grows super-linearly as frac -> floor, capped at a
        # few bp/bar (realistic depletion drift, not a compounding blowup)
        scarcity = max(0.0, 1.0 - frac) ** 2.0
        premium = scarcity * 0.0025
        # crisis supply squeeze: scarce assets spike as supply is rationed
        squeeze = (crisis_mult - 1.0) * 0.004 if crisis and t > n * 0.5 else 0.0
        shock = 0.0
        if frac < p["floor"] and rng.uniform() < 0.05:
            shock = rng.normal(0, 4.0) * p["vol"]  # exhaustion gap
        ret = p["vol"] * rng.normal(0, 1) + premium + squeeze + shock
        price[t] = price[t - 1] * (1.0 + ret)
    return price, np.full(n, p["vol"])


def _renewable_path(sym: str, n: int, regime: str, crisis: bool, rng: np.random.RandomState) -> tuple:
    """Regeneration + mean reversion: price reverts to an equilibrium that
    shifts with supply (stock level) and regime demand."""
    p = RENEWABLE_ASSETS[sym]
    stock = np.empty(n)
    stock[0] = p["capacity"] * 0.8
    price = np.empty(n)
    price[0] = 100.0
    demand = 1.0 + (0.06 if regime == "bull" else -0.08 if regime == "bear" else 0.0)
    crisis_flow = 0.55 if crisis else 1.0  # crises cut generation
    for t in range(1, n):
        season = 1.0 + p["season"] * np.sin(2 * np.pi * t / 250.0)
        weather = 1.0 + rng.normal(0, 0.10)
        regen = p["regen"] * season * weather * crisis_flow
        stock[t] = min(p["capacity"], stock[t - 1] + (p["capacity"] - stock[t - 1]) * regen)
        # equilibrium price rises when stock is low (short supply)
        eq = 100.0 * (1.0 + 0.6 * (1.0 - stock[t] / p["capacity"]) - 0.1 * (demand - 1.0))
        mean_rev = 0.06 * (eq - price[t - 1]) / 100.0
        ret = p["vol"] * rng.normal(0, 1) + mean_rev
        price[t] = price[t - 1] * (1.0 + ret)
    return price, np.full(n, p["vol"])


def _stored_path(sym: str, n: int, regime: str, crisis: bool, rng: np.random.RandomState) -> tuple:
    """Inventory-driven storage asset (EIA-style): price depends on inventory
    vs the seasonal norm; gaps when inventory dives below a stress threshold.
    Carry + seasonality + gap risk — a mean-reverting trap for trend-chasers."""
    p = STORED_ASSETS[sym]
    inv = np.empty(n)
    inv[0] = p["capacity"] * 0.55
    price = np.empty(n)
    price[0] = 100.0
    demand = 1.0 + (0.08 if regime == "bull" else -0.10 if regime == "bear" else 0.0)
    crisis_short = 1.5 if crisis else 1.0
    for t in range(1, n):
        season = 0.5 + 0.5 * np.sin(2 * np.pi * (t + (0.15 * n)) / 250.0)
        # harvest-season injection vs winter withdrawal, mean-zero over a cycle:
        # inject/withdraw are equal weights so inventory oscillates, not drifts
        flow = p["inject"] * season - p["inject"] * (1.0 - season)
        inv[t] = min(p["capacity"], max(0.0, inv[t - 1] + (p["capacity"] * flow * demand * crisis_short)))
        fill = inv[t] / p["capacity"]
        norm = 0.55  # seasonal norm: above = bearish, below = bullish
        carry = 0.0025 * (norm - fill)  # bp-scale inventory-vs-norm premium
        gap = 0.0
        if fill < 0.15 and rng.uniform() < p["gap_p"]:
            gap = rng.normal(2.5, 1.0) * p["vol"]  # storage-stress gap UP
        ret = p["vol"] * rng.normal(0, 1) + carry + gap
        price[t] = price[t - 1] * (1.0 + ret)
    return price, np.full(n, p["vol"])


def generate_resource_assets(spec, index: pd.DatetimeIndex) -> Dict[str, pd.DataFrame]:
    """Generate the resource-asset OHLCV frames for one world.

    spec: a ScenarioSpec-like object (regime, seed, n_bars, symbols).
    Returns a dict of {SYMBOL: DataFrame} to merge into the world data.
    """
    from scenarios.spec import REGIME_BULL, REGIME_BEAR, REGIME_CRISIS

    rng = np.random.RandomState((spec.seed or 0) + 99_991)
    n = spec.n_bars
    regime = spec.regime
    crisis = regime == REGIME_CRISIS or spec.event is not None
    out: Dict[str, pd.DataFrame] = {}
    # All registered resources are tradable world assets — they are the point
    # of resource worlds, independent of the base spec's symbol list.
    for sym in SCARCE_KEYS:
        price, vol = _scarce_path(sym, n, regime, crisis, rng)
        out[sym] = _ohlcv(sym, price, index, vol, rng)
    for sym in RENEWABLE_KEYS:
        price, vol = _renewable_path(sym, n, regime, crisis, rng)
        out[sym] = _ohlcv(sym, price, index, vol, rng)
    for sym in STORED_KEYS:
        price, vol = _stored_path(sym, n, regime, crisis, rng)
        out[sym] = _ohlcv(sym, price, index, vol, rng)
    return out
