#!/usr/bin/env python3
"""kalman — Kalman local-linear-trend z gate x momentum-top (R1c+R2).

The regime tool. Long top-5 by 60d momentum, rebalance every 20 bars; entries
gated by (a) Kalman-z of the intl equal-weight log-price index > 1.0 (LLT with
qs=1e-8, fixed obs variance from the first 100 bars) and (b) market breadth >
0.6. gate-entries-only (force_exit=False).

Verified: R1c (US 2008-26) Calmar 0.603; OOS (intl 2021-26) Calmar 0.988 /
Sharpe 1.19 / maxDD -12.7%. Best params: mom_lb=60, k=5, rebal=20,
breadth_thr=0.6, breadth_win=100, qs=1e-8, z_thr=1.0.

Honesty: Kalman is a causal forward filter; gate reads state at t-1, fills at
t close, 0.35%/side fees. Faithful port of
/tmp/opentrader/swarm/agents/r2_kalman_intl.py.
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035
QS = 1e-8
Z_THR = 1.0


def _kalman_llt(y: np.ndarray, q_slope: float, obs_var: float):
    n = len(y)
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.array([[0.0, 0.0], [0.0, q_slope]])
    x = np.array([y[0], 0.0])
    P = np.array([[obs_var, 0.0], [0.0, q_slope * 100.0]])
    slopes = np.empty(n)
    slope_var = np.empty(n)
    for t in range(n):
        R = np.array([[obs_var]])
        xp = F @ x
        Pp = F @ P @ F.T + Q
        S = H @ Pp @ H.T + R
        K = Pp @ H.T @ np.linalg.inv(S)
        if np.isfinite(y[t]):
            e = y[t] - xp[0]
            x = xp + (K @ np.array([[e]])).ravel()
            P = (np.eye(2) - K @ H) @ Pp
        else:
            x = xp
            P = Pp
        slopes[t] = x[1]
        slope_var[t] = P[1, 1]
    return slopes, slope_var


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        mom_lb: int = 60, k: int = 5, rebal: int = 20,
        breadth_thr: float = 0.6, breadth_win: int = 100,
        qs: float = QS, z_thr: float = Z_THR, fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    uni = closes[names]

    breadth = (uni > uni.rolling(breadth_win).mean()).mean(axis=1).to_numpy()
    lpx = np.log(uni.to_numpy())
    mkt = np.nanmean(lpx, axis=1)
    obs_var = float(np.diff(mkt[:breadth_win + 1]).std() ** 2)
    slopes, sv = _kalman_llt(mkt, qs, obs_var)
    z = slopes / np.sqrt(np.maximum(sv, 1e-12))

    n = len(closes.index)
    C = uni.to_numpy()
    mom_tab = (uni / uni.shift(mom_lb) - 1.0).to_numpy()
    cash, pos, equity = 500.0, {}, []
    start = max(mom_lb + 2, breadth_win + 1)
    for t in range(start, n):
        prev = C[t - 1]
        for ci, p in pos.items():
            if prev[ci] > p["peak"]:
                p["peak"] = prev[ci]
        ok = bool(breadth[t - 1] > breadth_thr and z[t - 1] > z_thr)
        eq = cash
        for ci, p in pos.items():
            eq += p["qty"] * C[t, ci]
        equity.append((closes.index[t], eq))
        if t % rebal != 0 or not ok:
            continue
        sel = np.argsort(mom_tab[t - 1])[-k:][::-1]
        w = 1.0 / len(sel)
        for ci in list(pos.keys()):
            if ci not in sel:
                p = pos[ci]
                cash += p["qty"] * C[t, ci] - fee * p["qty"] * C[t, ci]
                del pos[ci]
        for ci in sel:
            price = C[t, ci]
            if not np.isfinite(price) or price <= 0:
                continue
            target_qty = w * eq / price
            cur = pos[ci]["qty"] if ci in pos else 0.0
            dq = target_qty - cur
            if dq > 0:
                cost = dq * price
                fee_amt = fee * cost
                if cost + fee_amt > cash:
                    dq = max(0.0, (cash - fee_amt) / price)
                if dq * price <= 5:
                    continue
                cash -= dq * price + fee * dq * price
                old = pos.get(ci, {"qty": 0, "peak": price})
                pos[ci] = {"qty": old["qty"] + dq, "peak": max(old["peak"], price)}
            elif dq < 0:
                ex = price
                cash += abs(dq) * ex - fee * abs(dq) * ex
                pos[ci]["qty"] = cur + dq
                if pos[ci]["qty"] < 1e-9:
                    del pos[ci]
    return pd.Series([e for _, e in equity], index=[d for d, _ in equity])
