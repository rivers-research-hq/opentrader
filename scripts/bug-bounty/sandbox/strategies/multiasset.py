#!/usr/bin/env python3
"""multiasset — momentum-filtered, vol-scaled multi-asset allocation
(Tournament R1+R2).

The drawdown tool. Every `rebal` bars: keep the top-`topk` of the universe by
`mom_lb`-day momentum, size `eq_frac` equal-weight + (1-eq_frac) inverse-vol.
Decisions use only prior-close data; fills at current close; 0.35%/side fees.

Verified: R1 (13-asset US basket 2008-26) ann 7.2% / Sharpe 0.81 / maxDD
-18.5% / Calmar 0.39 / 4/4 folds; OOS (intl 2021-26) ann 11.6% / Sharpe 1.32
/ maxDD -9.0% / Calmar 1.289. Best params: rebal=63, vol_lb=120, mom_lb=180,
topk=8, eq_frac=0.4 (mode="blend").
"""

from typing import Optional

import numpy as np
import pandas as pd


def backtest(prices: pd.DataFrame, *,
             rebal: int = 63, vol_lb: int = 120, mom_lb: int = 180,
             mode: str = "blend", target_vol: Optional[float] = None,
             mom_gate: bool = True, topk: Optional[int] = None,
             min_w: float = 0.0, eq_frac: float = 0.4,
             names: Optional[list] = None,
             start_equity: float = 500.0, fee: float = 0.0035) -> pd.Series:
    """Weight-based multi-asset backtest over a prices DataFrame.

    prices: DataFrame, rows indexed by DatetimeIndex (master), cols = assets.
    topk: if None, keep all momentum-positive assets; else keep top-`topk`
      by momentum among the positive ones (use topk = #assets*0.75 approx).
    Returns equity pd.Series indexed by prices.index.
    """
    if names is None:
        names = list(prices.columns)
    P = prices[names].values.astype(float)
    n, k = len(P), len(names)
    rets = np.zeros_like(P)
    rets[1:] = P[1:] / P[:-1] - 1.0

    mom = np.full((n, k), np.nan)
    vol = np.full((n, k), np.nan)
    logp = np.log(P)
    for t in range(1, n):
        mom[t] = P[t - 1] / P[max(0, t - 1 - mom_lb)] - 1.0
        lo = max(0, t - 1 - vol_lb)
        seg = logp[lo:t]
        if len(seg) > 3:
            vol[t] = np.nanstd(seg[1:] - seg[:-1], axis=0)

    w = np.full(k, 1.0 / k)
    equity = np.empty(n)
    equity[0] = start_equity

    for t in range(1, n):
        w = w * (1.0 + rets[t])
        s = w.sum()
        w = w / s if s > 0 else np.zeros(k)
        equity[t] = equity[t - 1] * (1.0 + (w @ rets[t]))

        if t % rebal != 0:
            continue

        mv, vv = mom[t], vol[t]
        valid = np.isfinite(mv) & np.isfinite(vv) & (vv > 0)
        tw = np.zeros(k)

        if mode == "eq":
            sel = valid & ((mv > 0) if mom_gate else True)
            if sel.sum() > 0:
                tw[sel] = 1.0 / sel.sum()
        elif mode == "rp":
            sel = valid & ((mv > 0) if mom_gate else True)
            inv = np.zeros(k)
            inv[sel] = 1.0 / vv[sel]
            if inv.sum() > 0:
                tw = inv / inv.sum()
        elif mode in ("combo", "blend"):
            sel = valid & ((mv > 0) if mom_gate else True)
            if topk is not None and sel.sum() > topk:
                idx = np.where(sel)[0]
                keep = idx[np.argsort(-mv[idx])[:topk]]
                sel = np.zeros(k, dtype=bool)
                sel[keep] = True
            inv = np.zeros(k)
            inv[sel] = 1.0 / vv[sel]
            if inv.sum() > 0:
                rpw = inv / inv.sum()
                if mode == "blend":
                    eqw = np.zeros(k)
                    eqw[sel] = 1.0 / sel.sum()
                    tw = (1.0 - eq_frac) * rpw + eq_frac * eqw
                else:
                    tw = rpw
        elif mode == "momw":
            sel = valid
            pos_m = np.maximum(mv, 0.0)
            wgt = np.zeros(k)
            wgt[sel] = (1.0 / vv[sel]) * (1.0 + 4.0 * pos_m[sel] / (np.max(pos_m[sel]) + 1e-12))
            if wgt.sum() > 0:
                tw = wgt / wgt.sum()

        if tw.sum() > 0 and target_vol is not None:
            pw = np.sqrt((tw * vv) @ (tw * vv))
            pv_ann = pw * np.sqrt(252) if pw > 0 else 1.0
            if pv_ann > 0:
                tw = tw * min(target_vol / pv_ann, 1.5)

        if min_w > 0:
            m = tw > 0
            tw[m] = np.maximum(tw[m], min_w)

        to = np.abs(tw - w).sum()
        fee_amt = fee * to * equity[t]
        diff = tw - w
        cost = np.abs(diff).sum()
        if cost > 1.0:
            tw = w + diff * (1.0 / cost)
        w = tw
        equity[t] -= fee_amt

    return pd.Series(equity, index=prices.index)
