"""Parametric multiverse sampler — regime-switching jump-diffusion with a common
market factor.

This is the *immediate* generator: dependency-light (numpy/pandas), deterministic
per seed, and it emits the exact ``{sym: DataFrame}`` shape the arena war consumes.
It also serves as the distributional baseline the neural generator is measured
against in ``scenarios.evaluate`` (a GAN that adds no diversity over this sampler
is not worth its VRAM). Once ``NeuralMarketGenerator`` is trained (GPU1 idle
windows), ``MarketScenarioGenerator`` upgrades to it for the everyday multiverse;
the tail library injects crises on top of either.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from scenarios.spec import DEFAULT_UNIVERSE, REGIME_BEAR, REGIME_BULL, REGIME_CRISIS, ScenarioSpec
from scenarios.tail_library import TailEvent

# Deterministic beta map (seeded) so worlds are reproducible per symbol.
_BETA_RNG = np.random.RandomState(7)
_BETAS: Dict[str, float] = {s: float(np.clip(_BETA_RNG.normal(1.0, 0.2), 0.6, 1.5)) for s in DEFAULT_UNIVERSE}

_REGIME_PARAMS = {
    REGIME_BULL: {"drift": 0.0012, "vol": 0.012},
    REGIME_BEAR: {"drift": -0.0010, "vol": 0.018},
    "range": {"drift": 0.0001, "vol": 0.009},
    REGIME_CRISIS: {"drift": -0.0030, "vol": 0.030},
}

TRADEABLES = [s for s in DEFAULT_UNIVERSE if s != "SPY"]


def _regime_params(spec: ScenarioSpec) -> Dict[str, float]:
    p = dict(_REGIME_PARAMS.get(spec.regime, _REGIME_PARAMS["range"]))
    p["vol"] *= spec.vol_mult
    p["drift"] = spec.drift if spec.regime == "range" else p["drift"]
    return p


def _ohlcv_from_close(sym: str, close: np.ndarray, vol: np.ndarray, index, rng) -> pd.DataFrame:
    n = len(close)
    prev = np.empty(n)
    prev[0] = close[0]
    prev[1:] = close[:-1]
    open_ = prev
    # intra-bar range scales with the bar's vol
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


def generate(spec: ScenarioSpec) -> Dict[str, pd.DataFrame]:
    """Generate one multivariate OHLCV world from a scenario spec.

    Cross-symbol correlation is induced by a shared market factor (SPY proxy):
    ``r_sym = beta_sym * r_factor + idio``, where idio vol is set so the realized
    pairwise correlation lands near ``spec.correlation`` on average.
    """
    rng = np.random.RandomState(spec.seed)
    n = spec.n_bars
    syms = list(spec.symbols) if spec.symbols else list(DEFAULT_UNIVERSE)
    # Every world needs a regime marker: the war's align() keys on data['SPY'].
    # A caller-supplied universe that omits SPY silently produced un-warr-able
    # worlds; enforce the marker instead of letting it fail downstream.
    if "SPY" not in syms:
        syms = ["SPY"] + syms
    rp = _regime_params(spec)

    # Market factor path (regime marker / SPY proxy). A mid-world structural
    # break flips the regime params at bar_frac — the world's factor, drift
    # and vol all switch, so downstream gates see a real regime shift.
    break_bar = None
    if spec.regime_break:
        frac, new_regime = spec.regime_break
        break_bar = int(n * float(frac))
        rp_break = dict(_REGIME_PARAMS.get(new_regime, _REGIME_PARAMS["range"]))
        rp_break["vol"] *= spec.vol_mult
    factor_ret = rng.normal(rp["drift"], rp["vol"], n)
    if break_bar is not None:
        factor_ret[break_bar:] = rng.normal(rp_break["drift"], rp_break["vol"],
                                            n - break_bar)
    jumps = rng.uniform(size=n) < spec.jump_p
    jump_amp = rng.normal(0, 3.0, n)
    factor_ret[jumps] += jump_amp[jumps] * rp["vol"]
    factor = np.exp(np.cumsum(factor_ret))

    # Common-factor ratio controls correlation: idio vol = k * factor vol.
    k = max(0.05, (1.0 - spec.correlation) / (spec.correlation + 1e-6)) * 0.6

    index = pd.bdate_range(end=datetime.now(timezone.utc).date(), periods=n)

    data: Dict[str, pd.DataFrame] = {}
    for s in syms:
        beta = _BETAS.get(s, 1.0)
        idio = rng.normal(0, rp["vol"] * k, n)
        ret = beta * factor_ret + idio
        close = float(getattr(spec, "_start_price", 100.0 if s == "SPY" else 50.0)) * np.exp(np.cumsum(ret))
        if s == "SPY":
            data[s] = _ohlcv_from_close(s, factor * 100.0, np.full(n, rp["vol"]), index, rng)
        else:
            data[s] = _ohlcv_from_close(s, close, np.full(n, rp["vol"]), index, rng)
    return data


def inject_event(data: Dict[str, pd.DataFrame], event: TailEvent, seed: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """Apply a tail event's shock profile onto the last ``window_frac`` of bars of
    every tradeable. The SPY/market-factor proxy is shocked too so the regime
    marker reflects the crisis.

    Returns a new dict (does not mutate the input).
    """
    sh = event.shock
    rng = np.random.RandomState(seed)
    out = {}
    for sym, df in data.items():
        df = df.copy()
        n = len(df)
        w = max(3, int(n * sh.get("window_frac", 0.2)))
        i0 = n - w
        close = df["close"].to_numpy().copy()
        ret = np.empty(n)
        ret[0] = 0.0
        ret[1:] = np.log(close[1:] / close[:-1])
        base_vol = float(np.std(ret[1:100])) + 1e-9
        vol_mult = float(sh.get("vol_mult", 2.0))
        drift = float(sh.get("drift_impact", -0.005))
        recovery = sh.get("recovery", "u")
        gap_risk = float(sh.get("gap_risk", 0.02))
        for t in range(i0, n):
            frac = (t - i0) / max(1, w)
            # recovery shape modulates drift across the window
            shape = 1.0
            if recovery == "v":
                shape = 2.0 * max(0.0, 1.0 - 2 * frac)  # strong early, fades to bounce
            elif recovery == "grind":
                shape = 1.0
            elif recovery == "u":
                shape = 1.0 - 0.5 * frac
            r = drift * shape * (1 + 2 * frac) * 0.5
            if rng.uniform() < gap_risk:
                r += rng.normal(0, 4.0) * base_vol * vol_mult
            ret[t] = r
        new_close = close[0] * np.exp(np.cumsum(ret))
        vol_vec = df["volume"].to_numpy().copy()
        vol_vec[i0:] = vol_vec[i0:] * (1.0 + 2.0 * (vol_mult - 1.0) * 0.3)
        df["close"] = new_close
        df["high"] = np.maximum(df["high"].to_numpy(), new_close)
        df["low"] = np.minimum(df["low"].to_numpy(), new_close)
        df["volume"] = vol_vec
        out[sym] = df
    return out


def generate_with_event(spec: ScenarioSpec, event: TailEvent) -> Dict[str, pd.DataFrame]:
    data = generate(spec)
    return inject_event(data, event, seed=spec.seed)
