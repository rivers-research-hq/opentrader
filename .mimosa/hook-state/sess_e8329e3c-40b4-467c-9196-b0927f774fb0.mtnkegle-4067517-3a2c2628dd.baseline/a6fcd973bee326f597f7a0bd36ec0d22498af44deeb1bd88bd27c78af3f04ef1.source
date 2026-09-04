#!/usr/bin/env python3
"""wavelet — causal Haar a-trous trend gate x momentum-top (R1c+R2).

The regime tool. Long top-k by `mom_lb` momentum, rebalance every `rebal`
bars; entries gated by the coarse-scale wavelet trend RISING (undecimated Haar
a-trous, J=4, slope h=1: trend[t-1] > trend[t-2]) on the equal-weight intl
log-price index. gate-entries-only — never force-exit.

Verified: R1c (US 2008-26) Calmar 0.766; OOS (intl 2021-26) Calmar 0.803 /
Sharpe 0.91 / maxDD -11.7%. Best params: mom_lb=90, k=6, rebal=20, wl_levels=4,
wl_slope=1.

Honesty: the a-trous (1/2,1/2) low-pass is one-sided so the transform is
streaming-causal; gate reads trend at t-1, fills at t close, 0.35%/side fees.
Faithful port of /tmp/opentrader/swarm/agents/r2_wavelet_intl.py.
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035


def _atrous_causal(x: np.ndarray, levels: int) -> list:
    """Causal undecimated Haar a-trous (same as r1c_wavelet)."""
    x = np.asarray(x, dtype=float)
    a = [x]
    for j in range(1, levels + 1):
        prev = a[-1]
        hole = 2 ** (j - 1)
        out = prev.copy()
        out[hole:] = 0.5 * (prev[hole:] + prev[:-hole])
        a.append(out)
    return a


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        mom_lb: int = 90, k: int = 6, rebal: int = 20,
        wl_levels: int = 4, wl_slope: int = 1, fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)

    logp = np.log(closes[names].values.astype(float))
    mkt_log = logp.mean(axis=1)
    a = _atrous_causal(mkt_log, wl_levels)
    mkt_tr = a[wl_levels]

    cash, pos, equity = 500.0, {}, []
    start = mom_lb + 2
    for t in range(start, n):
        t1 = t - 1

        ok = (t1 >= wl_slope) and (mkt_tr[t1] > mkt_tr[t1 - wl_slope])

        eq = cash + sum(p["qty"] * closes[s].iloc[t] for s, p in pos.items())
        equity.append((closes.index[t], eq))

        if t % rebal != 0:
            continue
        if not ok:
            continue

        mom = {s: closes[s].iloc[t1] / closes[s].iloc[t1 - mom_lb] - 1
               for s in names}
        sel = sorted(mom, key=mom.get, reverse=True)[:k]
        w = 1.0 / len(sel) if sel else 0.0

        for s in list(pos.keys()):
            if s not in sel:
                ex = closes[s].iloc[t]
                cash += pos[s]["qty"] * ex - fee * pos[s]["qty"] * ex
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
                old = pos.get(s, {"qty": 0})
                pos[s] = {"qty": old["qty"] + dq}
            elif dq < 0:
                fee_amt = fee * abs(dq) * price
                cash += abs(dq) * price - fee_amt
                pos[s]["qty"] = cur + dq
                if pos[s]["qty"] < 1e-9:
                    del pos[s]
    return pd.Series([e for _, e in equity], index=[d for d, _ in equity])
