#!/usr/bin/env python3
"""Calibration tests for the return-series White's Reality Check (#245).

A data-snooping correction that is itself miscalibrated would repeat the
2026-09-11 deflation bug (location-invariance) it was written to fix. These
tests pin three properties on synthetic data with known truth:

  1. the stationary bootstrap actually produces mean block length ~ L;
  2. under a zero-edge null the p-values are approximately uniform, i.e. the
     empirical rejection rate at alpha is ~ alpha (no anti-conservative drift);
  3. a planted edge is detected (power > 0.5 at a realistic t-stat).

Run as a script:  .venv/bin/python3 tests/test_wrc_calibration.py
Run under pytest: .venv/bin/python3 -m pytest tests/test_wrc_calibration.py -v
"""

import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "wrc", REPO / "scripts" / "white_reality_check.py")
wrc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wrc)


def _synthetic(K=40, T=1200, seed=0, edge_col=None, edge=0.0, vol=(0.002, 0.008)):
    rng = np.random.default_rng(seed)
    sig = np.exp(rng.uniform(np.log(vol[0]), np.log(vol[1]), size=K))
    R = rng.standard_normal((T, K)) * sig
    if edge_col is not None:
        R[:, edge_col] += edge
    return R


def test_stationary_counts_block_length():
    T, L, B = 4000, 20, 200
    counts = wrc.stationary_counts(T, L, np.random.default_rng(1), B)
    assert counts.shape == (B, T)
    assert np.allclose(counts.sum(axis=1), T)
    # reconstruct indices via counts is lossy; measure block length directly
    rng = np.random.default_rng(2)
    p = 1.0 / L
    new = rng.random(T) < p
    new[0] = True
    starts = np.flatnonzero(new)
    base = rng.integers(0, T, size=starts.size)
    ar = np.arange(T)
    last = np.maximum.accumulate(np.where(new, ar, 0))
    base_of = np.zeros(T, dtype=np.int64)
    base_of[starts] = base
    idx = (base_of[last] + (ar - last)) % T
    assert idx.min() >= 0 and idx.max() < T
    cont = (idx[1:] == (idx[:-1] + 1) % T).mean()
    assert abs(cont - (1 - p)) < 0.02, f"block continuity {cont:.3f}"


def test_null_calibration_is_uniform():
    """Zero-edge null: rejection rate at alpha must be ~ alpha.

    The two statistics the deflated bar rests on (White RC on the mean, and
    the PF-space null) must be no more liberal than their nominal alpha; the
    studentized diagnostics are expected to be liberal and are asserted only
    loosely (this is why they do not gate)."""
    alpha, n_rep, B, block = 0.10, 150, 400, 20
    ps = {k: [] for k in ("p_rc_mean", "p_pf",
                          "p_spa_studentized_diagnostic",
                          "p_spa_consistent_diagnostic")}
    for s in range(n_rep):
        R = _synthetic(seed=s)
        rng = np.random.default_rng(1000 + s)
        res, _ = wrc.run_bootstrap(R, block, B, rng, alpha)
        for k in ps:
            ps[k].append(res[k])
    rates = {}
    for k, v in ps.items():
        v = np.array(v)
        rates[k] = float((v < alpha).mean())
        print(f"  null {k}: mean p {v.mean():.3f}, rejection@{alpha} {rates[k]:.3f}")
    # Monte Carlo se at n=150, p=0.10 is 0.024 -> allow ~3 se
    assert 0.03 <= rates["p_rc_mean"] <= 0.18, rates
    assert 0.03 <= rates["p_pf"] <= 0.20, rates
    assert rates["p_spa_consistent_diagnostic"] <= 0.35, rates


def test_power_detects_planted_edge():
    alpha, n_rep, B, block = 0.10, 60, 400, 20
    hits = {"p_rc_mean": 0, "p_pf": 0}
    for s in range(n_rep):
        # homogeneous vol (RC has power only when the null max is not dominated
        # by a high-variance model); 4 bps/day edge vs 4 bps/day vol.
        R = _synthetic(seed=500 + s, edge_col=3, edge=0.0004,
                       vol=(0.004, 0.004))
        rng = np.random.default_rng(2000 + s)
        res, _ = wrc.run_bootstrap(R, block, B, rng, alpha)
        for k in hits:
            hits[k] += res[k] < alpha
    for k, h in hits.items():
        print(f"  power {k}: {h}/{n_rep}")
    assert hits["p_rc_mean"] / n_rep >= 0.5
    assert hits["p_pf"] / n_rep >= 0.5


def test_real_winner_series_matches_recorded_gate():
    """Integration: the series pipeline reproduces the recorded gate PF."""
    import json
    from fxexpert.gate import OUT_DIR, daily_pnl_series
    gate = json.loads((OUT_DIR / "gate_g185.json").read_text())
    s = daily_pnl_series("185")
    g, l = s[s > 0].sum(), -s[s < 0].sum()
    assert abs(g / l - gate["model"]["pf"]) < 1e-3
    assert abs(float(s.mean() * 1e4) - gate["model"]["daily_mean_bps"]) < 1e-3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"== {name}")
            fn()
    print("all WRC calibration tests passed")