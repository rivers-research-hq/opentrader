"""
pm8: CORRECTED favorite-longshot + MM spread-capture on the clean live3 sample
(554 resolved binary, 345 with real tradeable prices, Aug 24-25).

FIX vs pm_analyze/pm_analyze2: favorite price is max(p, 1-p), NOT p.clip(0.5,1).
Price reference = p_first_real (first candle with a tight two-sided quote, i.e. the
first price a trader could actually cross). Side-symmetric:
  favorite = higher-priced side (fav_price in [0.5,1]); longshot = lower (in [0,0.5]).
  H0 (efficient): a side's empirical win rate == its price.
  Edge/contract (USD) = win_rate - price - 0.07*price*(1-price)  [Kalshi taker fee]
"""
import pickle
import numpy as np
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

OUT = "/home/mrc/opentrader/data/shadow_scaled"
FEE = 0.07
RNG = np.random.default_rng(42)

def fee(p):
    return FEE * p * (1 - p)

def side(d, pcol):
    d = d.dropna(subset=[pcol]).copy()
    d = d[(d[pcol] > 0.001) & (d[pcol] < 0.999)].copy()
    p = d[pcol]
    d["fav_price"] = np.maximum(p, 1 - p)                 # CORRECT
    d["fav_win"] = np.where(p >= 0.5, d["result"], 1 - d["result"])
    d["long_price"] = 1 - d["fav_price"]                  # = min(p,1-p)
    d["long_win"] = 1 - d["fav_win"]
    return d

def binned(sub, pc, wc, bins, label):
    print(f"\n[{label}]  bin by {pc} -> win rate vs price")
    print(f"  {pc:>10} {'n':>5} {'avg_price':>10} {'win_rate':>9} {'raw_edge':>9} {'fee':>7} {'net_edge':>9}")
    for lo, hi in zip(bins[:-1], bins[1:]):
        b = sub[(sub[pc] > lo) & (sub[pc] <= hi)]
        if len(b) < 3:
            continue
        ap = b[pc].mean(); wr = b[wc].mean()
        print(f"  {lo:>4.2f}-{hi:<4.2f} {len(b):>5} {ap:>10.4f} {wr:>9.4f} {wr-ap:>+9.4f} {fee(ap):>7.4f} {wr-ap-fee(ap):>+9.4f}")

def boot(win, price, nboot=4000):
    e = win - price - fee(price); n = len(e)
    m = np.array([RNG.choice(e, n, replace=True).mean() for _ in range(nboot)])
    return e.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

def aggregate(sub, tag):
    fe, lo, hi = boot(sub.fav_win.values, sub.fav_price.values)
    le, llo, lhi = boot(sub.long_win.values, sub.long_price.values)
    print(f"\n  [AGGREGATE {tag}] (N={len(sub)})")
    print(f"    buy-FAVORITE  net edge = {fe*100:+.2f}c  95%CI [{lo*100:+.2f},{hi*100:+.2f}]c  "
          f"(wins {sub.fav_win.mean():.3f} @ avg price {sub.fav_price.mean():.3f})")
    print(f"    buy-LONGSHOT  net edge = {le*100:+.2f}c  95%CI [{llo*100:+.2f},{lhi*100:+.2f}]c  "
          f"(wins {sub.long_win.mean():.3f} @ avg price {sub.long_price.mean():.3f})")
    x = sub.fav_price.values; y = sub.fav_win.values
    if len(x) > 5 and x.std() > 0:
        b1, b0 = np.polyfit(x, y, 1)
        print(f"    regression fav_win = {b0:.3f} + {b1:.3f}*fav_price  (slope {b1:.2f}; <1 => fav underpriced/longshot overpriced)")

    d = pd.DataFrame(sec_pickle_load(open(f"{OUT}/pm_kalshi_live3_features.pkl", "rb")))
    d = pd.DataFrame(pickle.load(open(f"{OUT}/pm_kalshi_live3_features.pkl", "rb")))
    d = d[d.n_real > 0].copy()
    print(f"real-price sample N = {len(d)}  (of {len(pd.DataFrame(pickle.load(open(f'{OUT}/pm_kalshi_live3_features.pkl','rb'))))} total)")
    p = d.p_first_real
    d["fav_price"] = np.maximum(p, 1 - p)
    print(f"\nfav_price distribution (first real price):")
    print(pd.cut(d.fav_price, [0.5,0.6,0.7,0.8,0.9,0.95,0.99,1.0]).value_counts().sort_index().to_string())
    print(f"  yes_rate={d.result.mean():.3f}  lead_h med={d.lead_h.median():.1f}h  volume med={d.volume.median():.0f}")

    fav_bins = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
    long_bins = [0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5]
    s = side(d, "p_first_real")
    print(f"\n{'='*74}\nFAVORITE-LONGSHOT on p_first_real (first tradeable price)\n{'='*74}")
    binned(s, "fav_price", "fav_win", fav_bins, "FAVORITE side")
    binned(s, "long_price", "long_win", long_bins, "LONGSHOT side")
    aggregate(s, "first-real")

    # MM spread-capture (real quotes)
    print(f"\n{'='*74}\nMM SPREAD-CAPTURE (real quotes, first-real candle)\n{'='*74}")
    sp = d.spread_first_real.dropna()
    print(f"  n={len(sp)}  mean={sp.mean()*100:.2f}c  median={sp.median()*100:.2f}c  p90={sp.quantile(0.9)*100:.2f}c  max={sp.max()*100:.2f}c")
    print(f"  taker crossing pays ~half-spread = {(sp.mean()/2)*100:.2f}c/contract;  taker fee @0.5 = {fee(0.5)*100:.2f}c, @0.1 = {fee(0.1)*100:.2f}c")

    d.to_pickle(f"{OUT}/pm_kalshi_live3_real.pkl")
    print(f"\nsaved real-price sample -> {OUT}/pm_kalshi_live3_real.pkl")

if __name__ == "__main__":
    main()
