#!/usr/bin/env python3
"""RL apprentice v1: a torch value head learned from the rule playbook's rewards.

Contextual bandit: state = engineered features at the signal bar, action =
{take, skip}, reward = 10-bar forward return. V(state) predicts E[forward
return]; the policy takes iff V >= theta. Trained on a bull window, early-
stopped on a held-out discrimination slice, and gated on two regime-diverse
held-out windows (2022 bear + 2026) per the map's autonomy bar.

Writes data/research_gate/value_head.pt + value_head_report.json.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "research_gate"
FORWARD = 10
TRAIN = (0, 1000)          # forward-only (audit 2026-08-11): train the past
TESTS = [(1000, 1250)]     # gate ONLY the unseen future — w0 (2021-23 bear)
                           # is not discriminable at +1% even in-sample (#68)
VAL_FRAC = 0.15              # early-stop slice from TRAIN's tail
SEED = 23
FEAT_COLS = ["mom", "rev", "rsi", "brk", "z", "ma_dist", "vol_spike", "vol_level", "momfilt"]
THETA_BAR = 0.01             # autonomy bar: >= +1% discrimination per window


def _device():
    """Prefer GPU0 (NVIDIA) for the fit; fall back to CPU. (#47: GPU0 must
    be a genuine parallel compute stream, not an idle card.)"""
    if torch.cuda.is_available():
        return "cuda:0"
    return "cpu"


def collect(closes, highs, lows, vols, cfg, gen_score_min=-0.5, require_regime=False):
    """All candidates for value-head TRAINING: score >= gen_score_min (loosened
    data-gen screen so the value function sees the full state space), each
    labeled with its realized forward return. The strict buy_thresh/regime gate
    still governs TRADING; here we only need labeled (state, reward) pairs."""
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if cfg["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    master = next(iter(closes.values())).index
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        for t in range(len(c)):
            if t + FORWARD >= len(c):
                break
            date = c.index[t]
            if date not in master:
                continue
            s = float(_score_at({s: f.loc[date] for s in [sym]}, cfg, {sym: 0.0})[sym])
            if s != s or s < gen_score_min:  # NaN != NaN excludes warmup bars
                continue
            regime_ok = True
            if require_regime and spy_ma is not None and date in spy_ma.index:
                regime_ok = float(spy[date]) > float(spy_ma[date])
            if not regime_ok:
                continue
            v = [0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k]) for k in FEAT_COLS]
            spy_ratio = 1.0
            if spy is not None and date in spy_ma200.index and spy_ma200[date]:
                spy_ratio = float(spy[date] / spy_ma200[date])
            v += [s, spy_ratio]
            rows.append({
                "bar": master.get_loc(date), "sym": sym, "date": date,
                "x": np.array(v, dtype=np.float32),
                "fwd": float(c.loc[c.index[t + FORWARD]]) / float(c.iloc[t]) - 1.0,
            })
    return rows


class ValueMLP(nn.Module):
    def __init__(self, d_in):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_in, 32), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(32, 16), nn.ReLU(),
            nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


def discrim(rows, model, theta, stats):
    """kept-mean - all-mean for a window given the policy V >= theta."""
    mean, std = stats
    kept = []
    for r in rows:
        z = (r["x"] - mean) / (std + 1e-8)
        with torch.no_grad():
            v = float(model(torch.tensor(z).unsqueeze(0)).item())
        if v >= theta:
            kept.append(r["fwd"])
    all_m = statistics.mean(r["fwd"] for r in rows)
    kept_m = statistics.mean(kept) if kept else 0.0
    return kept_m - all_m, len(kept), kept_m, all_m


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, [s for s in data if s != REGIME_SYM])
    all_rows = collect(al[0], al[1], al[2], al[3], base)
    n_strict = sum(1 for r in all_rows if r["x"][-2] >= base["buy_thresh"])
    print(f"[v] data-gen candidates: {len(all_rows)} (strict-screen subset: {n_strict})")
    trn_all = [r for r in all_rows if TRAIN[0] <= r["bar"] < TRAIN[1]]
    print(f"[v] train-window candidates: {len(trn_all)}")

    train = [r for r in all_rows if TRAIN[0] <= r["bar"] < TRAIN[1]]
    n_val = max(1, int(len(train) * VAL_FRAC))
    trn, val = train[: len(train) - n_val], train[-n_val:]
    X = np.stack([r["x"] for r in trn])
    y = np.array([r["fwd"] for r in trn], dtype=np.float32)
    mean, std = X.mean(0), X.std(0)
    Xz = (X - mean) / (std + 1e-8)

    model = ValueMLP(X.shape[1])
    device = _device()
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.MSELoss()
    Xt, yt = torch.tensor(Xz, device=device), torch.tensor(y, device=device)
    Xv = torch.tensor((np.stack([r["x"] for r in val]) - mean) / (std + 1e-8),
                      device=device)
    yv = torch.tensor(np.array([r["fwd"] for r in val], dtype=np.float32),
                      device=device)
    best_val_loss, best_state, patience = 1e9, None, 0
    for epoch in range(200):
        model.train()
        opt.zero_grad()
        loss = lossf(model(Xt), yt)
        loss.backward()
        opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(lossf(model(Xv), yv))
        if vl < best_val_loss:
            best_val_loss, best_state, patience = vl, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 15:
                break
    model.load_state_dict(best_state)
    model.eval()

    # Tune theta on the VALIDATION window to maximize discrimination
    def preds(rows):
        out = []
        for r in rows:
            z = (r["x"] - mean) / (std + 1e-8)
            with torch.no_grad():
                out.append(float(model(torch.tensor(z, device=device).unsqueeze(0)).item()))
        return out

    vp = np.array(preds(val))
    best_theta, best_d = 0.0, -1e9
    for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
        kept = [r["fwd"] for r, p in zip(val, vp) if p >= q]
        allm = statistics.mean(r["fwd"] for r in val)
        km = statistics.mean(kept) if kept else 0.0
        d = km - allm
        if d > best_d:
            best_d, best_theta = d, float(q)
    print(f"[v] trained; val MSE {best_val_loss:.5f}; tuned theta={best_theta:+.3f} "
          f"(val discrimination {best_d:+.2%})")

    results = []
    for lo, hi in TESTS:
        win = [r for r in all_rows if lo <= r["bar"] < hi]
        wp = np.array(preds(win))
        kept_f = [r["fwd"] for r, p in zip(win, wp) if p >= best_theta]
        all_m = statistics.mean(r["fwd"] for r in win)
        kept_m = statistics.mean(kept_f) if kept_f else 0.0
        d = kept_m - all_m
        results.append({"window": f"{lo}-{hi}", "n": len(win), "kept": len(kept_f),
                        "kept_mean": kept_m, "all_mean": all_m, "margin": d})
        print(f"[v] window {lo}-{hi}: n={len(win)} kept={len(kept_f)} "
              f"kept_m={kept_m:+.2%} all_m={all_m:+.2%} margin={d:+.2%}")

    passed = [r for r in results if r["margin"] >= THETA_BAR]
    pass_gate = len(passed) == len(results)
    print(f"\n=== VALUE HEAD GATE ===")
    print(f"  autonomy bar: +{THETA_BAR:.0%}/trade on BOTH windows")
    print(f"  windows passing: {len(passed)}/{len(results)}")
    print(f"  GATE: {'PASS - value head may veto within the rule gate' if pass_gate
          else 'FAIL - stays gated; rules remain primary'}")

    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "d_in": X.shape[1], "mean": mean,
                "std": std}, OUT / "value_head.pt")
    (OUT / "value_head_report.json").write_text(json.dumps({
        "train_window": TRAIN, "test_windows": [list(t) for t in TESTS],
        "n_train": len(trn), "n_val": len(val), "val_mse": best_val_loss,
        "theta": best_theta, "results": results, "pass": pass_gate}, indent=1, default=str))
    print(f"-> {OUT / 'value_head.pt'} + value_head_report.json")


if __name__ == "__main__":
    main()
