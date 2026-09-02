#!/usr/bin/env python3
"""Full-cross-section training source — the HuggingFace stock_market_dataset.

/home/mrc/odysseus/data/parquet_cache/stock_prices.parquet:
  35.4M daily OHLCV rows, 11,719 symbols, 1994-11 -> 2026-06, SPY present.

Same feature space as the validated rule (daily OHLCV), so the arena's
collect_from_data pipeline consumes it directly. MEMORY-LEAN BY DESIGN (the
pandas full-frame build OOM'd a 32GB box under load):

- build: one Arrow read -> dictionary-encoded symbol column -> single vectorized
  sort -> per-symbol slicing; caches float32 numpy arrays (~1GB pickle, not
  ~3GB of pandas frames);
- collect: samples N liquid symbols FIRST, reconstructs frames only for those,
  then runs collect_from_data — peak ~5GB, minutes of CPU.

Usage as an arena augmentation:
  rows, base = collect(sample=20000, n_symbols=200)
  -> pass rows as fit(extra_rows=...) so training broadens, measurement doesn't.
"""
from __future__ import annotations

import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

PARQUET = Path("/home/mrc/odysseus/data/parquet_cache/stock_prices.parquet")
CACHE = PROJECT / "data" / "setup_search" / "fullcross.pkl"

from arena.candidates import collect_from_data  # noqa: E402
from setup_search.core import clamp_config  # noqa: E402


def _frames(arr_dict: dict) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": arr_dict["o"], "high": arr_dict["h"], "low": arr_dict["l"],
         "close": arr_dict["c"], "volume": arr_dict["v"]},
        index=pd.to_datetime(arr_dict["d"]),
    )


def load_fullcross(min_bars=500, fresh=False) -> dict:
    """{symbol: {d,o,h,l,c,v: np.ndarray}} — float32 OHLCV + int64 dates,
    cached. Lean build: dictionary-encoded symbol column, one vectorized sort,
    per-symbol slicing (peak ~5-6GB, safe under an 8GiB cgroup cap)."""
    if not fresh and CACHE.exists():
        try:
            return pickle.load(open(CACHE, "rb"))
        except Exception:
            pass

    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    t0 = time.time()
    tbl = pq.read_table(str(PARQUET), columns=[
        "symbol", "report_date", "open", "high", "low", "close", "volume"])
    print(f"[fullcross] read {tbl.num_rows:,} rows in {time.time()-t0:.0f}s", flush=True)
    # one vectorized sort; then integer-encode the symbol column via
    # index_in (pc.cast -> dictionary is NOT implemented in this pyarrow)
    tbl = tbl.sort_by("symbol")
    syms = pc.unique(tbl.column("symbol")).to_pylist()  # sorted order (first-encounter after sort)
    codes = pc.index_in(tbl.column("symbol"), pc.unique(tbl.column("symbol"))).to_numpy()
    n = len(codes)
    boundaries = np.flatnonzero(np.diff(codes) != 0)
    starts = np.concatenate([[0], boundaries + 1])
    ends = np.concatenate([boundaries + 1, [n]])
    print(f"[fullcross] sorted; {len(syms)} symbols in {time.time()-t0:.0f}s", flush=True)

    out: dict = {}
    for i, (s0, s1) in enumerate(zip(starts, ends)):
        sub = tbl.slice(int(s0), int(s1 - s0))
        df = sub.to_pandas()
        if len(df) >= min_bars:
            df = df.sort_values("report_date").drop_duplicates(subset="report_date")
            out[syms[i]] = {
                "d": df["report_date"].to_numpy(),
                "o": df["open"].to_numpy(np.float32),
                "h": df["high"].to_numpy(np.float32),
                "l": df["low"].to_numpy(np.float32),
                "c": df["close"].to_numpy(np.float32),
                "v": df["volume"].to_numpy(np.float32),
            }
    del tbl
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(out, open(CACHE, "wb"))
    print(f"[fullcross] cached {len(out)} symbols in {time.time()-t0:.0f}s "
          f"({CACHE.stat().st_size/1e6:.0f}MB)", flush=True)
    return out


def collect(sample=None, n_symbols=200, min_bars=500, fresh=False, seed=7,
            cfg_path=PROJECT / "data/setup_search/best.json") -> tuple:
    """Arena candidate rows from a sampled subset of the full cross-section
    (SPY regime marker from the dataset itself). Lean: symbols sampled BEFORE
    frame reconstruction or feature building."""
    base = clamp_config(json.loads(cfg_path.read_text())["config"])
    cache = load_fullcross(min_bars=min_bars, fresh=fresh)
    syms = [s for s in cache if s != "SPY"]
    rng = np.random.RandomState(seed)
    if n_symbols and len(syms) > n_symbols:
        syms = list(rng.choice(syms, size=n_symbols, replace=False))
    if "SPY" not in cache:
        print("[fullcross] WARNING: SPY missing; regime proxy = cross-sectional mean")
        mkt = np.nanmean(np.stack([cache[s]["c"] for s in syms[:50]]), axis=0)
        cache["SPY"] = {"d": cache[syms[0]]["d"], "o": mkt, "h": mkt, "l": mkt,
                        "c": mkt, "v": np.zeros_like(mkt)}
    data = {"SPY": _frames(cache["SPY"])}
    for s in syms:
        data[s] = _frames(cache[s])
    rows, base = collect_from_data(data, base)
    if sample and len(rows) > sample:
        idx = rng.permutation(len(rows))[:sample]
        rows = [rows[i] for i in idx]
    return rows, base


if __name__ == "__main__":
    t0 = time.time()
    cache = load_fullcross(min_bars=500)
    print(f"[fullcross] {len(cache)} symbols cached in {time.time()-t0:.0f}s")
    rows, base = collect(sample=5000, n_symbols=100)
    print(f"[fullcross] sample collect: {len(rows)} rows in {time.time()-t0:.0f}s")
    print(f"[fullcross] sample syms: {sorted({r['sym'] for r in rows})[:5]}")
