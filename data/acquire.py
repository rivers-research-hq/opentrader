#!/usr/bin/env python3
"""Acquirers for the Data Accumulator — one per source.

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow
Each acquirer: fetch(name) -> {date_str: float} normalized series,
writes to the lake as parquet, returns (obs_start, obs_end, n_obs).
"""
from __future__ import annotations
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow

import json
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request

import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from data.accumulator import ACCUM, LAKE  # noqa: E402

# ── FRED ──────────────────────────────────────────────────────────────
FRED_SERIES = {
    "VIXCLS": "CBOE Volatility Index: VIX",
    "T10Y2Y": "10-Year minus 2-Year Treasury Constant Maturity",
    "BAA": "Moody's Seasoned Baa Corporate Bond Yield",
    "AAA": "Moody's Seasoned Aaa Corporate Bond Yield",
    "DTWEXBGS": "Nominal Broad U.S. Dollar Index",
    "DFF": "Effective Federal Funds Rate",
    "DCOILWTICO": "Crude Oil Prices: West Texas Intermediate",
    "PPIACO": "Producer Price Index by Commodity: All Commodities",
    "T10YIE": "10-Year Breakeven Inflation Rate",
}


# ── FRED ──────────────────────────────────────────────────────────────
import threading
_FRED_SEM = threading.Semaphore(2)  # FRED rate-limits concurrent requests


def _fred_key():
    from data.economics import _get_fred_key
    return _get_fred_key()


def acquire_fred(name: str, retries=3) -> dict:
    """Full-history FRED observations -> {date: value}. Rate-limited + retry."""
    key = _fred_key()
    url = ("https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={name}&api_key={key}&file_type=json&sort_order=asc")
    for attempt in range(retries):
        try:
            with _FRED_SEM:
                req = Request(url)
                with urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read().decode())
            out = {}
            for o in d.get("observations", []):
                v = o.get("value")
                if v not in (".", ""):
                    out[o["date"]] = float(v)
            time.sleep(0.5)
            return out
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"FRED {name} failed after {retries}: {e}") from e
    raise RuntimeError(f"FRED {name} failed")


# ── EIA ───────────────────────────────────────────────────────────────
EIA_SERIES = {
    "EIA_COAL_INV": ("coal", "inventories"),
    "EIA_NG_INV": ("naturalgas", "inventories"),
    "EIA_CRUDE_INV": ("petroleum", "crude/inventories"),
}


def _eia_key():
    return json.loads(
        (PROJECT / "config" / "alt_data_keys.json").read_text())["EIA_API_KEY"]


def acquire_eia(name: str) -> dict:
    """EIA v2 series -> {date: value} (weekly/monthly frequency)."""
    key = _eia_key()
    _, path = EIA_SERIES[name]
    url = (f"https://api.eia.gov/v2/{path}/data/?api_key={key}"
           "&frequency=weekly&data[]=value"
           "&sort[0][column]=period&sort[0][direction]=asc&length=5000")
    try:
        with urlopen(url, timeout=30) as resp:
            d = json.loads(resp.read().decode())
    except Exception as e:
        raise RuntimeError(f"EIA {name} failed: {e}")
    out = {}
    for row in d.get("response", {}).get("data", []):
        try:
            out[row["period"]] = float(row["value"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


# ── ETF (yfinance) ────────────────────────────────────────────────────
ETF_TICKERS = ["SPY", "QQQ", "IWM", "EEM", "TLT", "IEF", "SHY", "LQD",
               "HYG", "GLD", "DBC", "VNQ", "UUP", "FXE", "FXY", "EWJ", "TIP"]


def acquire_etf(name: str) -> dict:
    """ETF close history -> {date: close}."""
    import yfinance as yf
    df = yf.Ticker(name).history(period="max", auto_adjust=True)
    return {str(d.date()): float(row["Close"]) for d, row in df.iterrows()}


# ── SEC insider (local parquet) ───────────────────────────────────────
def acquire_insider(name: str) -> dict:
    """Daily Form-4 filing counts -> {date: count}. Local SEC parquet."""
    import pyarrow.parquet as pq
    t = pq.read_table(PROJECT / "odysseus/data/parquet_cache/stock_sec_filing.parquet"
                      if False else Path(
                          "/home/mrc/odysseus/data/parquet_cache/stock_sec_filing.parquet"),
                      columns=["form_type", "filing_date"])
    df = t.to_pandas()
    df = df[df["form_type"] == "4"]
    counts = df.groupby(pd.to_datetime(df["filing_date"]).dt.date).size()
    return {str(d): int(c) for d, c in counts.items()}


# ── dispatch ──────────────────────────────────────────────────────────
ACQUIRERS = {
    "fred": acquire_fred,
    "eia": acquire_eia,
    "etf": acquire_etf,
    "insider": acquire_insider,
}


def save_to_lake(name: str, series: dict) -> tuple:
    """{date: value} -> parquet in the lake. Returns (start, end, n)."""
    s = pd.Series(series, dtype=float).sort_index()
    s.index = pd.DatetimeIndex(s.index)
    out = LAKE / f"{name}.parquet"
    s.to_frame("value").to_parquet(out)
    return str(s.index.min().date()), str(s.index.max().date()), len(s)


if __name__ == "__main__":
    import sys
    src, name = sys.argv[1], sys.argv[2]
    fn = ACQUIRERS[src]
    data = fn(name)
    start, end, n = save_to_lake(name, data)
    print(f"{name}: {n} obs {start} -> {end}")
