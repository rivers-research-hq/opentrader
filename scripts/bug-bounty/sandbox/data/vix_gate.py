#!/usr/bin/env python3
"""VIX day-regime gate (wayfinder map, the exogenous layer).

Trade the score-tail/rule floor only on days when trailing VIX z-score >=
threshold. ~~"Validated: +12.47%/day vs +4.13% always (98.6th pctile
date-clustered bootstrap...)"~~ FALSIFIED 2026-08-12: replay on the same 503
trades measures -2.42%/trade (vix_high) vs -2.80%/trade (calm) — both
losing; the gate splits losing trades into buckets, it does not create an
edge. See ~/overnight-reports/opentrader-2026-08-12-session.md.

FAILURE MODE IS FAIL-CLOSED, BY DESIGN: any error path (fetch failure, empty
cache, warmup, non-finite z) yields z=0.0 → allow_trading() False → NO
trades. A degraded gate must never trade blind.

Causal, no lookahead: z-score uses trailing 250 bars of daily VIXCLS (FRED),
as-of ffill. Fetched lazily and cached.

Usage:
    gate = VixGate(threshold=0.5)
    if gate.allow_trading():   # True when VIX z >= threshold (high-vol days)
        ...BUY...
"""
from __future__ import annotations

import json
import os
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
CACHE = PROJECT / "data" / "vix_daily.pkl"
Z_WINDOW = 250
DEFAULT_THRESHOLD = 0.5


class VixGate:
    """Daily VIX-regime gate for the rule-primary path."""

    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 z_window: int = Z_WINDOW, cache_path: Path = CACHE):
        self.threshold = threshold
        self.z_window = z_window
        self.cache_path = cache_path
        self._vix: pd.Series | None = None

    # -- data -----------------------------------------------------------------
    def _load_vix(self) -> pd.Series:
        """Daily VIXCLS (FRED), cached. Falls back to cache-only on fetch fail."""
        if self._vix is not None:
            return self._vix
        if self.cache_path.exists():
            try:
                self._vix = pickle.load(open(self.cache_path, "rb"))
                return self._vix
            except Exception:
                pass
        try:
            from data.economics import _get_fred_key
            key = _get_fred_key()
            url = ("https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id=VIXCLS&api_key={key}&file_type=json"
                   "&sort_order=asc")
            req = Request(url)
            req.add_header("User-Agent", "OpenTrader/1.0")
            with urlopen(req, timeout=30) as resp:
                d = json.loads(resp.read().decode())
            vals = {o["date"]: float(o["value"]) for o in d["observations"]
                    if o["value"] not in (".", "")}
            s = pd.Series(vals, dtype=float).sort_index()
            s.index = pd.DatetimeIndex(s.index)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            pickle.dump(s, open(self.cache_path, "wb"))
            self._vix = s
            return s
        except Exception as e:
            # degraded: FAIL CLOSED — empty series => vix_z()=0.0 => allow
            # trading = False. The harness must not trade blind on a dead gate.
            print(f"[vixgate] fetch failed ({e}); gate CLOSED (no trades)", flush=True)
            self._vix = pd.Series(dtype=float)
            return self._vix

    # -- signal ---------------------------------------------------------------
    def vix_z(self, date=None) -> float:
        """Trailing-250 z-score of VIXCLS as of `date` (default: latest).

        Fail-closed: returns 0.0 (below any positive threshold => no trades)
        on every data-availability or degeneracy failure.
        """
        s = self._load_vix()
        if s.empty:
            return 0.0  # no data -> gate CLOSED
        if date is None:
            date = s.index[-1]
        date = pd.Timestamp(date)
        hist = s[s.index <= date]
        if len(hist) < 60:
            return 0.0  # warmup -> no gate
        m = hist.rolling(self.z_window).mean().iloc[-1]
        sd = hist.rolling(self.z_window).std().iloc[-1]
        v = float(hist.iloc[-1])
        if not (np.isfinite(m) and np.isfinite(sd) and sd > 0):
            return 0.0
        return (v - m) / sd

    def regime(self, date=None) -> str:
        z = self.vix_z(date)
        return "high-vol" if z >= self.threshold else "calm"

    def allow_trading(self, date=None) -> bool:
        """High-vol days (VIX z >= threshold) are the good regime."""
        return self.vix_z(date) >= self.threshold

    def describe(self, date=None) -> str:
        z = self.vix_z(date)
        return (f"vix_z={z:+.2f} regime={self.regime(date)} "
                f"(threshold={self.threshold})")


if __name__ == "__main__":
    g = VixGate()
    print(f"today: {g.describe()}")
    print(f"allow_trading: {g.allow_trading()}")
    # sanity over history
    s = g._load_vix()
    print(f"vix cache: {len(s)} points {s.index.min().date()} -> {s.index.max().date()}")
