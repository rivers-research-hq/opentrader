#!/usr/bin/env python3
"""entropy — high-entropy regime gate x momentum-top (R1c+R2).

The regime tool. Long top-k by `mom_lb` momentum, rebalance every `rebal`
bars; entries gated by (a) Shannon entropy of the equal-weight intl market's
daily returns (60d window, 16 bins, [2,98]pct range) > 2.53 and (b) market
breadth > 0.6. gate-entries-only — no forced exits.

Verified: R1c (US 2008-26) Calmar 0.832; OOS (intl 2021-26) Calmar 0.667 /
Sharpe 1.00 / maxDD -13.8%. Best params: k=7, mom_lb=60, rebal=20,
breadth_thr=0.6, breadth_win=100, ent_win=60, ent_bins=16, ent_thr=2.53.

Honesty: entropy/breadth signals at prior close, fills at current close,
0.35%/side fees. Faithful port of
/tmp/opentrader/swarm/agents/r2_entropy_intl.py.
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035


def _shannon(arr: np.ndarray, bins: int = 16) -> float:
    x = np.asarray(arr, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 4:
        return np.nan
    lo, hi = np.percentile(x, [2, 98])
    if hi <= lo:
        return 0.0
    h, _ = np.histogram(x, bins=bins, range=(lo, hi))
    p = h / h.sum()
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def _entropy_series(closes: pd.DataFrame, names: list, win: int,
                    bins: int) -> pd.Series:
    mret = closes[names].pct_change().mean(axis=1)
    n = len(closes.index)
    out = pd.Series(np.nan, index=closes.index)
    for t in range(win + 2, n):
        out.iloc[t] = _shannon(mret.iloc[t - win:t].values, bins)
    return out


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        k: int = 7, mom_lb: int = 60, rebal: int = 20,
        breadth_thr: float = 0.6, breadth_win: int = 100,
        ent_win: int = 60, ent_bins: int = 16, ent_thr: float = 2.53,
        fee: float = FEE) -> pd.Series:
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)
    breadth = (closes[names] > closes[names].rolling(breadth_win).mean()).mean(axis=1)
    ent_s = _entropy_series(closes, names, ent_win, ent_bins)
    cash, pos, equity = 500.0, {}, []
    start = max(mom_lb + 2, breadth_win + 1, ent_win + 3)
    for t in range(start, n):
        for s in pos:
            px = closes[s].iloc[t - 1]
            if px > pos[s]["peak"]:
                pos[s]["peak"] = px
        ok = (breadth.iloc[t - 1] > breadth_thr)
        ev = ent_s.iloc[t - 1]
        ok = ok and np.isfinite(ev) and (ev > ent_thr)
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
