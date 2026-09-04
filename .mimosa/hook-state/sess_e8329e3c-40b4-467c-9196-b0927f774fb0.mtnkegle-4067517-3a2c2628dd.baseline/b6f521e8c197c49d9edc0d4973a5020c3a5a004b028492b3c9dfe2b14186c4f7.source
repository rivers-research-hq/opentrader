"""International candidate rows for the arena — the 'international' expert's data.

Universe (verified 5y coverage, research: docs/research/expert-data-sources.md):
  ^N225 ^FTSE ^GDAXI ^HSI ^GSPC(alias 'SPY' = regime marker) ^VIX EEM EFA
  EURUSD=X USDJPY=X GC=F CL=F
yfinance fetch (5y daily), cached to data/setup_search/international_ohlcv_5y.pkl
with a 24h TTL and graceful network degradation. Rows follow the EXACT arena
contract (bar/sym/date/x/fwd/feats/score/regime_up/close/close_series) so the
opponent bots, war referee, GRPO refine and multiverse gate work unchanged —
same 11-dim feature vector, different universe.
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import numpy as np

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, align
from setup_search.engine import _features, _score_at

from arena.candidates import FEAT_COLS, FORWARD

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "setup_search" / "international_ohlcv_5y.pkl"
CACHE_TTL_S = 24 * 3600
GEN_SCORE_MIN = -0.5

INTERNATIONAL = [
    "^N225", "^FTSE", "^GDAXI", "^HSI", "^GSPC", "^VIX",
    "EEM", "EFA", "EURUSD=X", "USDJPY=X", "GC=F", "CL=F",
]


def load_international(period="5y", fresh=False) -> dict:
    """dict {symbol: OHLCV DataFrame}, with ^GSPC renamed to the arena's regime
    marker REGIME_SYM ('SPY'). Cached; refetches if stale or fresh=True."""
    if not fresh and CACHE.exists():
        try:
            ck = pickle.load(open(CACHE, "rb"))
            if time.time() - ck.get("ts", 0) < CACHE_TTL_S:
                return ck.get("data")
        except Exception:
            pass
    import yfinance as yf

    raw = yf.download(INTERNATIONAL, period="5y", interval="1d",
                      auto_adjust=True, progress=False, group_by="ticker")
    data = {}
    for t in INTERNATIONAL:
        try:
            df = raw[t].dropna(how="all")
            df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            df.columns = ["open", "high", "low", "close", "volume"]
            if len(df) > 250:
                key = REGIME_SYM if t == "^GSPC" else t
                data[key] = df
        except Exception:
            continue
    if len(data) >= 6:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE, "wb") as f:
            pickle.dump({"ts": time.time(), "data": data}, f)
        print(f"[candidates_international] cached {len(data)} international symbols")
    else:
        print("[candidates_international] WARNING: too few international symbols fetched")
    return data


def collect(period="5y", cfg_path=PROJECT / "data/setup_search/best.json",
            fresh=False) -> tuple:
    """Rows in the arena contract from the international universe."""
    base = clamp_config(json.loads(cfg_path.read_text())["config"])
    data = load_international(period, fresh=fresh)
    al = align(data, [s for s in data if s != REGIME_SYM])
    closes, highs, lows, vols = al
    feat = _features(closes, highs, lows, vols, base)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if base["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(base["regime_window"]), min_periods=10).mean()
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    master = next(iter(closes.values())).index
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        for t in range(len(c)):
            if t + FORWARD >= len(c):
                break
            date = c.index[t]
            if date not in master:
                continue
            s = float(_score_at({sym: f.loc[date]}, base, {sym: 0.0})[sym])
            if s != s or s < GEN_SCORE_MIN:
                continue
            regime_up = True
            if spy_ma is not None and date in spy_ma.index:
                regime_up = float(spy[date]) > float(spy_ma[date])
            v = [0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k])
                 for k in FEAT_COLS]
            spy_ratio = 1.0
            if spy is not None and date in spy_ma200.index and spy_ma200[date]:
                spy_ratio = float(spy[date] / spy_ma200[date])
            v += [s, spy_ratio]
            rows.append({
                "bar": master.get_loc(date),
                "sym": sym,
                "date": date,
                "x": np.array(v, dtype=np.float32),
                "fwd": float(c.loc[c.index[t + FORWARD]]) / float(c.iloc[t]) - 1.0,
                "feats": {k: (0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k]))
                          for k in FEAT_COLS},
                "score": s,
                "regime_up": regime_up,
                "close": float(c.iloc[t]),
                "close_series": c,
            })
    return rows, base


if __name__ == "__main__":
    rows, cfg = collect("5y")
    print(f"international rows: {len(rows)}, x-dim: {rows[0]['x'].shape[0]}")
    print(f"symbols: {sorted({r['sym'] for r in rows})}")
    print(f"bar range: {min(r['bar'] for r in rows)}-{max(r['bar'] for r in rows)}")
