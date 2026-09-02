"""Inspect the 42 'coin-flip' liquid markets (fav_price 0.50-0.60) that drive the
apparent buy-favorite edge. Are they one series/event (artifact) or diverse?"""
import pickle
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

liq = pd.DataFrame(sec_pickle_load(open(f"{OUT}/pm_kalshi_liquid.pkl", "rb")))
liq = pd.DataFrame(pickle.load(open(f"{OUT}/pm_kalshi_liquid.pkl", "rb")))
p = liq.p_final
liq["fav_price"] = p.clip(0.5, 1.0)
liq["fav_win"] = (p >= 0.5) * liq.result + (p < 0.5) * (1 - liq.result)

coin = liq[(liq.fav_price >= 0.50) & (liq.fav_price <= 0.60)].copy()
print(f"coin-flip cluster: N={len(coin)}")
print(f"  fav_win (favorite-side wins): {coin.fav_win.mean():.3f}")
print(f"  result yes rate: {coin.result.mean():.3f}")
print(f"  p_final: mean={coin.p_final.mean():.3f}  (how many exactly 0.50?) {(coin.p_final==0.5).sum()}")
print(f"  lead_h: med={coin.lead_h.median():.1f}h  max={coin.lead_h.max():.1f}h")
print(f"  volume: med={coin.volume.median():.0f}")
print(f"\n  by series (top 12):")
print(coin.series.value_counts().head(12).to_string())
print(f"\n  close_ts spread (UTC):")
ct = pd.to_datetime(coin.close_ts, unit="s", utc=True)
print(f"    min={ct.min()}  max={ct.max()}")
print(f"\n  sample tickers:")
print(coin[["ticker","series","p_final","result","lead_h","volume"]].head(20).to_string())

# contrast: the near-certain cluster
near = liq[liq.fav_price > 0.95]
print(f"\nnear-certain cluster: N={len(near)}  fav_win={near.fav_win.mean():.3f}  "
      f"avg fav_price={near.fav_price.mean():.3f}")
print(f"  by series (top 8):")
print(near.series.value_counts().head(8).to_string())
