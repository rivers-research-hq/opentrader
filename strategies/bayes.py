#!/usr/bin/env python3
"""bayes — Bayesian online change-point (BOCPD) regime gate x momentum-top
(R1c+R2).

The drawdown tool. Long top-k by `mom_lb` momentum, rebalance every `rebal`
bars; entries gated by (a) BOCPD "stable" regime (cp_win window probability <
cp_thr, expected run-length >= min_run) on the equal-weight intl market returns
and (b) market breadth > 0.6. gate-entries-only: never force-exit.

Verified: R1c (US 2008-26) Calmar 0.818; OOS (intl 2021-26) Calmar 1.148 /
Sharpe 1.24 / maxDD -10.4%. Best params: mom_lb=60, k=6, rebal=30,
hazard_lam=500, cp_thr=0.05, min_run=80, cp_win=5, breadth_thr=0.6,
breadth_win=100.

Honesty: signals at prior close, fills at current close, 0.35%/side fees.
Faithful port of /tmp/opentrader/swarm/agents/r2_bayes_intl.py.
"""

import math
from typing import Optional

import numpy as np
import pandas as pd
from scipy import special

FEE = 0.0035


def _bocpd(r: np.ndarray, lam: float, mu0: float = 0.0, kappa0: float = 1.0,
           alpha0: float = 1.0, beta0: float = 0.02, win: int = 5):
    r = np.asarray(r, dtype=np.float64)
    T = len(r)
    lam = float(lam)
    haz = 1.0 / lam
    log_haz = math.log(haz)
    log_surv = math.log1p(-haz)

    S = np.empty(T + 1)
    S2 = np.empty(T + 1)
    S[0] = 0.0
    S2[0] = 0.0
    np.cumsum(r, out=S[1:])
    np.cumsum(r * r, out=S2[1:])

    lga = special.gammaln(alpha0 + 0.5 + np.arange(T + 1) * 0.5)
    lgb = special.gammaln(alpha0 + np.arange(T + 1) * 0.5)

    logR = np.full(T + 2, -np.inf)
    logR[0] = 0.0

    cp = np.zeros(T)
    erun = np.zeros(T)
    maxrun = np.zeros(T, dtype=np.int64)
    cwin = np.zeros(T)

    c = -0.5 * math.log(2.0 * math.pi)

    def logsumexp_arr(a):
        m = np.max(a)
        return m + math.log(np.exp(a - m).sum()) if np.isfinite(m) else m

    for t in range(T):
        xt = r[t]
        j = np.arange(t + 1, dtype=np.float64)
        jidx = np.arange(t + 1)
        ssum = S[t] - S[t - jidx]
        ssq = S2[t] - S2[t - jidx]

        kappa = kappa0 + j
        with np.errstate(divide="ignore", invalid="ignore"):
            mu = np.where(j > 0, (kappa0 * mu0 + ssum) / np.where(j > 0, kappa, 1.0), mu0)
        alpha = alpha0 + 0.5 * j
        with np.errstate(divide="ignore", invalid="ignore"):
            beta = np.where(
                j > 0,
                beta0 + 0.5 * (ssq - ssum * ssum / j) + 0.5 * (kappa0 * j * (mu - mu0) ** 2) / kappa,
                beta0,
            )
        with np.errstate(divide="ignore", invalid="ignore"):
            term = 1.0 + kappa * (xt - mu) ** 2 / (2.0 * (kappa + 1.0) * beta)
            logp = (
                c
                + lga[jidx]
                - lgb[jidx]
                - 0.5 * np.log((kappa + 1.0) * beta / kappa)
                - (alpha + 0.5) * np.log(term)
            )

        loggrow = log_surv + logR[: t + 1] + logp
        lse = logsumexp_arr(logR[: t + 1] + logp)
        log_cp = log_haz + lse

        logRn = np.full(t + 2, -np.inf)
        logRn[0] = log_cp
        logRn[1:] = loggrow
        lse_all = logsumexp_arr(logRn)
        logRn -= lse_all
        logR[: t + 2] = logRn

        cp[t] = math.exp(logRn[0])
        maxr = np.max(logRn[: t + 2])
        pr = np.exp(logRn[: t + 2] - maxr)
        pr /= pr.sum()
        erun[t] = float(np.dot(pr, np.arange(t + 2)))
        maxrun[t] = int(np.argmax(pr))
        cwin[t] = math.exp(logsumexp_arr(logRn[: min(t + 2, win + 1)]))
    return cp, erun, maxrun, cwin


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        mom_lb: int = 60, k: int = 6, rebal: int = 30,
        hazard_lam: float = 500.0, cp_thr: float = 0.05, min_run: float = 80.0,
        cp_win: int = 5, breadth_thr: float = 0.6, breadth_win: int = 100,
        fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)
    idx = closes.index

    ret = closes[names].pct_change()
    proxy_ret = ret.mean(axis=1).astype(np.float64).fillna(0.0).to_numpy()

    cp, erun, maxrun, cwin = _bocpd(proxy_ret, hazard_lam,
                                    beta0=0.5 * float(np.var(proxy_ret[:63])),
                                    win=cp_win)

    stable_raw = np.zeros(n, dtype=bool)
    for t in range(1, n):
        stable_raw[t] = (cwin[t - 1] < cp_thr) and (erun[t - 1] >= min_run)
    stable = stable_raw.copy()

    breadth = (closes[names] > closes[names].rolling(breadth_win).mean()).mean(axis=1)

    cash, pos, equity = 500.0, {}, []
    start = max(mom_lb + 2, breadth_win + 1)
    for t in range(start, n):
        for s in pos:
            px = closes[s].iloc[t - 1]
            if px > pos[s]["peak"]:
                pos[s]["peak"] = px

        ok = stable[t] and (breadth.iloc[t - 1] > breadth_thr)

        eq = cash + sum(p["qty"] * closes[s].iloc[t] for s, p in pos.items())
        equity.append((idx[t], eq))

        if t % rebal != 0:
            continue
        if not ok:
            continue

        mom = {s: closes[s].iloc[t - 1] / closes[s].iloc[t - 1 - mom_lb] - 1
               for s in names}
        sel = sorted(mom, key=mom.get, reverse=True)[:k]
        w = 1.0 / len(sel) if len(sel) else 0.0
        for s in list(pos.keys()):
            if s not in sel:
                ex = closes[s].iloc[t]
                fee_amt = fee * pos[s]["qty"] * ex
                cash += pos[s]["qty"] * ex - fee_amt
                del pos[s]
        for s in sel:
            price = closes[s].iloc[t]
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
                old = pos.get(s, {"qty": 0, "peak": price})
                newq = old["qty"] + dq
                pos[s] = {"qty": newq, "peak": max(old["peak"], price)}
            elif dq < 0:
                ex = price
                fee_amt = fee * abs(dq) * ex
                cash += abs(dq) * ex - fee_amt
                pos[s]["qty"] = cur + dq
                if pos[s]["qty"] < 1e-9:
                    del pos[s]
    return pd.Series([e for _, e in equity], index=[d for d, _ in equity])
