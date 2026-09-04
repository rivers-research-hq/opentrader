#!/usr/bin/env python3
"""hurst — R/S Hurst persistence gate x momentum-top (R1c+R2).

The regime tool. Long top-7 by `mom_lb` momentum, rebalance every `rebal`
bars; entries gated by (a) R/S Hurst exponent > 0.54 on the equal-weight
market-index log-returns (causal window win=250, as of t-1) and (b) market
breadth > 0.6. gate-entries-only — positions ride until a rebalance drops them.

Verified: R1c (US 2008-26) Calmar 0.884; OOS (intl 2021-26) Calmar 0.967 /
Sharpe 1.18 / maxDD -11.3%. Best params: k=7, mom=120, rebal=20,
breadth_thr=0.6, breadth_win=100, hurst_win=250, hurst_thr=0.54.

Honesty: signals at prior close, fills at current close, 0.35%/side fees.
Faithful port of /tmp/opentrader/swarm/agents/r2_hurst_intl.py.
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035


def _hurst_rs(x: np.ndarray) -> float:
    """R/S Hurst exponent (no package), verbatim from the R1c implementation."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 64:
        return 0.5
    max_n = n // 2
    lags = np.unique(np.rint(np.geomspace(8, max_n, 10)).astype(int))
    lags = lags[(lags >= 8) & (lags <= max_n)]
    logl, logrs = [], []
    for lag in lags:
        chunks = n // lag
        if chunks < 3:
            continue
        xc = x[: chunks * lag].reshape(chunks, lag)
        m = xc.mean(axis=1, keepdims=True)
        cum = np.cumsum(xc - m, axis=1)
        r = cum.max(axis=1) - cum.min(axis=1)
        s = np.maximum(xc.std(axis=1), 1e-12)
        logl.append(np.log(float(lag)))
        logrs.append(np.log(float(np.mean(r / s))))
    if len(logrs) < 3:
        return 0.5
    return float(np.polyfit(logl, logrs, 1)[0])


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        k: int = 7, mom_lb: int = 120, rebal: int = 20,
        breadth_thr: float = 0.6, breadth_win: int = 100,
        hurst_win: int = 250, hurst_thr: float = 0.54,
        fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    cols = [s for s in names]
    col = {s: j for j, s in enumerate(cols)}
    idx = closes.index
    arr = closes[cols].values.astype(float)
    n = len(arr)

    mkt = arr.mean(axis=1)
    lr = np.log(mkt)
    lr = np.concatenate([[np.nan], np.diff(lr)])

    H = np.full(n, 0.5)
    for t in range(hurst_win + 1, n):
        H[t] = _hurst_rs(lr[t - hurst_win:t])

    mean100 = pd.DataFrame(arr, index=idx).rolling(breadth_win).mean().values
    breadth = (arr > mean100).mean(axis=1)

    cash, pos, equity = 500.0, {}, []
    start = max(mom_lb + 2, breadth_win + 1)
    for t in range(start, n):
        eq = cash + sum(p["qty"] * arr[t, col[s]] for s, p in pos.items())
        equity.append((idx[t], eq))

        if t % rebal != 0:
            continue

        h = H[t]
        if not np.isfinite(h) or h <= hurst_thr:
            continue
        if breadth[t - 1] <= breadth_thr:
            continue

        prev = arr[t - 1]
        prev_lb = arr[t - 1 - mom_lb]
        mom = {s: prev[col[s]] / prev_lb[col[s]] - 1 for s in cols}
        sel = sorted(mom, key=mom.get, reverse=True)[:k]
        sel_set = set(sel)
        w = 1.0 / len(sel)
        for s in list(pos.keys()):
            if s not in sel_set:
                j = col[s]
                ex = arr[t, j]
                fee_amt = fee * pos[s]["qty"] * ex
                cash += pos[s]["qty"] * ex - fee_amt
                del pos[s]
        eq = cash + sum(p["qty"] * arr[t, col[s]] for s, p in pos.items())
        for s in sel:
            price = arr[t, col[s]]
            if not np.isfinite(price) or price <= 0:
                continue
            target_qty = w * eq / price
            cur = pos[s]["qty"] if s in pos else 0.0
            dq = target_qty - cur
            if dq > 0:
                cost = dq * price
                fee_amt = fee * cost
                if cost + fee_amt > cash:
                    dq = max(0.0, (cash - fee_amt) / price)
                if dq * price <= 5:
                    continue
                cash -= dq * price + fee * dq * price
                old = pos.get(s, {"qty": 0})
                pos[s] = {"qty": old["qty"] + dq}
            elif dq < 0:
                fee_amt = fee * abs(dq) * price
                cash += abs(dq) * price - fee_amt
                pos[s]["qty"] = cur + dq
                if pos[s]["qty"] < 1e-9:
                    del pos[s]
    return pd.Series([e for _, e in equity], index=[d for d, _ in equity])
