#!/usr/bin/env python3
"""spectral — FFT low-frequency-share regime gate x momentum-top (R1c+R2).

The drawdown tool. Long top-K by `mom_lb` momentum, rebalance every `rebal`
bars; entries gated by (a) the spectral low-frequency power share of the
equal-weight market log-returns (causal FFT window ending t-1, win=336,
min_period=60, threshold 0.025) and (b) market breadth > 0.6. gate-entries-only:
hold through bad regimes, no forced exits.

Verified: R1c (US 2008-26) Calmar 1.071; OOS (intl 2021-26) Calmar 1.000 /
Sharpe 1.29 / maxDD -13.3%. Best params: mom_lb=60, k=7, rebal=20, win=336,
min_period=60, thr=0.025, breadth_thr=0.6, breadth_win=100.

Honesty: signals at prior close, fills at current close, 0.35%/side fees.
Faithful port of /tmp/opentrader/swarm/agents/r2_spectral_intl.py.
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035


def _spectral_feat(closes: pd.DataFrame, names: list, win: int,
                   min_period: int) -> pd.Series:
    """Causal rolling spectral feature (low-freq power share) on the
    equal-weight intl basket log-returns. Window ends at t-1."""
    lr = np.log(closes[names]).diff()
    r = lr.mean(axis=1).values
    n = len(r)
    out = np.full(n, np.nan)
    freqs = np.fft.rfftfreq(win)
    lo = (freqs >= 1e-6) & (freqs <= 1.0 / min_period)
    hi = freqs > 1.0 / min_period
    for t in range(win, n):
        w = r[t - win:t]
        w = w - w.mean()
        spec = np.abs(np.fft.rfft(w)) ** 2
        low_p = spec[lo].sum()
        tot = spec[hi].sum() + low_p
        out[t] = low_p / tot if tot > 0 else np.nan
    return pd.Series(out, index=closes.index)


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        mom_lb: int = 60, k: int = 7, rebal: int = 20, win: int = 336,
        min_period: int = 60, thr: float = 0.025, breadth_thr: float = 0.6,
        breadth_win: int = 100, fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)
    feat = _spectral_feat(closes, names, win, min_period)
    breadth = (closes[names] > closes[names].rolling(breadth_win).mean()).mean(axis=1)

    cash, pos, equity = 500.0, {}, []
    start = max(mom_lb + 2, breadth_win + 1, win + 1)
    for t in range(start, n):
        for s in pos:
            px = closes[s].iloc[t - 1]
            if px > pos[s]["peak"]:
                pos[s]["peak"] = px

        f0 = feat.iloc[t - 1]
        ok = (f0 >= thr) if np.isfinite(f0) else False
        ok = ok and (breadth.iloc[t - 1] > breadth_thr)

        eq = cash + sum(p["qty"] * closes[s].iloc[t] for s, p in pos.items())
        equity.append((closes.index[t], eq))

        if t % rebal != 0:
            continue
        if not ok:
            continue

        mom = {s: closes[s].iloc[t - 1] / closes[s].iloc[t - 1 - mom_lb] - 1
               for s in names}
        sel = sorted(mom, key=mom.get, reverse=True)[:k]
        w = 1.0 / len(sel)
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
