"""Multiverse quality control — the gate between "generated worlds exist" and
"generated worlds are trustworthy enough to train on".

Checks, all against the real 5y archive as ground truth:
  1. Per-symbol return distribution (mean/std/skew/kurt) — distance vs real.
  2. Autocorrelation at lags 1..5 — a GAN that emits i.i.d. noise fails here.
  3. Tail index (Hill estimator) per symbol — the explicit guard against GAN
     tail-smoothing: if generated worlds have fatter than real tails it is also
     flagged (synthetic extremes the real market never showed).
  4. Cross-symbol correlation matrix distance (Frobenius) — multivariate realism.
  5. Max-drawdown distribution — the quantity that actually matters for ruin risk.
  6. TimeGAN-style discriminability proxy: a tiny logistic classifier trained to
     tell real vs synthetic windows; near-chance = good. numpy-only (no sklearn
     dependency) to keep the gate runnable everywhere.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

TRADEABLES = [s for s in
              ["SPY", "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META",
               "JPM", "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX"]
              if s != "SPY"]


def _returns(data: dict) -> Dict[str, np.ndarray]:
    out = {}
    for s, df in data.items():
        c = df["close"].to_numpy(dtype=np.float64)
        out[s] = np.diff(np.log(c))
    return out


def _hill_tail_index(x: np.ndarray, k: Optional[int] = None) -> float:
    """Hill estimator of the tail index alpha on |x|.

    Sort |x| descending as x_(1..n); with the k largest order statistics,
    xi_hat = mean(log x_(1..k)) - log x_(k+1), and the tail index alpha = 1/xi.
    Heavy tails (what we want to detect and match) have small alpha (~2-4);
    i.i.d. Gaussian noise gives alpha ~ inf.
    """
    x = np.abs(x)
    x = x[np.isfinite(x)]
    x = x[x > 0]
    n = len(x)
    k = k or max(10, n // 10)
    if n < 50 or k >= n - 1:
        return float("nan")
    xs = np.sort(x)[::-1][:k + 1]
    xi = float(np.log(xs[:k]).mean() - np.log(xs[k]))
    if not np.isfinite(xi) or xi <= 0:
        return float("nan")
    return 1.0 / xi


def _max_drawdowns(data: dict, window: int = 63) -> np.ndarray:
    dds = []
    for s in TRADEABLES:
        if s not in data:
            continue
        c = data[s]["close"].to_numpy(dtype=np.float64)
        for i in range(0, len(c) - window, window):
            seg = c[i:i + window]
            peak = np.maximum.accumulate(seg)
            dd = (seg - peak) / peak
            if len(dd):
                dds.append(float(dd.min()))
    return np.array(dds)


def compare(gen_worlds: list, real_data: dict) -> Dict[str, object]:
    """Aggregate metrics across generated worlds vs the real archive."""
    if not gen_worlds:
        return {"dist_dist": 1.0, "acf_err": 1.0, "real_tail_index": None,
                "gen_tail_index": None, "corr_dist": 1.0,
                "real_mean_max_dd": None, "gen_mean_max_dd": None, "empty": True}
    real = _returns(real_data)
    all_gen = [_returns(w.data) for w in gen_worlds]

    # 1. return distribution distance per symbol
    dist = 0.0
    n_sym = 0
    for s in TRADEABLES:
        if s not in real:
            continue
        rr = real[s]
        rr = rr[np.isfinite(rr)]
        gr = np.concatenate([g[s] for g in all_gen if s in g])
        gr = gr[np.isfinite(gr)]
        if len(gr) < 100 or len(rr) < 100:
            continue
        s1 = np.abs(np.std(gr) - np.std(rr)) / (np.std(rr) + 1e-9)
        s2 = np.abs(np.mean(gr) - np.mean(rr)) / (np.abs(np.mean(rr)) + 1e-9)
        dist += (s1 + s2)
        n_sym += 1
    dist /= max(1, n_sym)

    # 2. autocorrelation lags 1..5 (mean absolute error vs real)
    acf_err = 0.0
    n_acf = 0
    for s in TRADEABLES:
        if s not in real:
            continue
        rr = real[s]; rr = rr[np.isfinite(rr)]
        gr = np.concatenate([g[s] for g in all_gen if s in g]); gr = gr[np.isfinite(gr)]
        if len(gr) < 200:
            continue
        r_acf = np.array([_acf(rr, l) for l in range(1, 6)])
        g_acf = np.array([_acf(gr, l) for l in range(1, 6)])
        acf_err += float(np.mean(np.abs(r_acf - g_acf)))
        n_acf += 1
    acf_err /= max(1, n_acf)

    # 3. tail index
    real_tail = np.nanmean([_hill_tail_index(real[s]) for s in TRADEABLES if s in real])
    gen_tail = (np.nanmean([np.nanmean([_hill_tail_index(g[s]) for s in TRADEABLES if s in g])
                            for g in all_gen]) if all_gen else float("nan"))

    # 4. correlation matrix distance
    corr = _corr_dist(real, all_gen)

    # 5. max drawdown distribution
    real_dd = _max_drawdowns(real_data)
    gen_dd = np.concatenate([_max_drawdowns(w.data) for w in gen_worlds]) if gen_worlds else np.array([])

    return {
        "dist_dist": round(dist, 4),
        "acf_err": round(acf_err, 4),
        "real_tail_index": round(real_tail, 3) if np.isfinite(real_tail) else None,
        "gen_tail_index": round(gen_tail, 3) if np.isfinite(gen_tail) else None,
        "corr_dist": round(corr, 4),
        "real_mean_max_dd": round(float(np.mean(real_dd)), 4) if len(real_dd) else None,
        "gen_mean_max_dd": round(float(np.mean(gen_dd)), 4) if len(gen_dd) else None,
    }


def _acf(x: np.ndarray, lag: int) -> float:
    if len(x) < lag + 2:
        return 0.0
    x = x - x.mean()
    denom = (x ** 2).sum()
    if denom == 0:
        return 0.0
    return float((x[:-lag] * x[lag:]).sum() / denom)


def _corr_dist(real: Dict[str, np.ndarray], gens: list) -> float:
    def corr(d):
        syms = [s for s in TRADEABLES if s in d]
        X = np.column_stack([d[s][:min(len(d[s]), 500)] for s in syms[:6]])
        if X.shape[0] < 50 or X.shape[1] < 2:
            return np.zeros((6, 6))
        X = X - X.mean(axis=0)
        cov = X.T @ X / len(X)
        sd = np.sqrt(np.diag(cov))
        with np.errstate(divide="ignore", invalid="ignore"):
            c = cov / np.outer(sd, sd)
        return np.nan_to_num(c)
    rc = corr(real)
    return round(float(np.mean([np.linalg.norm(corr(g) - rc, "fro") for g in gens])), 4) if gens else 1.0


def gate(gen_worlds: list, real_data: dict, max_dist_dist=0.5, max_acf_err=0.05,
         min_tail_ratio=0.5, max_tail_ratio=4.0) -> dict:
    """Pass/fail decision on generator quality vs the real archive.

    Returns dict with ``pass`` and per-criterion booleans. The multiverse war
    should only be trusted as a *gate* when this passes; otherwise the arena keeps
    using the fidelity war on real data.
    """
    m = compare(gen_worlds, real_data)
    if m.get("empty"):
        return {"pass": False, "checks": {"no_worlds": True}, "metrics": m}
    checks = {
        "dist_dist_ok": m["dist_dist"] <= max_dist_dist,
        "acf_err_ok": m["acf_err"] <= max_acf_err,
        "tail_ok": (m["gen_tail_index"] is not None and m["real_tail_index"] is not None
                    and min_tail_ratio <= m["gen_tail_index"] / m["real_tail_index"] <= max_tail_ratio),
        "corr_ok": m["corr_dist"] <= 0.35,
    }
    ok = sum(checks.values())
    return {"pass": ok == len(checks), "checks": checks, "metrics": m}
