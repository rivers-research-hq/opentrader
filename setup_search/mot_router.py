#!/usr/bin/env python3
"""MoT router demonstration (wayfinder #39): rule vs value-head as experts.

Builds the shared daily candidate set (5y, loosened data-gen screen), trains a
value head on the bull window, then runs the regime router over per-regime
per-trade impact. Shows:
- per-regime (SPY>200d) mean impact for the RULE floor vs the VALUE expert,
- the router's picks (rule-floor prior, min-evidence gate),
- the rule-floor-prior rollout across the walk-forward windows.

Experts are compared on the SAME candidate set via per-trade impact
(pnl/equity-at-entry), never compounded returns across horizons.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from mot.mixture import RegimeRouter
from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
FORWARD = 10
TRAIN = (0, 1000)             # forward-only (audit 2026-08-11), matches value_head/arena
TESTS = [(1000, 1250)]        # gate only the unseen future (w0 bear era not discriminable — #68)
GEN_SCORE_MIN = -0.5
SEED = 31
FEAT_COLS = ["mom", "rev", "rsi", "brk", "z", "ma_dist", "vol_spike", "vol_level", "momfilt"]


def collect(closes, highs, lows, vols, cfg, spy, spy_ma200, master):
    feat = _features(closes, highs, lows, vols, cfg)
    w = cfg
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        score = (w["w_mom"] * f["mom"] + w["w_rev"] * f["rev"] + w["w_rsi"] * f["rsi"]
                 + w["w_brk"] * f["brk"] + w["w_z"] * f["z"])
        vals = f[FEAT_COLS].values.astype(np.float32)
        np.nan_to_num(vals, copy=False)
        fwd = (c.shift(-FORWARD) / c - 1.0).values
        sc = score.values
        regime_arr = None
        if spy is not None and spy_ma200 is not None:
            regime_arr = (spy > spy_ma200).reindex(c.index).astype(int).values
        n = len(c) - FORWARD
        for t in range(n):
            s = sc[t]
            if s != s or s < GEN_SCORE_MIN:
                continue
            date = c.index[t]
            if date not in master:
                continue
            regime = "bull" if (regime_arr is not None and regime_arr[t] == 1) else "bear"
            v = np.concatenate([vals[t], [s, 1.0]])
            rows.append({"sym": sym, "bar": master.get_loc(date), "x": v.astype(np.float32),
                         "fwd": float(fwd[t]), "score": float(s), "regime": regime})
    return rows


class ValueMLP(nn.Module):
    def __init__(self, d_in):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, 32), nn.ReLU(), nn.Dropout(0.2),
                                 nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def main():
    torch.manual_seed(SEED)
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, [s for s in data if s != REGIME_SYM])
    spy = al[0].get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    master = next(iter(al[0].values())).index
    rows = collect(al[0], al[1], al[2], al[3], base, spy, spy_ma200, master)
    trn = [r for r in rows if TRAIN[0] <= r["bar"] < TRAIN[1]]
    X = np.stack([r["x"] for r in trn])
    y = np.array([r["fwd"] for r in trn], dtype=np.float32)
    mean, std = X.mean(0), X.std(0)
    Xz = torch.tensor((X - mean) / (std + 1e-8))
    yt = torch.tensor(y)
    model = ValueMLP(X.shape[1])
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    for _ in range(120):
        opt.zero_grad()
        loss = lossf(model(Xz), yt)
        loss.backward()
        opt.step()
    model.eval()

    def vhead(rows):
        out = []
        for r in rows:
            z = torch.tensor((r["x"] - mean) / (std + 1e-8)).unsqueeze(0)
            with torch.no_grad():
                out.append(float(model(z).item()))
        return out

    def split_by_regime(rows):
        d = {}
        for r in rows:
            d.setdefault(r["regime"], []).append(r)
        return d

    router = RegimeRouter(rule_floor="rule", min_evidence=5)
    print("=== per-regime mean per-trade impact (rule vs value expert) ===")
    windows = [("train(500-1000)", TRAIN)] + [(f"test{lo}-{hi}", (lo, hi)) for lo, hi in TESTS]
    for label, (lo, hi) in windows:
        win = [r for r in rows if lo <= r["bar"] < hi]
        vp = vhead(win)
        for regime, sub in split_by_regime(win).items():
            rule_imp = statistics.mean(r["fwd"] for r in sub)
            val_sub = [r for r, p in zip(sub, vp) if p >= 0.0]
            val_imp = statistics.mean(r["fwd"] for r in val_sub) if val_sub else 0.0
            router.record(regime, "rule", rule_imp)
            router.record(regime, "value", val_imp)
            picked = router.pick(regime)
            print(f"  {label:16s} {regime:5s} n={len(sub):4d} "
                  f"rule={rule_imp:+.3%} value={val_imp:+.3%} router->{picked}")

    print("\n=== rule-floor-prior rollout (per validated window) ===")
    # simulate: value earns weight only where its impact beats the rule floor
    for reg in ("bull", "bear"):
        r_imp = router.mean_impact(reg, "rule") or 0.0
        v_imp = router.mean_impact(reg, "value") or -1.0
        ok = v_imp > r_imp
        router.step({(reg, "value"): 1 if ok else 0})
        print(f"  {reg:5s}: rule={r_imp:+.3%} value={v_imp:+.3%} -> "
              f"value weight={router.weights.get(reg, {}).get('value', 0.0):.2f} "
              f"({'earned' if ok else 'stays at floor'})")

    print("\n=== MoT router prototype ready ===")
    print("Interface: mot/mot.py (ExpertDecision, Expert, RegimeRouter)")


if __name__ == "__main__":
    main()
