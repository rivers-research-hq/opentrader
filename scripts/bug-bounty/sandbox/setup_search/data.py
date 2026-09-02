#!/usr/bin/env python3
"""Data layer for the setup-search loop: fetch + cache OHLCV for a small
sector-diversified universe using yfinance, with a synthetic fallback so the
loop never stalls if the network is down overnight."""

import math
import pickle
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT / "data" / "setup_search"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UNIVERSE = [
    "SPY",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "AMZN",
    "GOOGL",
    "META",
    "JPM",
    "XOM",
    "JNJ",
    "PG",
    "KO",
    "DIS",
    "CSCO",
    "WMT",
    "NFLX",
]
REGIME_SYM = "SPY"
SYM_FEES = 0.35


def _synthetic_data(days: int = 500, seed: int = 7) -> dict:
    rng = random.Random(seed)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    idx = pd.date_range(start, periods=days, freq="B", tz="UTC")
    out = {}
    for i, sym in enumerate(UNIVERSE):
        rng.seed(seed + i)
        mu = rng.uniform(0.0001, 0.0015)
        sigma = rng.uniform(0.01, 0.025)
        rets = rng.gauss(0, 1) * sigma
        base = rng.uniform(20, 400)
        px = base * np.exp(np.cumsum(np.array([mu] * days) + rets))
        drift = rng.uniform(0.3, 1.0)
        if rng.random() < 0.4:
            px = px * (1 + drift * np.sin(np.arange(days) / rng.uniform(8, 25)))
        df = pd.DataFrame(
            {
                "open": px,
                "close": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "volume": np.full(days, 1e6),
            },
            index=idx,
        )
        out[sym] = df
    return out


def _fetch_yfinance(period: str) -> dict:
    import yfinance as yf

    out = {}
    for sym in UNIVERSE:
        try:
            sub = yf.download(
                sym,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if sub is None or len(sub) < 200:
                continue
            sub = sub.dropna()
            if isinstance(sub.columns, pd.MultiIndex):
                ticker_level = 1 if "Ticker" in sub.columns.names else 0
                if sym not in sub.columns.get_level_values(ticker_level):
                    continue

                def _g(price):
                    try:
                        return sub[(price, sym)]
                    except (KeyError, IndexError):
                        try:
                            return sub[(price.capitalize(), sym)]
                        except (KeyError, IndexError):
                            return None

                close = _g("Close")
                if close is None:
                    close = _g("close")
                high = _g("High")
                if high is None:
                    high = _g("high")
                low = _g("Low")
                if low is None:
                    low = _g("low")
                open_ = _g("Open")
                if open_ is None:
                    open_ = _g("open")
                vol = _g("Volume")
                if vol is None:
                    vol = _g("volume")
                if close is None:
                    continue
                df = pd.DataFrame(
                    {
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": vol,
                    }
                )
            else:
                cols = {c.lower(): c for c in sub.columns}
                if "close" not in cols:
                    continue
                df = pd.DataFrame(
                    {
                        "open": sub[cols["open"]],
                        "high": sub[cols["high"]],
                        "low": sub[cols["low"]],
                        "close": sub[cols["close"]],
                        "volume": sub[cols["volume"]],
                    }
                )
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")
            df = df.astype(float)
            df.index.name = "date"
            out[sym] = df
        except Exception as e:
            print(f"[data] {sym} failed: {e}")
    return out


def load_ohlcv(period: str = "2y", force: bool = False, allow_synthetic: bool = True) -> dict:
    cache = OUT_DIR / f"ohlcv_{period}.pkl"
    if cache.exists() and not force:
        try:
            with open(cache, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    data = {}
    for attempt in (period, "1y"):
        try:
            data = _fetch_yfinance(attempt)
            if len(data) >= 8:
                break
        except Exception as e:
            print(f"[data] yfinance {attempt} failed: {e}")
            data = {}

    if len(data) >= 8:
        with open(cache, "wb") as f:
            pickle.dump(data, f)
        print(f"[data] cached {len(data)} symbols to {cache}")
    elif allow_synthetic:
        data = _synthetic_data()
        print("[data] WARNING: using SYNTHETIC data (network unavailable)")
    return data


def align(data: dict, syms: list) -> tuple:
    master = data[REGIME_SYM].index
    closes, highs, lows, vols = {}, {}, {}, {}
    for s in syms:
        if s not in data:
            continue
        df = data[s]
        c = df["close"].reindex(master).ffill(limit=5).dropna()
        if len(c) < 200:
            continue
        closes[s] = c
        highs[s] = df["high"].reindex(c.index).ffill(limit=5)
        lows[s] = df["low"].reindex(c.index).ffill(limit=5)
        vols[s] = df["volume"].reindex(c.index).ffill(limit=5)
    return closes, highs, lows, vols


def slice_aligned(al: tuple, i0: int, i1: int) -> tuple:
    closes, highs, lows, vols = al
    idx = next(iter(closes.values())).index
    lo_date, hi_date = idx[i0], idx[i1 - 1]

    def _slc(d):
        return {
            s: c.loc[(c.index >= lo_date) & (c.index <= hi_date)]
            for s, c in d.items()
        }

    return (_slc(closes), _slc(highs), _slc(lows), _slc(vols))
