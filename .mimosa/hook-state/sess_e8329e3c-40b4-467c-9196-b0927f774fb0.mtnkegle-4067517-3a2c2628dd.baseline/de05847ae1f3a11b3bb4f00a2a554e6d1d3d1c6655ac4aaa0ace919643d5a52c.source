#!/usr/bin/env python3
"""laggard — momentum leaders + in-bull laggard catch-up (Tournament R1d).

The participation tool. In a confirmed bull (market breadth > thr) it runs TWO
books on top of each other:
  - MOMENTUM book: top-k_mom by `mom_lb`-day momentum, equal weight, exposure
    `mom_expo` of equity, rebalanced every `rebal` bars while bull is ON.
  - LAGGARD book:  the worst-k_con by the shorter `con_lb` lookback (catch-up),
    each sized `con_expo`/k_con, entries only while bull is ON; positions age
    out via `max_hold` only (never force-sold by regime).
When the bull regime is OFF: no entries anywhere; existing positions ride out.

Verified: R1d (intl 2021-26) OOS Calmar 1.666 / Sharpe 1.35 / maxDD -7.5%,
beats the intl basket in the 2023-26 broad bull (+71.8% vs +64.5%) — the
broad-bull participation gap. Best params (FINAL_CFG): breadth_thr=0.7,
rebal=20, mom_lb=60, k_mom=5, mom_expo=0.7, con_lb=10, k_con=1, con_expo=0.4,
max_hold=32.

Honesty: breadth/mom/con signals at prior close, fills at current close,
0.35%/side fees, $500 start. Faithful port of
/tmp/opentrader/swarm/agents/r1d_laggard.py (no lookahead).
"""

from typing import Optional

import numpy as np
import pandas as pd

FEE = 0.0035
BREADTH_WIN = 100
START_EQUITY = 500.0


def run(closes: pd.DataFrame, universe: Optional[list] = None, *,
        breadth_thr: float = 0.7, rebal: int = 20, mom_lb: int = 60,
        k_mom: int = 5, mom_expo: float = 0.7, con_lb: int = 10,
        k_con: int = 1, con_expo: float = 0.4, max_hold: int = 32,
        mom_hold: int = 10000, fee: float = FEE) -> pd.Series:
    """Run laggard over a closes DataFrame (DatetimeIndex rows, cols = symbols).

    Returns equity pd.Series indexed by closes.index.
    """
    if universe is None:
        universe = list(closes.columns)
    names = [s for s in universe if s in closes]
    n = len(closes.index)
    breadth = (closes[names] > closes[names].rolling(BREADTH_WIN).mean()).mean(axis=1)
    start = max(mom_lb + 2, BREADTH_WIN + 1, con_lb + 2)
    cash, pos, equity = START_EQUITY, {}, []

    def eqnow(t):
        return cash + sum(p["qty"] * closes[s].iloc[t] for s, p in pos.items())

    for t in range(start, n):
        # age laggard positions out naturally (never forced by regime)
        for s in list(pos.keys()):
            p = pos[s]
            p["bars"] += 1
            if p["bars"] >= p["maxhold"]:
                ex = closes[s].iloc[t]
                fee_amt = fee * p["qty"] * ex
                cash += p["qty"] * ex - fee_amt
                del pos[s]

        equity.append((closes.index[t], eqnow(t)))
        bull = breadth.iloc[t - 1] > breadth_thr
        if not np.isfinite(breadth.iloc[t - 1]):
            continue

        if t % rebal != 0:
            continue

        if not bull:
            continue

        # ---- MOMENTUM book: rotate to top-k_mom (equal weight, mom_expo) ----
        mom = {s: closes[s].iloc[t - 1] / closes[s].iloc[t - 1 - mom_lb] - 1
               for s in names}
        sel = sorted(mom, key=mom.get, reverse=True)[:k_mom]
        w = mom_expo / len(sel)
        for s in list(pos.keys()):
            if pos[s]["book"] == "mom" and s not in sel:
                ex = closes[s].iloc[t]
                fee_amt = fee * pos[s]["qty"] * ex
                cash += pos[s]["qty"] * ex - fee_amt
                del pos[s]
        eq = eqnow(t)
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
                pos[s] = {"qty": old["qty"] + dq, "book": "mom",
                          "bars": 0, "maxhold": mom_hold}
            elif dq < 0:
                ex = price
                fee_amt = fee * abs(dq) * ex
                cash += abs(dq) * ex - fee_amt
                pos[s]["qty"] = cur + dq
                if pos[s]["qty"] < 1e-9:
                    del pos[s]

        # ---- LAGGARD book: buy worst-k_con by con_lb (catch-up) ----
        con_mom = {s: closes[s].iloc[t - 1] / closes[s].iloc[t - 1 - con_lb] - 1
                   for s in names}
        lag = sorted(con_mom, key=con_mom.get)[:k_con]
        lag = [s for s in lag if pos.get(s, {}).get("book") != "mom"]
        eq = eqnow(t)
        wc = con_expo / len(lag) if lag else 0.0
        for s in lag:
            price = closes[s].iloc[t]
            if not np.isfinite(price) or price <= 0:
                continue
            target_qty = wc * eq / price
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
                pos[s] = {"qty": old["qty"] + dq, "book": "lag",
                          "bars": 0, "maxhold": max_hold}

    return pd.Series([e for _, e in equity], index=[d for d, _ in equity])
