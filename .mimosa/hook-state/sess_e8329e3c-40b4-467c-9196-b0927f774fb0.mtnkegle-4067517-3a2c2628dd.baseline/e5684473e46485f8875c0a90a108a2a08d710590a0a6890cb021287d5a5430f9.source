#!/usr/bin/env python3
"""Autonomous task: the deferred honest sentiment holdout (3/5/10-day).

Tests whether FinBERT financial sentiment predicts LONGER-horizon forward
returns (3/5/10 days), which the 1-day test missed. Uses the fintweet-2025
dataset filtered to our liquid universe, aligns each tweet to the NEXT 3/5/10
trading days' forward return (yfinance daily), and measures sentiment
separation of up vs down outcomes at each horizon.
"""

import json
from pathlib import Path

import pandas as pd

from setup_search.sentiment_value import TECH_COLS  # reuse

PROJECT = Path(__file__).resolve().parent.parent
DATA = Path("/tmp/opencode")
OUT = PROJECT / "data" / "research_gate"
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "JPM",
            "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX"]
HORIZONS = [3, 5, 10]


def main():
    from transformers import pipeline
    import torch

    df = pd.read_parquet(DATA / "fintweet_train.parquet")
    df = df[df["ticker"].isin(UNIVERSE)].copy()
    print(f"[sent3d] {len(df)} tweets for universe tickers", flush=True)

    # forward returns per horizon from yfinance daily
    import yfinance as yf
    px = {}
    for tk in UNIVERSE:
        try:
            v = yf.download(tk, period="2y", interval="1d", auto_adjust=True, progress=False)
            s = v["Close"]
            s = s[tk] if hasattr(s, "columns") else s
            px[tk] = s.dropna()
        except Exception as e:
            print(f"  price fail {tk}: {e}", flush=True)
    print(f"[sent3d] prices for {len(px)}/{len(UNIVERSE)} tickers", flush=True)

    df["day"] = pd.to_datetime(df["timestamp"], utc=True).dt.normalize()
    for h in HORIZONS:
        fwd_map = {}
        for tk, grp in df.groupby("ticker"):
            s = px.get(tk)
            if s is None:
                continue
            for d in grp["day"]:
                try:
                    pos = s.index.searchsorted(pd.Timestamp(d).tz_localize(None))
                    if pos + h < len(s):
                        fwd_map[(d, tk)] = float(s.iloc[pos + h] / s.iloc[pos] - 1.0)
                except Exception:
                    continue
        df[f"fwd_{h}d"] = df.apply(lambda r: fwd_map.get((r["day"], r["ticker"])), axis=1)
        print(f"[sent3d] {h}d fwd rows: {df[f'fwd_{h}d'].notna().sum()}", flush=True)

    # FinBERT sentiment on the universe tweets (subsample to keep it bounded)
    pipe = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                    device=0 if torch.cuda.is_available() else -1,
                    truncation=True, max_length=512)
    aligned = df.dropna(subset=[f"fwd_{HORIZONS[-1]}d"])
    if len(aligned) < 200:
        print("[sent3d] too few aligned forward rows - cannot test", flush=True)
        import json as _j
        (PROJECT / "data" / "research_gate" / "sentiment_holdout_3_10d.json").write_text(
            _j.dumps({"verdict": "insufficient aligned data"}))
        return
    sample = aligned.sample(min(4000, len(aligned)), random_state=7)
    sents = []
    for i in range(0, len(sample), 32):
        res = pipe(sample["text"].iloc[i:i + 32].tolist())
        sents += [r["score"] if r["label"] == "positive" else -r["score"] for r in res]
    sample["sent"] = sents

    results = {}
    for h in HORIZONS:
        col = f"fwd_{h}d"
        s = sample.dropna(subset=[col])
        up = s[s[col] > 0]["sent"]
        dn = s[s[col] <= 0]["sent"]
        sep = float(up.mean() - dn.mean())
        results[h] = {"n": len(s), "up_mean_sent": float(up.mean()),
                      "down_mean_sent": float(dn.mean()), "separation": sep}
        print(f"[sent3d] {h}d: n={len(s)} up_sent={up.mean():+.4f} "
              f"down_sent={dn.mean():+.4f} separation={sep:+.4f}", flush=True)

    verdict = "sentiment predicts longer-horizon returns" if any(
        v["separation"] > 0.01 for v in results.values()) else "no longer-horizon sentiment signal"
    out = OUT / "sentiment_holdout_3_10d.json"
    out.write_text(json.dumps({**results, "verdict": verdict}, indent=1, default=str))
    print(f"[sent3d] verdict: {verdict} -> {out}", flush=True)


if __name__ == "__main__":
    main()
