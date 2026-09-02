#!/usr/bin/env python3
"""Train the neural multiverse generator (conditional DoppelGANger-style GAN).

Runs on GPU1 (RX 7900) during idle windows per the VRAM-lock discipline — do NOT
run while the trading harness is live. Output: data/scenarios/neural_gen.pt.

Usage:
  /home/mrc/rocm_venv/bin/python3 -m scenarios.train_generator \
      --data data/setup_search/ohlcv_5y.pkl --epochs 50 \
      --out data/scenarios/neural_gen.pt [--device cuda]
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))


def _log_returns_from_pkl(path: Path):
    with open(path, "rb") as f:
        data = pickle.load(f)
    # DEFAULT_UNIVERSE order (SPY first, then tradeables) so the column count
    # and ordering match the neural model's D=17 space. Dropping SPY here was
    # a latent bug: training fed 16-dim windows into a D=17 model.
    from scenarios.spec import DEFAULT_UNIVERSE
    missing = [s for s in DEFAULT_UNIVERSE if s not in data]
    if missing:
        raise ValueError(f"archive missing universe symbols: {missing}")
    closes = {s: data[s]["close"].to_numpy(dtype=np.float64) for s in DEFAULT_UNIVERSE}
    n = min(len(c) for c in closes.values())
    X = np.column_stack([np.diff(np.log(c[:n])) for c in closes.values()])
    spy = closes["SPY"]
    spy_ma = pd_rolling(spy, 200)
    regime = np.where(spy > spy_ma, "bull", "bear")
    # X[t] = return into bar t+1: the conditioning regime must be the one in
    # effect at that bar, so align by dropping the first regime label.
    return X, regime[1:]


def pd_rolling(x: np.ndarray, w: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=np.float64)
    for i in range(w - 1, len(x)):
        out[i] = x[i - w + 1:i + 1].mean()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/setup_search/ohlcv_5y.pkl")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default="data/scenarios/neural_gen.pt")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    data_path = PROJECT / args.data
    if not data_path.exists():
        print(f"[train_generator] data not found: {data_path}", file=sys.stderr)
        raise SystemExit(1)

    from scenarios.neural import NeuralMarketGenerator
    X, regime = _log_returns_from_pkl(data_path)
    print(f"[train_generator] {X.shape} log-returns, regime split: "
          f"bull={int((regime=='bull').sum())} bear={int((regime=='bear').sum())}")

    gen = NeuralMarketGenerator(device=args.device)
    gen.train(X, regime, epochs=args.epochs, lr=args.lr)
    out = PROJECT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    gen.save(out)
    print(f"[train_generator] saved to {out}")

    from scenarios.evaluate import gate
    import scenarios.spec as spec_mod
    from scenarios import parametric
    real = pickle.load(open(data_path, "rb"))
    base = spec_mod.ScenarioSpec()
    worlds = [spec_mod.World(spec=base, data=parametric.generate(base), generated_by="neural")]
    g = gate(worlds, real)
    print(f"[train_generator] generator gate (post-train smoke): pass={g['pass']} checks={g['checks']}")


if __name__ == "__main__":
    main()
