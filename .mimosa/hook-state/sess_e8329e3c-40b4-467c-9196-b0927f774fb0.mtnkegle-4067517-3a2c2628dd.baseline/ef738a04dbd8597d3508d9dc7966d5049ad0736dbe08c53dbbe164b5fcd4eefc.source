"""Macro-augmented candidate rows for the arena — the 'macro' expert's data.

Reuses setup_search.value_head_1m's feature plan (FRED DFF/DGS10/CPIAUCSL,
VIX, market breadth, cross-sectional mom/RSI ranks) but emits rows in the SAME
contract as arena/candidates.py (bar/sym/date/x/fwd/feats/score/regime_up/
close/close_series), so the opponent bots, the war referee, the GRPO refine and
the multiverse gate all work unchanged. Feature vector: 9 OHLCV feats + score +
spy_ratio + mom_rank + rsi_rank + 3 FRED + VIX + breadth = 18 dims.

FRED/VIX are cached to data/setup_search/macro_series.pkl and refreshed at most
once per day, so the arena never depends on live network at iteration time.
"""
from __future__ import annotations

import json
import pickle
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features

from arena.candidates import FEAT_COLS, FORWARD

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "setup_search" / "macro_series.pkl"
CACHE_TTL_S = 24 * 3600
GEN_SCORE_MIN = -0.5


def _load_cached() -> dict | None:
    if CACHE.exists():
        try:
            ck = pickle.load(open(CACHE, "rb"))
            if time.time() - ck.get("ts", 0) < CACHE_TTL_S:
                return ck.get("data")
        except Exception:
            pass
    return None


def _save_cached(data: dict):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump({"ts": time.time(), "data": data}, f)


def macro_state(fresh: bool = False) -> dict:
    """fred (dict of Series), vix (Series), breadth (Series) — cached."""
    if not fresh:
        cached = _load_cached()
        if cached is not None:
            return cached
    from setup_search.value_head_1m import load_fred

    fred = load_fred()
    vix = _load_vix_5y()
    data = {"fred": fred, "vix": vix}
    if fred and vix is not None:
        _save_cached(data)
    return data


def _load_vix_5y():
    """Daily ^VIX over the FULL archive span (value_head_1m's load_vix only
    fetches 2y, which left the first 3y of macro rows on the fallback 20.0)."""
    import urllib.request
    import json as _json
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=5y&interval=1d"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            payload = _json.loads(r.read().decode())
        ts = payload["chart"]["result"][0]["timestamp"]
        close = payload["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        df = pd.DataFrame({"close": close}, index=pd.to_datetime(ts, unit="s", utc=True).normalize())
        return df["close"].dropna()
    except Exception as e:
        print(f"[candidates_macro] VIX fetch failed ({e}); using fallback")
        return None


def collect(period="5y", cfg_path=PROJECT / "data/setup_search/best.json",
            fresh: bool = False, warn_no_macro: bool = True):
    """Rows in the arena contract, with 18-dim macro-augmented x.

    If FRED/VIX cannot be fetched and no cache exists, degrades to the plain
    11-dim momentum features (macro columns zeroed) and prints a warning — the
    iteration still runs, but the 'macro' expert's edge is not yet present.
    """
    base = clamp_config(json.loads(cfg_path.read_text())["config"])
    data = load_ohlcv(period)
    al = align(data, [s for s in data if s != REGIME_SYM])
    closes, highs, lows, vols = al
    feat = _features(closes, highs, lows, vols, base)
    spy = closes.get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean() if spy is not None else None
    master = next(iter(closes.values())).index

    st = macro_state(fresh=fresh)
    fred = st.get("fred")
    vix = st.get("vix")
    from setup_search.value_head_1m import breadth_series
    breadth = breadth_series(closes, window=50) if fred and vix is not None else None
    if fred is None or vix is None:
        if warn_no_macro:
            print("[candidates_macro] WARNING: no FRED/VIX available; macro columns zeroed")

    mom_frame = pd.DataFrame({s: feat[s]["mom"] for s in closes if s != REGIME_SYM})
    rsi_frame = pd.DataFrame({s: feat[s]["rsi"] for s in closes if s != REGIME_SYM})
    mom_rank = mom_frame.rank(axis=1, pct=True)
    rsi_rank = rsi_frame.rank(axis=1, pct=True)
    w = base

    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
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
        spy_arr = None
        if spy is not None and spy_ma200 is not None:
            spy_arr = (spy / spy_ma200).reindex(c.index).values
        n = len(c) - FORWARD
        for t in range(n):
            s = sc[t]
            if s != s or s < GEN_SCORE_MIN:
                continue
            date = c.index[t]
            spy_ratio = 1.0
            if spy_arr is not None and spy_arr[t] == spy_arr[t]:
                spy_ratio = float(spy_arr[t])
            extra = [float(mr[t]) if mr[t] == mr[t] else 0.5,
                     float(rr[t]) if rr[t] == rr[t] else 0.5]
            for key in ("FF", "T10", "CPI"):
                vv = fred_arr.get(key)
                extra.append(float(vv[t]) if vv is not None and vv[t] == vv[t] else 0.0)
            extra.append(float(vix_arr[t]) if vix_arr is not None and vix_arr[t] == vix_arr[t] else 20.0)
            extra.append(float(breadth_arr[t]) if breadth_arr is not None and breadth_arr[t] == breadth_arr[t] else 0.5)
            v = np.concatenate([vals[t], [s, spy_ratio], extra])
            rows.append({
                "bar": master.get_loc(date) if date in master else -1,
                "sym": sym,
                "date": date,
                "x": v.astype(np.float32),
                "fwd": float(fwd[t]),
                "feats": {k: (0.0 if f.loc[date][k] != f.loc[date][k] else float(f.loc[date][k]))
                          for k in FEAT_COLS},
                "score": s,
                "regime_up": bool(spy is not None and spy[date] > spy_ma200[date]) if (spy is not None and spy_ma200 is not None and date in spy_ma200.index) else True,
                "close": float(c.iloc[t]),
                "close_series": c,
            })
    rows = [r for r in rows if r["bar"] >= 0]
    return rows, base


if __name__ == "__main__":
    rows, cfg = collect("5y")
    print(f"macro rows: {len(rows)}, x-dim: {rows[0]['x'].shape[0]} (expect 18)")
    print(f"bar range: {min(r['bar'] for r in rows)}-{max(r['bar'] for r in rows)}")
