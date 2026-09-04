"""Inspect the spread anomaly + candle structure in the live2 sample."""
import pickle, statistics
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

d = pd.DataFrame(sec_pickle_load(open(f"{OUT}/pm_kalshi_live2_features.pkl", "rb")))
d = pd.DataFrame(pickle.load(open(f"{OUT}/pm_kalshi_live2_features.pkl", "rb")))
print(f"N={len(d)}")
print("\nspread describe:")
print(d.spread.describe())
print("\nspread value counts (top 10):")
print(d.spread.round(3).value_counts().head(10))
print("\nlead_h buckets:")
print(pd.cut(d.lead_h, [0,1,2,6,12,24,1000]).value_counts().sort_index())
print("\np_early vs p_final: how often equal?")
print(f"  equal: {(d.p_early==d.p_final).sum()}, diff>0.05: {((d.p_early-d.p_final).abs()>0.05).sum()}")
print("\nexample rows (spread, p_early, p_final, lead_h, volume, result):")
cols = ["spread","p_early","p_final","lead_h","volume","result","n_candles"]
print(d[cols].head(15).to_string())
print("\nrows with spread==1.0:")
print(d[d.spread==1.0][cols].head(10).to_string())
