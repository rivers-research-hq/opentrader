"""
pm6: Favorite-longshot bias + MM spread-capture on the live2 sample (617 resolved
binary markets, Aug 24-25).

KEY DATA-QUALITY FINDING: 518/617 markets have a degenerate final-candle quote
(bid=0/ask=1, spread=1.0) -> their mid is NOT a tradeable price. Only markets with a
real two-sided quote (spread <= 0.10) have a price you could actually trade at.
So the tradable-edge analysis runs on the LIQUID subset; the full sample is reported
for comparison only.

Favorite-longshot (side-symmetric):
  favorite  = higher-priced side, price fav_price = max(p, 1-p) in [0.5, 1]
  longshot  = lower-priced side,  price long_price = min(p, 1-p) in [0, 0.5]
  H0 (efficient): empirical win rate of a side == its price.
  Edge/contract (USD) = win_rate - price - 0.07*price*(1-price)   [Kalshi taker fee]
"""
import pickle, os
import numpy as np
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

OUT = "/home/mrc/opentrader/data/shadow_scaled"
FEE = 0.07
RNG = np.random.default_rng(42)

def fee(p):
    return FEE * p * (1 - p)

def side_features(d, pcol):
    """Return a copy with favorite/longshot side features built from price column pcol."""
    d = d.dropna(subset=[pcol]).copy()
    d = d[(d[pcol] > 0.001) & (d[pcol] < 0.999)].copy()
    p = d[pcol]
    d["fav_price"] = p.clip(0.5, 1.0)
    d["fav_win"] = np.where(p >= 0.5, d["result"], 1 - d["result"])
    d["long_price"] = 1 - d["fav_price"]
    d["long_win"] = 1 - d["fav_win"]
    return d

def binned(sub, price_col, win_col, bins, label):
    print(f"\n[{label}]  bin by {price_col} -> empirical win rate vs price")
    print(f"  {price_col:>10} {'n':>5} {'avg_price':>10} {'win_rate':>9} {'raw_edge':>9} {'fee':>7} {'net_edge':>9}")
    for lo, hi in zip(bins[:-1], bins[1:]):
        b = sub[(sub[price_col] > lo) & (sub[price_col] <= hi)]
        if len(b) < 3:
            continue
        ap = b[price_col].mean(); wr = b[win_col].mean()
        print(f"  {lo:>4.2f}-{hi:<4.2f} {len(b):>5} {ap:>10.4f} {wr:>9.4f} {wr-ap:>+9.4f} {fee(ap):>7.4f} {wr-ap-fee(ap):>+9.4f}")

def bootstrap_edge(win, price, nboot=2000):
    """Bootstrap CI for mean(win - price - fee(price))."""
    edge = win - price - fee(price)
    n = len(edge)
    means = np.array([RNG.choice(edge, n, replace=True).mean() for _ in range(nboot)])
    return edge.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)

def aggregate(sub, tag):
    fe, lo, hi = bootstrap_edge(sub.fav_win.values, sub.fav_price.values)
    le, llo, lhi = bootstrap_edge(sub.long_win.values, sub.long_price.values)
    print(f"\n  [AGGREGATE {tag}] (N={len(sub)})")
    print(f"    buy-FAVORITE  net edge = {fe*100:+.2f}c/contract  95%CI [{lo*100:+.2f}, {hi*100:+.2f}]c   "
          f"(wins {sub.fav_win.mean():.3f} @ avg price {sub.fav_price.mean():.3f})")
    print(f"    buy-LONGSHOT  net edge = {le*100:+.2f}c/contract  95%CI [{llo*100:+.2f}, {lhi*100:+.2f}]c   "
          f"(wins {sub.long_win.mean():.3f} @ avg price {sub.long_price.mean():.3f})")
    # regression fav_win ~ fav_price  (slope<1 => longshot overpriced / favorite underpriced)
    x = sub.fav_price.values; y = sub.fav_win.values
    if len(x) > 5 and x.std() > 0:
        b1, b0 = np.polyfit(x, y, 1)
        print(f"    regression fav_win = {b0:.3f} + {b1:.3f}*fav_price   (slope {b1:.2f}; <1 => favorite-longshot bias)")

    d = pd.DataFrame(sec_pickle_load(open(f"{OUT}/pm_kalshi_live2_features.pkl", "rb")))
    d = pd.DataFrame(pickle.load(open(f"{OUT}/pm_kalshi_live2_features.pkl", "rb")))
    print(f"full sample N = {len(d)}")
    liq = d[d.spread <= 0.10]
    print(f"LIQUID subset (final-candle spread <= 0.10, real tradeable price) N = {len(liq)}")
    print(f"  liquid lead_h med={liq.lead_h.median():.1f}h  volume med={liq.volume.median():.0f}  "
          f"yes_rate={liq.result.mean():.3f}")

    fav_bins = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]
    long_bins = [0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5]

    for name, sub_raw, pcol in [
        ("LIQUID subset (tradable)", liq, "p_final"),
        ("FULL sample (incl. degenerate quotes, NOT tradable)", d, "p_final"),
    ]:
        print(f"\n{'='*74}\n{name}  (price={pcol})\n{'='*74}")
        s = side_features(sub_raw, pcol)
        binned(s, "fav_price", "fav_win", fav_bins, "FAVORITE side")
        binned(s, "long_price", "long_win", long_bins, "LONGSHOT side")
        aggregate(s, name.split()[0])

    # MM spread-capture estimate (liquid subset): the MM's edge = half-spread captured
    # per round trip, in cents, vs the taker fee a directional trader pays.
    print(f"\n{'='*74}\nMM SPREAD-CAPTURE (liquid subset, final-candle quotes)\n{'='*74}")
    sp = liq.spread.dropna()
    print(f"  n={len(sp)}  mean spread={sp.mean()*100:.2f}c  median={sp.median()*100:.2f}c  "
          f"p90={sp.quantile(0.9)*100:.2f}c")
    print(f"  (a taker crossing the spread pays ~half-spread = {(sp.mean()/2)*100:.2f}c/contract on average)")
    print(f"  taker fee at p=0.5 = {fee(0.5)*100:.2f}c/contract; at p=0.1 = {fee(0.1)*100:.2f}c")

    # save
    liq.to_pickle(f"{OUT}/pm_kalshi_liquid.pkl")
    print(f"\nsaved liquid subset -> {OUT}/pm_kalshi_liquid.pkl")

if __name__ == "__main__":
    main()
