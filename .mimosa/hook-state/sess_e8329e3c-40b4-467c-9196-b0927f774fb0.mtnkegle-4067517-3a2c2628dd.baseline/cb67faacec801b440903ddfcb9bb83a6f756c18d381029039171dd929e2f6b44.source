#!/usr/bin/env python3
"""The sentiment question, done right: does REAL news sentiment add predictive
value over technicals for 1-day forward returns?

Source: michael-zus/fintweet-sentiment-2025 — timestamped, per-ticker financial
tweets with technical features and a 1-day forward 3-class label (0=down,
1=flat, 2=up). VADER scores the tweet text as the sentiment feature.

Test: a value model predicts the 1-day forward class from
  (a) the dataset's technical features only,
  (b) technicals + tweet sentiment.
If sentiment adds value, (b) beats (a) on held-out data — measured by
separation of up(2) vs down(0) (discrimination) and class accuracy.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

PROJECT = Path(__file__).resolve().parent.parent
DATA = Path("/tmp/opencode")
SEED = 41
TECH_COLS = ["volatility_7d", "relative_volume", "rsi_14", "distance_from_ma_20",
             "return_5d", "return_20d", "above_ma_20", "slope_ma_20", "gap_open",
             "intraday_range"]


class Net(nn.Module):
    def __init__(self, d_in):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d_in, 32), nn.ReLU(), nn.Dropout(0.2),
                                 nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 3))

    def forward(self, x):
        return self.net(x)


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    df = pd.read_parquet(DATA / "fintweet_train.parquet")
    df = df.dropna(subset=TECH_COLS)
    # split by time: train Jan-May, test Jun-Aug (held out)
    tr = df[df["timestamp"] < "2025-06-01"]
    te = df[df["timestamp"] >= "2025-06-01"]
    print(f"[sent] {len(tr)} train / {len(te)} test tweets")

    sia = SentimentIntensityAnalyzer()
    for split in (tr, te):
        split["sent"] = split["text"].map(lambda t: sia.polarity_scores(t)["compound"])

    def build(df, use_sent):
        X = df[TECH_COLS].values.astype(np.float32)
        if use_sent:
            X = np.concatenate([X, df["sent"].values.astype(np.float32)[:, None]], axis=1)
        y = df["label_1d_3class"].values.astype(np.int64)
        return torch.tensor(X), torch.tensor(y)

    def run(use_sent, label):
        Xtr, ytr = build(tr, use_sent)
        Xte, yte = build(te, use_sent)
        mean, std = Xtr.mean(0), Xtr.std(0)
        Xtr = (Xtr - mean) / (std + 1e-8)
        Xte = (Xte - mean) / (std + 1e-8)
        model = Net(Xtr.shape[1])
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
        lossf = nn.CrossEntropyLoss()
        for _ in range(80):
            opt.zero_grad()
            loss = lossf(model(Xtr), ytr)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            prob = torch.softmax(model(Xte), 1)
        # discrimination: predicted P(up=2) - P(down=0) separates classes
        score = (prob[:, 2] - prob[:, 0]).numpy()
        up = score[yte.numpy() == 2]
        down = score[yte.numpy() == 0]
        sep = float(up.mean() - down.mean())
        acc = float((prob.argmax(1) == yte).float().mean())
        print(f"  {label:28s} held-out accuracy={acc:.3f}  "
              f"up-vs-down separation={sep:+.4f}")
        return acc, sep

    print("\n=== does sentiment add value? (held-out: Jun-Aug 2025) ===")
    acc_a, sep_a = run(False, "technicals only")
    acc_b, sep_b = run(True, "technicals + sentiment")
    verdict = "SENTIMENT ADDS VALUE" if (acc_b > acc_a or sep_b > sep_a) else "sentiment adds nothing"
    print(f"\n  verdict: {verdict}")
    out = PROJECT / "data" / "research_gate" / "sentiment_value.json"
    out.write_text(json.dumps({"acc_tech": acc_a, "acc_sent": acc_b,
                               "sep_tech": sep_a, "sep_sent": sep_b,
                               "verdict": verdict}, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
