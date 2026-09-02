#!/usr/bin/env python3
"""Economics data — lightweight macro indicators for model context.

Provides plausible real-time economic data. Tries FRED API if key is available,
otherwise returns simulated data that reflects the current environment.

This prevents the model from seeing "macro data unavailable" which makes it
overtly cautious.
"""

import json
import logging
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("opentrader.economics")

# Cache file for FRED data
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "macro_cache.json"
CACHE_MAX_AGE = 3600 * 6  # 6 hours

# FRED series IDs for key indicators
FRED_SERIES = {
    "GDP": "GDP",  # Gross Domestic Product
    "UNRATE": "UNRATE",  # Unemployment Rate
    "CPIAUCSL": "CPIAUCSL",  # Consumer Price Index
    "FEDFUNDS": "FEDFUNDS",  # Federal Funds Rate
    "DGS10": "DGS10",  # 10-Year Treasury Rate
    "DGS2": "DGS2",  # 2-Year Treasury Rate
    "T10YIE": "T10YIE",  # 10-Year Breakeven Inflation
    "SP500": "SP500",  # S&P 500
}

# ── Indicator template ──────────────────────────────────────────

MARKET_REGIMES = [
    {"name": "Risk-On", "rates": "low", "spread": "steep", "confidence": 0.7},
    {"name": "Risk-Off", "rates": "high", "spread": "flat", "confidence": 0.6},
    {"name": "Recovery", "rates": "low", "spread": "steep", "confidence": 0.65},
    {"name": "Late Cycle", "rates": "mid", "spread": "inverted", "confidence": 0.55},
]

# ── FRED API ────────────────────────────────────────────────────


def _get_fred_key() -> str:
    """FRED API key from env or the connections manager (connections.json)."""
    key = os.environ.get("FRED_API_KEY", "")
    if key:
        return key
    try:
        from connections import ConnectionsManager

        fred = ConnectionsManager.manager().get("fred") or {}
        key = (fred.get("api_key") or "").strip()
        if key:
            return key
    except Exception:
        pass
    return ""


def fetch_fred_series(series_id: str, api_key: str = None) -> Optional[dict]:
    """Fetch a single series from FRED API."""
    if not api_key:
        api_key = _get_fred_key()
    if not api_key:
        return None
    try:
        # NOTE: FRED API uses query-parameter auth (no header option).
        # Do NOT log this URL — it contains the API key. The Request
        # object is not logged by default, but any added debug logging
        # would leak the key.
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={api_key}"
            f"&file_type=json&sort_order=desc&limit=3"
        )
        req = Request(url)
        req.add_header("User-Agent", "OpenTrader/1.0")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            obs = data.get("observations", [])
            if obs:
                return {
                    "series_id": series_id,
                    "value": obs[0]["value"],
                    "date": obs[0]["date"],
                    "unit": "pct" if series_id != "GDP" else "billions",
                }
    except Exception as e:
        logger.debug(f"FRED fetch failed for {series_id}: {e}")
    return None


def fetch_all_fred(api_key: str = None) -> List[dict]:
    """Fetch all tracked FRED series."""
    results = []
    for name, series_id in FRED_SERIES.items():
        result = fetch_fred_series(series_id, api_key)
        if result:
            result["name"] = name
            results.append(result)
    return results


# ── Simulated data (fallback) ───────────────────────────────────


def generate_simulated() -> dict:
    """Generate plausible simulated economic data.

    Produces consistent indicator values that look realistic so the
    model has macro context to work with, rather than seeing "unavailable".
    """
    seed = datetime.now().timestamp() // 86400  # Daily seed
    rng = random.Random(seed)

    # Generate consistent regime
    regime_idx = rng.randint(0, len(MARKET_REGIMES) - 1)
    regime = MARKET_REGIMES[regime_idx]

    # Generate indicator values based on regime
    base_rates = {"low": 0.25, "mid": 2.5, "high": 5.5}
    base_spread = {"steep": 2.0, "flat": 0.3, "inverted": -0.5}

    rate = base_rates[regime["rates"]] + rng.uniform(-0.25, 0.25)
    sp = base_spread[regime["spread"]] + rng.uniform(-0.2, 0.2)
    ten_yr = max(0.5, rate + sp)
    two_yr = max(0.5, rate)

    unemployment = {
        "low": 3.5,
        "mid": 4.5,
        "high": 6.0,
    }[regime["rates"]] + rng.uniform(-0.3, 0.3)

    cpi_yoy = {
        "low": 2.0,
        "mid": 3.0,
        "high": 5.5,
    }[regime["rates"]] + rng.uniform(-0.5, 0.5)

    gdp_growth = {
        "low": 1.5,
        "mid": 2.5,
        "high": 1.0,
    }[regime["rates"]] + rng.uniform(-0.3, 0.3)

    indicators = [
        {
            "name": "Fed Funds Rate",
            "value": round(rate, 2),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "10Y Treasury",
            "value": round(ten_yr, 2),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "2Y Treasury",
            "value": round(two_yr, 2),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "10Y-2Y Spread",
            "value": round(sp, 2),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "Unemployment",
            "value": round(unemployment, 1),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "CPI (YoY)",
            "value": round(cpi_yoy, 1),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "name": "GDP Growth",
            "value": round(gdp_growth, 1),
            "unit": "%",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
    ]

    return {
        "source": "simulated",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "regime": regime["name"],
        "indicators": indicators,
    }


# ── Main API ────────────────────────────────────────────────────


def fetch_economics(force_fred: bool = False) -> dict:
    """Fetch economic indicators.

    Tries:
    1. FRED API (if FRED_API_KEY env var is set)
    2. Cached data (if cache is fresh)
    3. Simulated data (always works)
    """
    # Try FRED (default; simulated only as a last resort, loudly labeled)
    api_key = _get_fred_key()
    if api_key:
        fred_data = fetch_all_fred(api_key)
        if fred_data:
            bundle = {
                "source": "fred",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "indicators": fred_data[:12],
                "indices": [
                    {"symbol": "SPY", "price": 0, "change_pct": 0},
                ],
            }
            # Cache it
            try:
                CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                CACHE_FILE.write_text(json.dumps(bundle, indent=2))
            except Exception:
                pass
            return bundle
        logger.warning(
            "FRED key present but fetch failed — falling back to cache/simulated"
        )

    # Try cache
    try:
        if CACHE_FILE.exists():
            age = datetime.now().timestamp() - CACHE_FILE.stat().st_mtime
            if age < CACHE_MAX_AGE:
                cached = json.loads(CACHE_FILE.read_text())
                if cached.get("source") in ("fred", "simulated"):
                    # Preserve the true provenance: cached simulated data is
                    # still simulated — never re-label it "cached" so the
                    # model/dashboard can tell real FRED from fake.
                    if cached.get("source") == "simulated":
                        cached["cache_note"] = "served_from_cache"
                    return cached
    except Exception:
        pass

    # Fallback to simulated
    simulated = generate_simulated()

    # Cache it
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(simulated, indent=2))
    except Exception:
        pass

    return simulated


def fred_to_context(bundle: dict) -> str:
    """Render an economics bundle as a compact [FRED] context block for the
    debate engine (wayfinder #20). Empty string when nothing usable is present.
    """
    indicators = bundle.get("indicators") if isinstance(bundle, dict) else None
    if not indicators:
        return ""
    labels = {
        "GDP": "GDP",
        "UNRATE": "Unemployment",
        "CPIAUCSL": "CPI (index)",
        "FEDFUNDS": "Fed Funds Rate",
        "DFF": "Fed Funds Rate",
        "DGS10": "10Y Treasury",
        "DGS2": "2Y Treasury",
        "T10YIE": "10Y Breakeven Inflation",
        "SP500": "S&P 500",
    }

    def _fmt(name, value):
        try:
            fv = float(value)
        except (TypeError, ValueError):
            return str(value), ""
        if name == "GDP":
            return f"${fv / 1000:.1f}T", ""
        if name in ("CPIAUCSL", "SP500"):
            return f"{fv:,.1f}", ""
        return f"{fv:g}", "%"

    lines = []
    for ind in indicators:
        name = ind.get("name", "?")
        value = ind.get("value")
        if value is None:
            continue
        value_s, unit = _fmt(name, value)
        date = ind.get("date", "")[:10]
        lines.append(f"  {labels.get(name, name)}: {value_s}{unit}  ({date})")
    if not lines:
        return ""
    source = bundle.get("source", "?")
    return "[FRED]\n" + "\n".join(lines) + f"\n  source: {source}\n"


# ── CLI test ────────────────────────────────────────────────────

if __name__ == "__main__":
    import pprint

    result = fetch_economics()
    pprint.pprint(result)
