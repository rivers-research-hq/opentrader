"""
pm_diag: decompose the +1.20c favorite edge into taker vs maker.
p_first_real is the MID (from pm_pull_live3.py: (yes_bid+yes_ask)/2).
A taker pays the ASK = mid + spread/2; a maker posts the BID = mid - spread/2.
Favorite is side-symmetric: fav_ask = fav_price + spread/2 in both YES-fav and NO-fav cases.
Read-only diagnostic.
"""
import pickle
import numpy as np
import pandas as pd

OUT = "/home/mrc/opentrader/data/shadow_scaled"
FEE = 0.07
def fee(p): return FEE * p * (1 - p)

d = pd.read_pickle(f"{OUT}/pm_kalshi_live3_real.pkl")
d = d.dropna(subset=["p_first_real", "spread_first_real"]).copy()
p = d.p_first_real
d["fav_price"] = np.maximum(p, 1 - p)
d["fav_win"] = np.where(p >= 0.5, d["result"], 1 - d["result"])
sp = d.spread_first_real
d["fav_ask"] = d.fav_price + sp / 2          # what a taker pays
d["fav_bid"] = d.fav_price - sp / 2          # what a maker posts (buy side)

def boot(win, price, nboot=4000, rng=np.random.default_rng(42)):
    e = win - price; n = len(e)
    m = np.array([rng.choice(e, n, replace=True).mean() for _ in range(nboot)])
    return e.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

print(f"N={len(d)}  fav wins={d.fav_win.sum()}/{len(d)}  avg fav_price(mid)={d.fav_price.mean():.4f}")
print(f"avg spread={sp.mean()*100:.2f}c  half-spread={(sp.mean()/2)*100:.2f}c")
print(f"fee @ avg fav mid = {fee(d.fav_price.mean())*100:.3f}c   (NOT 1.75c; that's the p=0.5 value)")

# where is the single loss?
loss = d[d.fav_win == 0]
print(f"\nlosses: {len(loss)}")
for _, r in loss.iterrows():
    print(f"  {r.ticker}  fav_price={r.fav_price:.3f}  spread={r.spread_first_real*100:.1f}c  series={r.series}")
print(f"sub-0.90 favorites: {(d.fav_price < 0.90).sum()}  (bins with n<3 are skipped in pm_analyze3 binned view)")

def boot_arr(e, nboot=4000, seed=42):
    rng = np.random.default_rng(seed); n = len(e)
    m = np.array([rng.choice(e, n, replace=True).mean() for _ in range(nboot)])
    return e.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

print("\n=== FAVORITE EDGE: mid vs taker(ask) vs maker(bid) ===")
# 1) mid-based (what pm_analyze3 reported)
me, mlo, mhi = boot(d.fav_win.values, d.fav_price.values)
print(f"  MID    edge = {me*100:+.2f}c  CI[{mlo*100:+.2f},{mhi*100:+.2f}]   (win - mid - fee(mid))")
# 2) taker: pay ask, pay taker fee on ask
te = (d.fav_win - d.fav_ask - fee(d.fav_ask)).values
tm, tlo, thi = boot_arr(te)
print(f"  TAKER  edge = {tm*100:+.2f}c  CI[{tlo*100:+.2f},{thi*100:+.2f}]   (win - ask - fee(ask))")
# 3) maker: post bid, NO maker fee
mk = (d.fav_win - d.fav_bid).values
km, klo, khi = boot_arr(mk)
print(f"  MAKER  edge = {km*100:+.2f}c  CI[{klo*100:+.2f},{khi*100:+.2f}]   (win - bid, no fee)")

print("\n=== by fav_price bin: mid / taker / maker net edge (c) ===")
bins = [0.90, 0.95, 0.99, 1.0]
for lo, hi in zip(bins[:-1], bins[1:]):
    b = d[(d.fav_price > lo) & (d.fav_price <= hi)]
    if len(b) < 3: continue
    mid_e = (b.fav_win - b.fav_price - fee(b.fav_price)).mean()*100
    tak_e = (b.fav_win - b.fav_ask - fee(b.fav_ask)).mean()*100
    mak_e = (b.fav_win - b.fav_bid).mean()*100
    print(f"  {lo:.2f}-{hi:.2f}  n={len(b):>3}  mid={mid_e:+.2f}  taker={tak_e:+.2f}  maker={mak_e:+.2f}   (avg spread {b.spread_first_real.mean()*100:.1f}c)")
