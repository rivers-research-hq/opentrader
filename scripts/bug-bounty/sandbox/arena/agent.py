"""The value head: fit with arena targets, vote, gate.

Builds on the closed map 'Apprentice learns to trade via RL from the rule
playbook': torch MLP V(state) -> E[forward return], early-stop on held-out
discrimination, gate = >= +1% discrimination on both regime windows. The
arena variant accepts per-row targets (war-relabeled r-tilde or the plain
forward return) and reports the discrimination gate.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from setup_search.value_head import THETA_BAR

GATE_MIN_KEPT = 30  # a gate window needs >= this many kept rows to count
# (audit 2026-08-11: the arena gate reported kept counts but did not
# enforce them, so a model keeping a handful of lucky rows could clear
# the bar; matches the breeder MIN_KEPT discipline — #68 protocol)

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"
SEED = 23
TRAIN = (0, 1000)              # forward-only (audit 2026-08-11): train the past
TESTS = [(1000, 1250)]         # gate ONLY the unseen future — w0 (2021-23 bear)
                               # is not discriminable at +1% even in-sample,
                               # so gating it made the bar unreachable (see #68)
VAL_FRAC = 0.15


class ArenaMLP(nn.Module):
    def __init__(self, d_in, hidden=(64, 32)):
        super().__init__()
        layers = []
        prev = d_in
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.ReLU(), nn.Dropout(0.2)]
            prev = h
        layers += [nn.Linear(prev, 1)]
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def _targets_for(rows, targets):
    if not targets:
        return np.array([r["fwd"] for r in rows], dtype=np.float32)
    return np.array(
        [targets.get((r["bar"], r["sym"]), r["fwd"]) for r in rows], dtype=np.float32
    )


def _device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def fit(
    rows,
    targets=None,
    epochs=200,
    lr=1e-3,
    hidden=(64, 32),
    extra_rows=None,
    extra_targets=None,
    seed=SEED,
):
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = _device()
    print(f"[arena] fit on {device}" if device == "cuda" else "", flush=True)
    # ORDER MATTERS: the val slice (last VAL_FRAC of train) is the theta
    # calibration tail and must be the RECENT era. collect() returns rows in
    # symbol-major order; without sorting, the "val tail" is the last
    # symbols' rows across all eras (audit 2026-08-11: theta calibrated on a
    # random era mix, silently destroying gate margins in run_iteration).
    rows = sorted(rows, key=lambda r: r["bar"])
    train_w, test_ws = _adaptive_windows(rows)
    train = [r for r in rows if train_w[0] <= r["bar"] < train_w[1]]
    if len(train) < 8:
        # Not enough data to split train/val: return a degenerate, clearly-failing
        # art instead of crashing on an empty stack. The gate reads pass=False.
        model = ArenaMLP(rows[0]["x"].shape[0] if rows else 11, hidden=hidden)
        report = {
            "train_window": list(train_w),
            "test_windows": [list(t) for t in test_ws],
            "n_train": len(train),
            "n_val": 0,
            "val_mse": float("nan"),
            "theta": 0.0,
            "results": [{"window": f"{lo}-{hi}", "n": 0, "kept": 0, "kept_mean": 0.0,
                         "all_mean": 0.0, "margin": -1.0} for lo, hi in test_ws],
            "pass": False,
            "insufficient_data": True,
        }
        return {"model": model, "theta": 0.0, "mean": np.zeros(model.net[0].in_features),
                "std": np.ones(model.net[0].in_features), "report": report, "pass": False}
    n_val = max(1, int(len(train) * VAL_FRAC))
    trn, val = train[: len(train) - n_val], train[-n_val:]
    if extra_rows:
        trn = extra_rows + trn
    X = np.stack([r["x"] for r in trn])
    base_y = _targets_for(trn, targets)
    if extra_rows and extra_targets:
        extra_by_key = {
            (r["bar"], r["sym"]): t for r, t in zip(extra_rows, extra_targets)
        }
        for i, r in enumerate(trn):
            key = (r["bar"], r["sym"])
            if key in extra_by_key:
                base_y[i] = extra_by_key[key]
    y = base_y.astype(np.float32)
    mean, std = X.mean(0), X.std(0)
    Xz = (X - mean) / (std + 1e-8)

    model = ArenaMLP(X.shape[1], hidden=hidden).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    lossf = torch.nn.MSELoss()
    Xt = torch.tensor(Xz, device=device)
    yt = torch.tensor(y, device=device)
    Xv = torch.tensor(
        (np.stack([r["x"] for r in val]) - mean) / (std + 1e-8), device=device
    )
    yv = torch.tensor(_targets_for(val, targets), device=device)
    best_val_loss, best_state, patience = 1e9, None, 0
    for _ in range(epochs):
        model.train()
        opt.zero_grad()
        loss = lossf(model(Xt), yt)
        loss.backward()
        opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(lossf(model(Xv), yv))
        if vl < best_val_loss:
            best_val_loss, best_state, patience = (
                vl,
                {k: v.clone() for k, v in model.state_dict().items()},
                0,
            )
        else:
            patience += 1
            if patience >= 15:
                break
    model.load_state_dict(best_state)
    model.eval()

    def preds(rows):
        return predict_batch(
            {"model": model, "mean": mean, "std": std}, [r["x"] for r in rows]
        )

    vp = preds(val)
    best_theta, best_d = 0.0, -1e9
    for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
        kept = [r["fwd"] for r, p in zip(val, vp) if p >= q]
        if len(kept) < GATE_MIN_KEPT:
            continue
        allm = statistics.mean(r["fwd"] for r in val)
        km = statistics.mean(kept) if kept else 0.0
        d = km - allm
        if d > best_d:
            best_d, best_theta = d, float(q)

    results = []
    for lo, hi in test_ws:
        win = [r for r in rows if lo <= r["bar"] < hi]
        if not win:
            results.append({"window": f"{lo}-{hi}", "n": 0, "kept": 0, "kept_mean": 0.0,
                            "all_mean": 0.0, "margin": -1.0})
            continue
        wp = preds(win)
        kept_f = [r["fwd"] for r, p in zip(win, wp) if p >= best_theta]
        all_m = statistics.mean(r["fwd"] for r in win)
        kept_m = statistics.mean(kept_f) if kept_f else 0.0
        results.append(
            {
                "window": f"{lo}-{hi}",
                "n": len(win),
                "kept": len(kept_f),
                "kept_mean": kept_m,
                "all_mean": all_m,
                "margin": kept_m - all_m,
            }
        )
    passed = [r for r in results
              if r["margin"] >= THETA_BAR and r["kept"] >= GATE_MIN_KEPT]
    pass_gate = len(passed) == len(results)
    report = {
        "train_window": list(train_w),
        "test_windows": [list(t) for t in test_ws],
        "n_train": len(trn),
        "n_val": len(val),
        "val_mse": best_val_loss,
        "theta": best_theta,
        "results": results,
        "pass": pass_gate,
    }
    return {
        "model": model,
        "theta": best_theta,
        "mean": mean,
        "std": std,
        "report": report,
        "pass": pass_gate,
    }


def save(art, path=None):
    path = path or OUT / "arena_value_head.pt"
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state": art["model"].state_dict(),
            "theta": art["theta"],
            "mean": art["mean"],
            "std": art["std"],
            "report": art["report"],
            "hidden": art.get("hidden", (64, 32)),
        },
        path,
    )
    (OUT / "arena_report.json").write_text(
        json.dumps(art["report"], indent=1, default=str)
    )
    return path


def load(path=None):
    path = path or OUT / "arena_value_head.pt"
    try:
        ck = torch.load(path, map_location="cpu", weights_only=False)
        hidden = tuple(ck.get("hidden", (32, 16)))
        model = ArenaMLP(ck["mean"].shape[0], hidden=hidden)
        model.load_state_dict(ck["state"])
    except Exception:
        return None
    model.eval()
    return {
        "model": model,
        "theta": ck["theta"],
        "mean": ck["mean"],
        "std": ck["std"],
        "report": ck.get("report", {}),
        "hidden": hidden,
    }


def load_report(path=None):
    path = path or OUT / "arena_value_head.pt"
    try:
        ck = torch.load(path, map_location="cpu", weights_only=False)
        return ck.get("report", {})
    except Exception:
        return {}


def predict_batch(art, xs):
    if not xs:
        return np.array([])
    model, mean, std = art["model"], art["mean"], art["std"]
    device = _device()
    model = model.to(device)
    X = np.stack([np.asarray(x, dtype=np.float32) for x in xs])
    Xz = (X - mean) / (std + 1e-8)
    with torch.no_grad():
        v = model(torch.tensor(Xz, device=device)).cpu().numpy()
    return v


def _adaptive_windows(rows):
    """Derive train/test bar windows from the actual data extent so the arena
    runs on any archive length (1y ~250 bars through 5y ~1250), not just the
    hardcoded 5y split. Feature warmup means rows may start well after bar 0
    (e.g. 1y rows span 110-240), so windows are placed inside the real range.
    Forward-only (audit 2026-08-11): train the past, gate the unseen future."""
    bars = [r["bar"] for r in rows]
    if not bars:
        return TRAIN, TESTS
    lo, hi = min(bars), max(bars) + 1
    if hi - lo >= 1000:
        return TRAIN, TESTS
    seg = hi - lo
    c = lo + int(0.8 * seg)
    train = (lo, c)
    tests = [(c, hi)]
    tests = [(x, y) for x, y in tests if y > x]
    if not tests:
        mid = lo + seg // 2
        train, tests = (lo, mid), [(mid, hi)]
    return train, tests


def recompute_gate(art, rows):
    """Recompute the held-out discrimination gate on the CURRENT model weights
    (after a GRPO refinement the margins in art['report'] are stale). Mutates
    art['report']['results'] and art['report']['pass'] in place."""
    theta = art["theta"]
    results = []
    _, test_ws = _adaptive_windows(rows)
    for lo, hi in test_ws:
        win = [r for r in rows if lo <= r["bar"] < hi]
        if not win:
            results.append({"window": f"{lo}-{hi}", "n": 0, "kept": 0, "kept_mean": 0.0,
                            "all_mean": 0.0, "margin": -1.0})
            continue
        wp = predict_batch(art, [r["x"] for r in win])
        kept_f = [r["fwd"] for r, p in zip(win, wp) if p >= theta]
        all_m = statistics.mean(r["fwd"] for r in win)
        kept_m = statistics.mean(kept_f) if kept_f else 0.0
        results.append(
            {
                "window": f"{lo}-{hi}",
                "n": len(win),
                "kept": len(kept_f),
                "kept_mean": kept_m,
                "all_mean": all_m,
                "margin": kept_m - all_m,
            }
        )
    passed = [r for r in results
              if r["margin"] >= THETA_BAR and r["kept"] >= GATE_MIN_KEPT]
    art["report"]["results"] = results
    art["report"]["pass"] = len(passed) == len(results)
    return art


def make_agent(art):
    model, theta, mean, std = art["model"], art["theta"], art["mean"], art["std"]
    device = _device()
    model = model.to(device)

    def agent_fn(state):
        z = (state["x"] - mean) / (std + 1e-8)
        with torch.no_grad():
            v = float(model(torch.tensor(z, device=device).unsqueeze(0)).item())
        return (1 if v >= theta else 0), v

    return agent_fn
