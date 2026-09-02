#!/usr/bin/env python3
"""MoT sentiment expert: train a value head on technicals + FinBERT sentiment,
predicting 3-10 day forward returns. The confirmed sentiment signal, turned
into a deployable expert. Heavy GPU0 work (FinBERT feature scoring).

Data: michael-zus/fintweet-sentiment-2025 (timestamped per-ticker financial
tweets). Features = the dataset's technicals + FinBERT compound sentiment.
Label = 10-day forward return (aligned to prices). Train 2025 Jan-May, hold
out Jun-Aug. Reports held-out discrimination vs technicals-only.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

PROJECT = Path(__file__).resolve().parent.parent
DATA = Path("/tmp/opencode")
OUT = PROJECT / "data" / "research_gate"
SEED = 43
TECH_COLS = ["volatility_7d", "relative_volume", "rsi_14", "distance_from_ma_20",
             "return_5d", "return_20d", "above_ma_20", "slope_ma_20", "gap_open",
             "intraday_range"]
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "JPM",
            "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX"]
HORIZON = 10


class Net(nn.Module):
    def __init__(self, d_in):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, 32), nn.ReLU(), nn.Dropout(0.2),
                                 nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))

    def forward(self, x):
        return self.net(x).squeeze(-1)


def main():
    import yfinance as yf
    from transformers import pipeline
    import torch as T

    df = pd.read_parquet(DATA / "fintweet_train.parquet")
    df = df[df["ticker"].isin(UNIVERSE)].copy()
    df["day"] = pd.to_datetime(df["timestamp"], utc=True).dt.normalize()

    # 10-day forward returns from prices (naive-index, aligned)
    px = {}
    for tk in UNIVERSE:
        try:
            v = yf.download(tk, period="2y", interval="1d", auto_adjust=True, progress=False)
            s = v["Close"]
            s = s[tk] if hasattr(s, "columns") else s
            px[tk] = s.dropna()
        except Exception:
            continue
    fwd_map = {}
    for tk, grp in df.groupby("ticker"):
        s = px.get(tk)
        if s is None:
            continue
        for d in grp["day"]:
            try:
                pos = s.index.searchsorted(pd.Timestamp(d).tz_localize(None))
                if pos + HORIZON < len(s):
                    fwd_map[(d, tk)] = float(s.iloc[pos + HORIZON] / s.iloc[pos] - 1.0)
            except Exception:
                continue
    df[f"fwd_{HORIZON}d"] = df.apply(lambda r: fwd_map.get((r["day"], r["ticker"])), axis=1)
    df = df.dropna(subset=TECH_COLS + [f"fwd_{HORIZON}d"])
    print(f"[expert] {len(df)} aligned rows", flush=True)

    # FinBERT sentiment on GPU0 (the sustained GPU work)
    pipe = pipeline("sentiment-analysis", model="ProsusAI/finbert",
                    device=0 if T.cuda.is_available() else -1,
                    truncation=True, max_length=512)
    sents = []
    for i in range(0, len(df), 64):
        res = pipe(df["text"].iloc[i:i + 64].tolist())
        sents += [r["score"] if r["label"] == "positive" else -r["score"] for r in res]
    df["sent"] = sents
    print(f"[expert] FinBERT scored {len(df)} tweets on GPU0", flush=True)

    tr = df[df["day"] < pd.Timestamp("2025-06-01", tz="UTC")]
    te = df[df["day"] >= pd.Timestamp("2025-06-01", tz="UTC")]

    def build(d, use_sent):
        X = d[TECH_COLS].values.astype(np.float32)
        if use_sent:
            X = np.concatenate([X, d["sent"].values.astype(np.float32)[:, None]], axis=1)
        y = d[f"fwd_{HORIZON}d"].values.astype(np.float32)
        return X, y

    def run(use_sent, label):
        Xtr, ytr = build(tr, use_sent)
        Xte, yte = build(te, use_sent)
        mean, std = Xtr.mean(0), Xtr.std(0)
        Xtr = (Xtr - mean) / (std + 1e-8)
        Xte = (Xte - mean) / (std + 1e-8)
        model = Net(Xtr.shape[1])
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        lossf = nn.MSELoss()
        Xt, yt = torch.tensor(Xtr), torch.tensor(ytr)
        for _ in range(120):
            opt.zero_grad()
            loss = lossf(model(Xt), yt)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            pred = model(torch.tensor(Xte)).numpy()
        up = pred[yte > 0]
        dn = pred[yte <= 0]
        sep = float(up.mean() - dn.mean())
        print(f"  {label:26s} pred-up {up.mean():+.4f} pred-down {dn.mean():+.4f} "
              f"separation {sep:+.4f}", flush=True)
        return sep

    print("=== held-out (Jun-Aug 2025) discrimination ===", flush=True)
    sep_tech = run(False, "technicals only")
    sep_sent = run(True, "technicals + sentiment")
    add = sep_sent - sep_tech
    verdict = ("sentiment ADDS to the expert" if add > 0.001
               else "sentiment adds nothing here")
    print(f"  sentiment marginal value: {add:+.4f} -> {verdict}", flush=True)
    out = OUT / "sentiment_expert.json"
    out.write_text(json.dumps({"sep_tech": sep_tech, "sep_sent": sep_sent,
                               "margin": add, "verdict": verdict,
                               "n_train": len(tr), "n_test": len(te)}, indent=1))
    print(f"-> {out}", flush=True)


if __name__ == "__main__":
    main()
