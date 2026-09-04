#!/usr/bin/env python3
"""US 1m value head — MoT expert #1 (market-scoped, modular).

Trains a torch value head on US 1-minute OHLCV (HuggingFace mito0o852/OHLCV-1m)
for the liquid universe. State = the rule engine's engineered features at bar t;
reward = 240-bar (4h) forward return. Loosened data-gen screen (score >= -0.5)
so the value function sees the full state space. Windows: TRAIN Dec-2025,
TESTS Jan-2026 + Mar-2026 (held out). Autonomy bar: kept-mean - all-mean >= +1%
on BOTH held-out months.

This is the pattern for a future Mixture of Traders: one small, per-market
model trained on that market's data, gated independently.
"""

import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "research_gate"
DATA = Path("/tmp/opencode")
FORWARD = 240  # 1m bars = 4h forward
GEN_SCORE_MIN = -0.5
UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "JPM",
            "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX", "SPY"]
TRAIN_MONTHS = ["2025-12"]
TEST_MONTHS = [("2026-01", "Jan-2026"), ("2026-03", "Mar-2026")]
VAL_FRAC = 0.15
SEED = 29
FEAT_COLS = ["mom", "rev", "rsi", "brk", "z", "ma_dist", "vol_spike", "vol_level", "momfilt"]
FRED_SERIES = {"FF": "DFF", "T10": "DGS10", "CPI": "CPIAUCSL"}


def load_fred():
    """Historical macro state: date-stamped FRED series -> per-bar value (ffill)."""
    import json as _json
    import urllib.request as _ur

    out = {}
    try:
        from data.economics import _get_fred_key
        key = _get_fred_key()
        if not key:
            print("[v1m] no FRED key")
            return out
        for k, sid in FRED_SERIES.items():
            url = (f"https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={sid}&api_key={key}&file_type=json")
            with _ur.urlopen(url, timeout=20) as r:
                data = _json.loads(r.read().decode())
            obs = [(pd.Timestamp(o["date"], tz="UTC"), float(o["value"]))
                   for o in data.get("observations", [])
                   if o.get("value") not in ("", ".")]
            if obs:
                out[k] = pd.Series(dict(obs)).sort_index()
    except Exception as e:
        print(f"[v1m] FRED load skipped: {e}")
    return out


def load_month(month: str):
    df = pd.read_parquet(DATA / f"ohlcv_{month}_filt.parquet")
    closes, highs, lows, vols = {}, {}, {}, {}
    for sym, g in df.groupby("ticker"):
        g = g.sort_values("timestamp").drop_duplicates("timestamp")
        idx = g["timestamp"]
        closes[sym] = pd.Series(g["close"].values.astype(float), index=idx)
        highs[sym] = pd.Series(g["high"].values.astype(float), index=idx)
        lows[sym] = pd.Series(g["low"].values.astype(float), index=idx)
        vols[sym] = pd.Series(g["volume"].values.astype(float), index=idx)
    return closes, highs, lows, vols


def load_vix():
    """Daily VIX (market-fear/sentiment proxy) -> daily Series."""
    try:
        import yfinance as yf
        v = yf.download("^VIX", period="2y", interval="1d", auto_adjust=True, progress=False)
        close = v["Close"]
        s = close["^VIX"] if hasattr(close, "columns") and "^VIX" in close else close
        s = s.dropna()
        s.index = pd.to_datetime(s.index, utc=True)
        return s
    except Exception as e:
        print(f"[v1m] VIX load skipped: {e}")
        return None


def breadth_series(closes, window=50):
    """Market breadth: fraction of the universe above its `window`-bar MA."""
    master = next(iter(closes.values())).index
    above = {}
    for sym, c in closes.items():
        ma = c.rolling(window, min_periods=window).mean()
        above[sym] = (c > ma).reindex(master)
    frame = pd.DataFrame(above)
    return frame.mean(axis=1, skipna=True)


def collect(closes, highs, lows, vols, cfg, fred=None, vix=None, breadth=None):
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    # cross-sectional relative strength: rank each symbol's momentum + RSI
    # among the universe at each bar (a genuinely different state dimension)
    mom_frame = pd.DataFrame({s: feat[s]["mom"] for s in closes if s != REGIME_SYM})
    rsi_frame = pd.DataFrame({s: feat[s]["rsi"] for s in closes if s != REGIME_SYM})
    mom_rank = mom_frame.rank(axis=1, pct=True)
    rsi_rank = rsi_frame.rank(axis=1, pct=True)
    w = cfg
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        # vectorized composite score (rank=0)
        score = (w["w_mom"] * f["mom"] + w["w_rev"] * f["rev"] + w["w_rsi"] * f["rsi"]
                 + w["w_brk"] * f["brk"] + w["w_z"] * f["z"])
        vals = f[FEAT_COLS].values.astype(np.float32)
        np.nan_to_num(vals, copy=False)
        fwd = (c.shift(-FORWARD) / c - 1.0).values
        sc = score.values
        mr = mom_rank[sym].reindex(c.index).values
        rr = rsi_rank[sym].reindex(c.index).values
        fred_arr = {}
        if fred:
            for key, s in fred.items():
                fred_arr[key] = s.reindex(c.index, method="ffill").values
        vix_arr = None
        if vix is not None:
            vix_arr = vix.reindex(c.index.normalize(), method="ffill").values
        breadth_arr = None
        if breadth is not None:
            breadth_arr = breadth.reindex(c.index, method="ffill").values
        n = len(c) - FORWARD
        spy_arr = None
        if spy is not None and spy_ma200 is not None:
            spy_arr = (spy / spy_ma200).reindex(c.index).values
        for t in range(n):
            s = sc[t]
            if s != s or s < GEN_SCORE_MIN:
                continue
            spy_ratio = 1.0
            if spy_arr is not None and spy_arr[t] == spy_arr[t]:
                spy_ratio = float(spy_arr[t])
            extra = [float(mr[t]) if mr[t] == mr[t] else 0.5,
                     float(rr[t]) if rr[t] == rr[t] else 0.5]
            for key in FRED_SERIES:
                vv = fred_arr.get(key)
                extra.append(float(vv[t]) if vv is not None and vv[t] == vv[t] else 0.0)
            extra.append(float(vix_arr[t]) if vix_arr is not None and vix_arr[t] == vix_arr[t] else 20.0)
            extra.append(float(breadth_arr[t]) if breadth_arr is not None and breadth_arr[t] == breadth_arr[t] else 0.5)
            v = np.concatenate([vals[t], [s, spy_ratio], extra])
            rows.append({
                "sym": sym, "ts": c.index[t], "x": v.astype(np.float32),
                "fwd": float(fwd[t]),
            })
    return rows


class ValueMLP(nn.Module):
    def __init__(self, d_in):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d_in, 64), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(64, 32), nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    fred = load_fred()
    vix = load_vix()
    print(f"[v1m] FRED macro features: {list(fred.keys())} | VIX: {vix is not None}")

    train_rows = []
    for m in TRAIN_MONTHS:
        m_closes = load_month(m)[0]
        train_rows += collect(*load_month(m), base, fred, vix, breadth_series(m_closes))
    test_sets = []
    for m, lbl in TEST_MONTHS:
        m_closes = load_month(m)[0]
        test_sets.append((lbl, collect(*load_month(m), base, fred, vix, breadth_series(m_closes))))
    print(f"[v1m] train: {len(train_rows)} (Dec-25) | tests: "
          + ", ".join(f"{lbl}={len(r)}" for lbl, r in test_sets))

    n_val = max(1, int(len(train_rows) * VAL_FRAC))
    trn, val = train_rows[: len(train_rows) - n_val], train_rows[-n_val:]
    trn = [r for r in trn if r["fwd"] == r["fwd"]]
    val = [r for r in val if r["fwd"] == r["fwd"]]
    if not trn:
        raise SystemExit("no clean train rows")
    X = np.stack([r["x"] for r in trn])
    y = np.array([r["fwd"] for r in trn], dtype=np.float32)
    mean, std = X.mean(0), X.std(0)
    Xz = (X - mean) / (std + 1e-8)
    Xv = torch.tensor((np.stack([r["x"] for r in val]) - mean) / (std + 1e-8))
    yv = torch.tensor(np.array([r["fwd"] for r in val], dtype=np.float32))

    model = ValueMLP(X.shape[1])
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.MSELoss()
    Xt, yt = torch.tensor(Xz), torch.tensor(y)
    best_loss, best_state, patience = 1e9, None, 0
    for epoch in range(150):
        model.train()
        opt.zero_grad()
        loss = lossf(model(Xt), yt)
        loss.backward()
        opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(lossf(model(Xv), yv))
        if vl < best_loss:
            best_loss, best_state, patience = vl, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            patience += 1
            if patience >= 12:
                break
    model.load_state_dict(best_state if best_state is not None else model.state_dict())
    model.eval()

    def preds(rows):
        return np.array([float(model(torch.tensor((r["x"] - mean) / (std + 1e-8)).unsqueeze(0)).item())
                         for r in rows])

    vp = preds(val)
    best_theta, best_d = 0.0, -1e9
    for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
        kept = [r["fwd"] for r, p in zip(val, vp) if p >= q]
        allm = statistics.mean(r["fwd"] for r in val)
        km = statistics.mean(kept) if kept else 0.0
        d = km - allm
        if d > best_d:
            best_d, best_theta = d, float(q)
    print(f"[v1m] val MSE {best_loss:.6f}; theta={best_theta:+.4f} (val discrim {best_d:+.2%})")

    results = []
    for label, rows in test_sets:
        wp = preds(rows)
        kept = [r["fwd"] for r, p in zip(rows, wp) if p >= best_theta]
        all_m = statistics.mean(r["fwd"] for r in rows)
        kept_m = statistics.mean(kept) if kept else 0.0
        results.append({"window": label, "n": len(rows), "kept": len(kept),
                        "kept_mean": kept_m, "all_mean": all_m, "margin": kept_m - all_m})
        print(f"[v1m] {label}: n={len(rows)} kept={len(kept)} "
              f"kept_m={kept_m:+.3%} all_m={all_m:+.3%} margin={kept_m-all_m:+.3%}")

    passed = [r for r in results if r["margin"] >= 0.01]
    pass_gate = len(passed) == len(results)
    print(f"\n=== US 1M VALUE HEAD GATE ===")
    print(f"  windows passing: {len(passed)}/{len(results)} -> "
          f"{'PASS' if pass_gate else 'FAIL (stays gated; rules primary)'}")

    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({"state": model.state_dict(), "d_in": X.shape[1], "mean": mean,
                "std": std}, OUT / "value_head_1m.pt")
    (OUT / "value_head_1m_report.json").write_text(json.dumps({
        "market": "US 1m", "universe": UNIVERSE, "forward_bars": FORWARD,
        "n_train": len(trn), "results": results, "theta": best_theta,
        "pass": pass_gate}, indent=1, default=str))
    print(f"-> {OUT / 'value_head_1m.pt'}")


if __name__ == "__main__":
    main()
