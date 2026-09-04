#!/usr/bin/env python3
"""valuehead — the MoT value-head pilot scorer (RLHF spec §5, SFT-on-outcomes stage).

A deliberately small, inspectable model: L2-regularized logistic regression
on hand-named features, trained by full-batch gradient descent in numpy.
At pilot data volumes (~10^2 rows) this is the statistically honest choice —
a neural value head would be a noise amplifier. Artifacts are JSON:
feature names, weights, standardization params, train window, metrics.
Nothing here self-promotes; it enters the world only as an agent_gym policy
(protocol §6) or via the epoch registry with human signoff.
"""

import json
import math


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def train(X, y, feature_names, l2=1.0, iters=600, lr=0.3):
    """X: list of feature dicts (None -> 0.0). Identical math in both paths;
    numpy vectorized when available (needed at deep-history n), pure-python
    fallback otherwise. Returns a model dict with standardization baked in."""
    names = list(feature_names)
    rows = [[(r.get(n) if r.get(n) is not None else 0.0) for n in names] for r in X]
    mu = [sum(col) / len(col) for col in zip(*rows)]
    sd = [max(1e-9, (sum((v - m) ** 2 for v in col) / len(col)) ** 0.5)
          for col, m in zip(zip(*rows), mu)]
    try:
        import numpy as np
        A = np.asarray(rows, dtype=float)
        mu_v, sd_v = A.mean(axis=0), np.maximum(1e-9, A.std(axis=0))
        mu, sd = mu_v.tolist(), sd_v.tolist()
        Z = (A - mu_v) / sd_v
        w = np.zeros(len(names))
        b = 0.0
        yy = np.asarray(y, dtype=float)
        for _ in range(iters):
            p = 1.0 / (1.0 + np.exp(-(Z @ w + b)))
            g = p - yy
            w = w - lr * (Z.T @ g / len(y) + l2 * w / len(y))
            b -= lr * g.mean()
        return {"feature_names": names, "w": [float(x) for x in w], "b": float(b),
                "mu": mu, "sd": sd, "l2": l2, "iters": iters, "n": len(y)}
    except ImportError:
        Z = [[(v - m) / s for v, m, s in zip(row, mu, sd)] for row in rows]
        w = [0.0] * len(names)
        b = 0.0
        n = len(y)
        for _ in range(iters):
            gw = [0.0] * len(names)
            gb = 0.0
            for row, yi in zip(Z, y):
                p = _sigmoid(b + sum(wi * xi for wi, xi in zip(w, row)))
                g = p - yi
                gb += g
                for k in range(len(w)):
                    gw[k] += g * row[k]
            w = [wi - lr * (gwk / n + l2 * wi / n) for wi, gwk in zip(w, gw)]
            b -= lr * gb / n
        return {"feature_names": names, "w": w, "b": b, "mu": mu, "sd": sd,
                "l2": l2, "iters": iters, "n": n}


def predict(model, feats):
    z = model["b"] + sum(
        wi * (((feats.get(n) if feats.get(n) is not None else 0.0) - m) / s)
        for wi, n, m, s in zip(model["w"], model["feature_names"], model["mu"], model["sd"]))
    return _sigmoid(z)


def auc(model, X, y):
    """Rank AUC (Mann-Whitney). Returns None if a class is absent."""
    pos = [predict(model, r) for r, yi in zip(X, y) if yi == 1]
    neg = [predict(model, r) for r, yi in zip(X, y) if yi == 0]
    if not pos or not neg:
        return None
    wins = ties = 0
    for p in pos:
        for q in neg:
            wins += p > q
            ties += p == q
    return round((wins + 0.5 * ties) / (len(pos) * len(neg)), 3)


def save(model, path, meta=None):
    path.write_text(json.dumps({**model, "meta": meta or {}}, indent=2, default=str))
