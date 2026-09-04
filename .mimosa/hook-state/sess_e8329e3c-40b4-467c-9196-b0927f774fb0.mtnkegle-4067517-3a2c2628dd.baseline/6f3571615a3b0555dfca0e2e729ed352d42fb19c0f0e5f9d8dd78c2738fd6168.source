#!/usr/bin/env python3
"""momtrend — momentum-top + market-breadth entry gate (Tournament R1+R2).

The regime tool. Long top-K by 60d momentum, rebalance every `rebal` bars;
entries gated by market breadth (fraction of universe above its `breadth_win`
MA > `breadth_thr`) and/or SPY above its long MA. NO forced exits — hold
winners through weak regimes, just stop buying.

Verified: R1 (US 2008-26) ann 23.2% / Calmar 0.469 / 4/4 folds; OOS
(intl 2021-26) ann 11.0% / Calmar 0.852 / Sharpe 1.05 / maxDD -13.0%.
Best params: mom=60, k=5, rebal=20, breadth_thr=0.6, breadth_win=100,
force_exit=False. (Bonus: mom=90,k=8 -> ann 27.5%, Calmar 0.68, maxDD -40%.)

Honesty: signals at prior close, fills at current close, 0.35%/side fees.
"""

from typing import Optional

import numpy as np
import pandas as pd


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        mom_lb: int = 60, k: int = 5, rebal: int = 20,
        spy_ma: int = 0, breadth_thr: float = 0.6, breadth_win: int = 100,
        expo: float = 1.0, force_exit: bool = False,
        top_pct: Optional[float] = None, bad_expo: Optional[float] = None,
        stop_pct: float = 0.0, spy: Optional[pd.Series] = None,
        start_equity: float = 500.0, fee: float = 0.0035) -> pd.Series:
    """Run the momtrend strategy over a closes DataFrame.

    closes: DataFrame, rows indexed by DatetimeIndex (master), cols = symbols.
    universe: subset of closes.columns to trade (default all).
    spy: optional SPY price series aligned to closes.index (for spy_ma gate).
    Returns equity pd.Series indexed by closes.index.
    """
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)
    spy_ma_s = spy.rolling(spy_ma).mean() if spy_ma and spy is not None else None
    if breadth_win:
        breadth = (closes > closes.rolling(breadth_win).mean()).mean(axis=1)
    else:
        breadth = None

    cash, pos, equity = start_equity, {}, []
    start = max(mom_lb + 2, (spy_ma or 1) + 1, (breadth_win or 1) + 1)
    for t in range(start, n):
        for s in pos:
            px = closes[s].iloc[t - 1]
            if px > pos[s]["peak"]:
                pos[s]["peak"] = px

        ok = True
        if spy_ma_s is not None:
            ok = ok and (spy.iloc[t - 1] > spy_ma_s.iloc[t - 1])
        if breadth is not None:
            ok = ok and (breadth.iloc[t - 1] > breadth_thr)

        if stop_pct:
            for s in list(pos.keys()):
                px = closes[s].iloc[t - 1]
                if px <= pos[s]["peak"] * (1 - stop_pct):
                    ex = closes[s].iloc[t]
                    fee_amt = fee * pos[s]["qty"] * ex
                    cash += pos[s]["qty"] * ex - fee_amt
                    del pos[s]

        if force_exit and not ok:
            for s in list(pos.keys()):
                ex = closes[s].iloc[t]
                fee_amt = fee * pos[s]["qty"] * ex
                cash += pos[s]["qty"] * ex - fee_amt
            pos = {}

        eq = cash + sum(p["qty"] * closes[s].iloc[t] for s, p in pos.items())
        equity.append((closes.index[t], eq))

        if t % rebal != 0:
            continue
        if not ok and bad_expo is None:
            continue

        eff_expo = expo if ok else (bad_expo if bad_expo is not None else 0.0)
        mom = {s: closes[s].iloc[t - 1] / closes[s].iloc[t - 1 - mom_lb] - 1
               for s in names}
        if top_pct:
            sel = sorted(mom, key=mom.get, reverse=True)
            kk = max(1, int(top_pct * len(sel)))
            sel = sel[:kk]
        else:
            sel = sorted(mom, key=mom.get, reverse=True)[:k]
        w = eff_expo / len(sel) if len(sel) else 0.0

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
