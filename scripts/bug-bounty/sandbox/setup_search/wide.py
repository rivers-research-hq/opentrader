#!/usr/bin/env python3
"""Wide-universe set for the search loop's generalization gate.

Builds the aligned wide set (harness 511-symbol registry ∩ fullcross archive,
regime ON via SPY — same convention as rule_floor_honest.py) once and caches
it, so the loop can gate promotions on generalization without reloading the
1.15GB archive every run.

Data provenance: fullcross.pkl (Aug 6 fetch, 1999->2026-06-11, delisted names
retained). The two archives (ohlcv_*.pkl vs fullcross) disagree ~1.5-2% on
identical dates — reconciliation outstanding; this module is for selection
pressure, not for re-validating the 17-sym claims.
"""

import pickle
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "setup_search"
ARCHIVE = OUT / "fullcross.pkl"

WIDE_PERIOD_BARS = 1300  # ~5y daily — the honest generalization horizon


def _cache_path(period_bars: int) -> Path:
    return OUT / f"wide_aligned_{period_bars}b.pkl"


def build_wide_aligned(period_bars: int = WIDE_PERIOD_BARS, force: bool = False):
    """Aligned (closes, highs, lows, vols) over registry ∩ archive.

    SPY is included so the regime filter runs (run_backtest needs SPY in the
    aligned set; without it the gate silently runs regime-OFF).
    """
    cache = _cache_path(period_bars)
    if cache.exists() and not force:
        with open(cache, "rb") as f:
            return pickle.load(f)

    sys.path.insert(0, str(PROJECT))
    from mot.industry_map import get_universe_tickers
    from setup_search.data import REGIME_SYM, align

    with open(ARCHIVE, "rb") as f:
        raw = pickle.load(f)

    registry = set(get_universe_tickers()) | {REGIME_SYM}
    data = {}
    for sym in registry:
        v = raw.get(sym)
        if v is None or len(v["c"]) < period_bars:
            continue
        dates = pd.to_datetime(v["d"], unit="s")
        df = pd.DataFrame(
            {
                "close": v["c"][-period_bars:],
                "high": v["h"][-period_bars:],
                "low": v["l"][-period_bars:],
                "volume": v["v"][-period_bars:],
            },
            index=dates[-period_bars:],
        )
        df = df[~df.index.duplicated(keep="last")]
        data[sym] = df

    syms = [s for s in data if s != REGIME_SYM] + [REGIME_SYM]
    al = align(data, syms)
    with open(cache, "wb") as f:
        pickle.dump(al, f)
    n = len([s for s in al[0] if len(al[0][s]) > 0])
    print(f"[wide] cached {n} symbols x {period_bars} bars -> {cache.name}")
    return al


def wide_metrics(al, cfg: dict) -> dict:
    from setup_search.engine import run_backtest

    m = run_backtest(al, cfg)
    return {k: v for k, v in m.items() if k != "equity"}
