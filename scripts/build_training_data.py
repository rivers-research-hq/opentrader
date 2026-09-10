#!/usr/bin/env python3
"""build_training_data — feature engineering from the accrual store into a
training dataset (map #198; the ML pipeline the user directed).

Reads the store (bars D1+H1 for all pairs, releases_history, exog) and
produces a per-pair-per-day feature matrix + forward return labels for
supervised learning. Features express the research agent's candidate
mechanisms (carry, policy cycle, positioning, news proximity, volatility
regime) plus price-action features the hand-coded families couldn't express.

Usage: python3 scripts/build_training_data.py
Output: /home/mrc/opentrader-data/training/features.parquet + labels.parquet
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STORE = "/home/mrc/opentrader-data/store.duckdb"
OUT = Path(__file__).resolve().parent.parent / "data" / "training"
OUT.mkdir(parents=True, exist_ok=True)


def build_features(con):
    """Per-pair per-day feature matrix from the store."""
    pairs = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars WHERE timeframe='1d' ORDER BY 1").fetchall()]

    frames = []
    for pair in pairs:
        base, quote = pair.split("_")

        # D1 bars
        d1 = con.execute("""
            SELECT ts, open, high, low, close, volume FROM bars
            WHERE symbol = ? AND timeframe = '1d' ORDER BY ts
        """, [pair]).fetchall()
        if len(d1) < 60:
            continue
        df = pd.DataFrame(d1, columns=["ts", "open", "high", "low", "close", "volume"])
        df = df.set_index("ts")
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        lo = df["low"].astype(float)
        v = df["volume"].astype(float)

        f = pd.DataFrame(index=df.index)
        f["pair"] = pair
        f["close"] = c

        # ── price action ──
        for lb in (5, 10, 20, 60, 120):
            f[f"mom_{lb}d"] = c / c.shift(lb) - 1.0
        f["rev_5d"] = -(c / c.shift(5) - 1.0)
        f["rev_20d"] = -(c / c.shift(20) - 1.0)
        f["brk_20d"] = c / h.rolling(20).max() - 1.0
        f["brk_60d"] = c / h.rolling(60).max() - 1.0
        f["z_20d"] = (c - c.rolling(20).mean()) / c.rolling(20).std()
        f["z_60d"] = (c - c.rolling(60).mean()) / c.rolling(60).std()

        # volatility regime
        ret = c.pct_change()
        f["vol_20d"] = ret.rolling(20).std()
        f["vol_60d"] = ret.rolling(60).std()
        f["vol_ratio"] = f["vol_20d"] / f["vol_60d"]
        f["atr_14d"] = (h - lo).rolling(14).mean()

        # range/efficiency
        hh = h.rolling(20).max()
        ll = lo.rolling(20).min()
        f["efficiency_20d"] = (c - c.shift(20)).abs() / (hh - ll).replace(0, np.nan)

        # ── rates (from exog if available, else 0) ──
        rate = con.execute("""
            SELECT CAST(date AS DATE) AS d, value FROM exog
            WHERE series = 'RATE:US' ORDER BY d
        """).fetchall()
        rate_df = pd.DataFrame(rate, columns=["d", "rate"]).set_index("d")
        rate_s = rate_df["rate"]
        f["rate_level"] = rate_s.reindex(f.index).ffill()
        f["rate_chg_20d"] = f["rate_level"].diff(20)
        f["rate_slope_5d"] = f["rate_level"].diff(5)

        # 2y yield (implied policy path)
        dgs2 = con.execute("""
            SELECT CAST(date AS DATE) AS d, value FROM exog
            WHERE series = 'PATH:US' OR series LIKE '%DGS2%' ORDER BY d
        """).fetchall()
        if dgs2:
            d2df = pd.DataFrame(dgs2, columns=["d", "y2"]).set_index("d")
            f["y2_yield"] = d2df["y2"].reindex(f.index).ffill()
            f["y2_chg_20d"] = f["y2_yield"].diff(20)

        # carry (from exog CARRY series for this pair)
        carry = con.execute("""
            SELECT CAST(date AS DATE) AS d, value FROM exog
            WHERE series = ? ORDER BY d
        """, [f"CARRY:{pair}"]).fetchall()
        if carry:
            cdf = pd.DataFrame(carry, columns=["d", "carry"]).set_index("d")
            f["carry"] = cdf["carry"].reindex(f.index).ffill()
            f["carry_z"] = (f["carry"] - f["carry"].rolling(252).mean()) / f["carry"].rolling(252).std().replace(0, np.nan)

        # COT positioning
        cur_map = {"EUR_USD": "EUR", "GBP_USD": "GBP", "AUD_USD": "AUD",
                   "USD_JPY": "JPY", "USD_CHF": "CHF", "USD_CAD": "CAD"}
        cot_cur = cur_map.get(pair)
        if cot_cur:
            cot = con.execute("""
                SELECT CAST(date AS DATE) AS d, value FROM exog
                WHERE series = ? ORDER BY d
            """, [f"COT:{cot_cur}"]).fetchall()
            if cot:
                cdf = pd.DataFrame(cot, columns=["d", "cot_z"]).set_index("d")
                f["cot_z"] = cdf["cot_z"].reindex(f.index).ffill()

        # ── event proximity (days to next high-impact release for this currency) ──
        cur_map2 = {"EUR_USD": "EUR", "GBP_USD": "GBP", "AUD_USD": "AUD",
                    "USD_JPY": "JPY", "USD_CHF": "CHF", "USD_CAD": "CAD",
                    "USD_MXN": "MXN", "USD_ZAR": "ZAR", "USD_TRY": "TRY",
                    "USD_NOK": "NOK", "USD_SEK": "SEK"}
        ev_cur = cur_map2.get(pair, base)
        ev = con.execute("""
            SELECT CAST(ts AS DATE) AS d, COUNT(*) as n
            FROM releases_history WHERE currency = ? AND impact = 'high'
            GROUP BY 1 ORDER BY 1
        """, [ev_cur[:2] if len(ev_cur) > 3 else ev_cur]).fetchall()
        if ev:
            evdf = pd.DataFrame(ev, columns=["d", "n_events"]).set_index("d")
            # days since last event, days to next event (forward fill/backfill count)
            f["events_lag_5d"] = evdf["n_events"].reindex(f.index).ffill().fillna(0)
        else:
            f["events_lag_5d"] = 0

        frames.append(f)

    all_f = pd.concat(frames)
    all_f = all_f.drop(columns=["close"], errors="ignore")
    return all_f


def build_labels(con):
    """Forward return labels: 1d, 5d, 20d ahead per pair per day."""
    pairs = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars WHERE timeframe='1d' ORDER BY 1").fetchall()]
    frames = []
    for pair in pairs:
        d1 = con.execute("""
            SELECT ts, close FROM bars WHERE symbol = ? AND timeframe = '1d' ORDER BY ts
        """, [pair]).fetchall()
        if len(d1) < 30:
            continue
        df = pd.DataFrame(d1, columns=["ts", "close"]).set_index("ts")
        c = df["close"].astype(float)
        f = pd.DataFrame(index=df.index)
        f["pair"] = pair
        for h in (1, 5, 20):
            f[f"fwd_ret_{h}d"] = c.shift(-h) / c - 1.0
        frames.append(f)
    return pd.concat(frames)


def main():
    con = duckdb.connect(STORE, read_only=True)
    print("[ml] building features from store...")
    features = build_features(con)
    print(f"[ml] features: {features.shape[0]} rows × {features.shape[1]} cols, "
          f"{features['pair'].nunique()} pairs, "
          f"{features.index.min()} → {features.index.max()}")

    labels = build_labels(con)
    print(f"[ml] labels: {labels.shape[0]} rows, {labels['pair'].nunique()} pairs")

    # save
    features.to_parquet(OUT / "features.parquet", compression="zstd")
    labels.to_parquet(OUT / "labels.parquet", compression="zstd")
    manifest = {
        "features_rows": len(features), "features_cols": features.shape[1] - 1,
        "labels_rows": len(labels), "pairs": sorted(features["pair"].unique().tolist()),
        "date_range": [str(features.index.min()), str(features.index.max())],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    print(f"[ml] saved to {OUT}")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
