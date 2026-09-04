#!/usr/bin/env python3
"""World Bank Open Data adapter (api.worldbank.org / data360).

HONEST SCOPE: World Bank indicators are predominantly ANNUAL (GDP growth,
inflation) with ~1yr publication lags. They CANNOT drive daily-bar regime
gates (FRED/VIX/breadth remain the daily signals). What WB uniquely adds:

  1. COUNTRY BREADTH — growth/inflation for markets FRED doesn't cover
     (China, EM, Europe) — a global-growth-regime context layer.
  2. CROSS-CHECK / validation of the FRED macro state.
  3. The user's in-house economic calendar can schedule when WB releases
     land (calendar-driven, not daily-driven).

This module mirrors data/economics.py: fetch + cache + provenance. Returns
a dict {series_name: pd.Series(datetime-indexed)} aligned/ffill'able to the
strategy master index. Usage is REGIME CONTEXT, not a per-bar gate.

Series mapped (World Bank indicator codes, US + peers):
  GDP growth (annual %)          NY.GDP.MKTP.KD.ZG
  Inflation, consumer prices     FP.CPI.TOTL.ZG
  Real interest rate             FR.INR.RINR
  Trade balance % of GDP         NE.RSB.GNFS.ZS
  Unemployment (ILO)             SL.UEM.TOTL.ZS
  FDI net inflows % of GDP       BX.KLT.DINV.WD.GD.ZS

Countries: US + China + Euro-zone aggregate via key peers (DE, FR, IT, ES),
plus EM representative (BR, IN, ID, MX, ZA).
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
urlopen = guarded_urlopen  # hardening shadow

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT / "data" / "world_bank_cache.json"
CACHE_MAX_AGE = 3600 * 24 * 7  # 7 days (annual data, no need for faster)

SERIES = {
    "gdp_growth": "NY.GDP.MKTP.KD.ZG",
    "inflation_cpi": "FP.CPI.TOTL.ZG",
    "real_interest": "FR.INR.RINR",
    "trade_balance_pct_gdp": "NE.RSB.GNFS.ZS",
    "unemployment": "SL.UEM.TOTL.ZS",
    "fdi_net_inflow_pct_gdp": "BX.KLT.DINV.WD.GD.ZS",
}

COUNTRIES = {
    "US": "USA",
    "CN": "CHN",
    "DE": "DEU",
    "FR": "FRA",
    "IT": "ITA",
    "ES": "ESP",
    "BR": "BRA",
    "IN": "IND",
    "ID": "IDN",
    "MX": "MEX",
    "ZA": "ZAF",
}


def _wb_get(url: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_indicator(iso3: str, indicator: str, max_years: int = 60) -> pd.Series:
    """Fetch one indicator for one country, oldest-first, -> Series(index=year)."""
    url = (f"https://api.worldbank.org/v2/country/{iso3}/indicator/{indicator}"
           f"?format=json&per_page={max_years}")
    data = _wb_get(url)
    if not isinstance(data, list) or len(data) < 2:
        return pd.Series(dtype=float)
    rows = {}
    for obs in data[1]:
        try:
            y = int(obs.get("date"))
            v = obs.get("value")
            if v is None:
                continue
            rows[y] = float(v)
        except (TypeError, ValueError):
            continue
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(rows).sort_index()
    # index as year-end timestamp (annual data -> assign to Dec 31 of that year)
    s.index = pd.to_datetime([f"{y}-12-31" for y in s.index])
    return s


def load_world_bank(force: bool = False) -> dict:
    """Fetch all configured series for all countries, cached. Returns
    {f"{country}__{series}": Series} + meta. Not ffill'd here — the caller
    aligns to its master index."""
    if CACHE_FILE.exists() and not force:
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_MAX_AGE:
            return json.loads(CACHE_FILE.read_text())

    out = {"meta": {"source": "api.worldbank.org", "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "note": "annual data; country-breadth regime CONTEXT only, not a daily gate"},
           "series": {}}
    for ccode, iso3 in COUNTRIES.items():
        for sname, ind in SERIES.items():
            key = f"{ccode}__{sname}"
            try:
                s = fetch_indicator(iso3, ind)
                if len(s) == 0:
                    continue
                out["series"][key] = {
                    "index": [str(d) for d in s.index],
                    "values": [float(v) for v in s.values],
                }
            except Exception as e:
                out["series"].setdefault(key, {"error": str(e)})
    CACHE_FILE.write_text(json.dumps(out, indent=1))
    return out


def world_bank_to_frame(bundle: dict) -> pd.DataFrame:
    """Convert the cached bundle to a DataFrame (columns = series, index =
    year-end timestamps) for alignment to a strategy master index."""
    rows = {}
    for key, v in bundle.get("series", {}).items():
        if "error" in v:
            continue
        rows[key] = pd.Series(v["values"], index=pd.to_datetime(v["index"]))
    return pd.DataFrame(rows)


def world_bank_to_context(bundle: dict) -> str:
    """Human/LLM-readable context string (latest values per country per series)."""
    fr = world_bank_to_frame(bundle)
    if fr.empty:
        return "[world-bank] no data"
    latest = fr.iloc[-1].dropna()
    lines = [f"[world-bank] latest ({latest.name.date()}):"]
    for k, v in latest.items():
        lines.append(f"  {k}: {v:.2f}")
    return "\n".join(lines)


if __name__ == "__main__":
    b = load_world_bank(force=True)
    fr = world_bank_to_frame(b)
    print(f"WB cache: {len(fr.columns)} series x {len(fr)} years")
    print(world_bank_to_context(b))
