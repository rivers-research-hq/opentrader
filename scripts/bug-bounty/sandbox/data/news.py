#!/usr/bin/env python3
"""Crypto news and sentiment pipeline — feeds the debate model real-time context.

Sources (all free, no API keys):
  - Fear & Greed Index (alternative.me) — market sentiment 0-100
  - CoinGecko Trending — top searched coins
  - CoinGecko Global — total market cap, volume, BTC dominance
  - CoinGecko BTC stats — price changes, ATH, ATL, market cap rank

All data is cached to respect rate limits:
  - F&G: 1 hour (updates daily)
  - CoinGecko: 5 min (public API, ~30 calls/min limit)
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("opentrader.news")

CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_FILE = CACHE_DIR / "news_cache.json"
CACHE_TTL = {
    "fear_greed": 3600,       # 1 hour (updates daily)
    "coingecko": 300,         # 5 minutes
    "global": 300,
    "btc_stats": 300,
}

# ── Fear & Greed Index (alternative.me) ───────────────────────

def fetch_fear_greed(limit: int = 2) -> Optional[Dict]:
    """Fetch Crypto Fear & Greed Index.

    Returns dict with current value, classification, and yesterday's value.
    Range: 0 (Extreme Fear) to 100 (Extreme Greed).
    """
    try:
        url = f"https://api.alternative.me/fng/?limit={limit}"
        req = Request(url)
        req.add_header("User-Agent", "OpenTrader/1.0")
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            items = data.get("data", [])
            if not items:
                return None
            current = items[0]
            result = {
                "value": int(current["value"]),
                "classification": current["value_classification"],
                "timestamp": current.get("timestamp"),
                "time_until_update": current.get("time_until_update"),
            }
            # Add yesterday for trend
            if len(items) > 1:
                prev = items[1]
                result["yesterday_value"] = int(prev["value"])
                result["yesterday_classification"] = prev["value_classification"]
                result["change"] = int(current["value"]) - int(prev["value"])
            return result
    except Exception as e:
        logger.debug(f"Fear & Greed fetch failed: {e}")
        return None


# ── CoinGecko (free public API) ────────────────────────────────

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

def _cg_request(endpoint: str) -> Optional[Dict]:
    """Generic CoinGecko API request with rate-limit awareness."""
    try:
        url = f"{COINGECKO_BASE}{endpoint}"
        req = Request(url)
        req.add_header("User-Agent", "OpenTrader/1.0")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug(f"CoinGecko {endpoint} failed: {e}")
        return None


def fetch_trending() -> Optional[Dict]:
    """Fetch top trending coins from CoinGecko search/trending."""
    data = _cg_request("/search/trending")
    if not data:
        return None
    coins = []
    for item in data.get("coins", [])[:7]:
        c = item.get("item", {})
        coins.append({
            "name": c.get("name", "?"),
            "symbol": c.get("symbol", "?").upper(),
            "market_cap_rank": c.get("market_cap_rank"),
            "score": c.get("score"),
            "thumb": c.get("thumb", ""),
        })
    return {"top_trending": coins, "count": len(coins)}


def fetch_global() -> Optional[Dict]:
    """Fetch global crypto market stats."""
    data = _cg_request("/global")
    if not data:
        return None
    d = data.get("data", {})
    return {
        "total_market_cap_usd": d.get("total_market_cap", {}).get("usd"),
        "total_volume_24h_usd": d.get("total_volume", {}).get("usd"),
        "btc_dominance_pct": d.get("market_cap_percentage", {}).get("btc"),
        "eth_dominance_pct": d.get("market_cap_percentage", {}).get("eth"),
        "active_cryptocurrencies": d.get("active_cryptocurrencies"),
        "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd"),
    }


def fetch_btc_stats() -> Optional[Dict]:
    """Fetch BTC-specific stats: current price, 24h/7d/30d change, ATH, cycle position."""
    data = _cg_request("/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false")
    if not data:
        return None
    market = data.get("market_data", {})
    ath = market.get("ath", {}).get("usd")
    ath_date = market.get("ath_date", {}).get("usd", "")[:10]
    current = market.get("current_price", {}).get("usd")
    ath_pct = round((current / ath - 1) * 100, 1) if ath and current else None
    return {
        "price_usd": current,
        "market_cap_usd": market.get("market_cap", {}).get("usd"),
        "market_cap_rank": market.get("market_cap_rank"),
        "total_volume_usd": market.get("total_volume", {}).get("usd"),
        "price_change_24h_pct": round(market.get("price_change_percentage_24h", 0), 2),
        "price_change_7d_pct": round(market.get("price_change_percentage_7d", 0), 2),
        "price_change_30d_pct": round(market.get("price_change_percentage_30d", 0), 2),
        "ath_usd": ath,
        "ath_date": ath_date,
        "ath_change_pct": ath_pct,
        "atl_usd": market.get("atl", {}).get("usd"),
        "high_24h_usd": market.get("high_24h", {}).get("usd"),
        "low_24h_usd": market.get("low_24h", {}).get("usd"),
        "circulating_supply": market.get("circulating_supply"),
        "max_supply": market.get("max_supply"),
    }


# ── Cache layer ─────────────────────────────────────────────────

def _load_cache() -> Dict:
    """Load cached news data from disk."""
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: Dict):
    """Save news cache to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _is_fresh(cache_key: str, ttl: int) -> bool:
    """Check if cached data is still fresh."""
    cache = _load_cache()
    entry = cache.get(cache_key, {})
    last_fetch = entry.get("fetched_at", 0)
    return (time.time() - last_fetch) < ttl


# ── Main API ───────────────────────────────────────────────────

# ── Equity Market Data (yfinance — free, no API key) ───────────

_EQUITY_CACHE = {}
_EQUITY_CACHE_TS = 0

def fetch_equity_markets() -> dict:
    """Fetch S&P 500, NASDAQ, VIX, and sector performance via yfinance."""
    global _EQUITY_CACHE, _EQUITY_CACHE_TS
    if time.time() - _EQUITY_CACHE_TS < 300 and _EQUITY_CACHE:
        return _EQUITY_CACHE
    try:
        import yfinance as yf
        indices = {"^GSPC": "S&P500", "^IXIC": "NASDAQ", "^VIX": "VIX",
                    "^DJI": "DOW", "GC=F": "GOLD", "CL=F": "OIL"}
        result = {}
        for ticker, name in indices.items():
            try:
                t = yf.Ticker(ticker)
                info = t.info
                result[name.lower()] = {
                    "price": info.get("regularMarketPrice", 0),
                    "change_pct": info.get("regularMarketChangePercent", 0) if hasattr(t, 'info') else 0,
                }
            except Exception:
                result[name.lower()] = {"price": 0, "change_pct": 0}
        _EQUITY_CACHE = result
        _EQUITY_CACHE_TS = time.time()
        return result
    except Exception:
        return {}

def fetch_all_news(force: bool = False) -> Dict[str, Any]:
    """Fetch all news and sentiment data with caching.

    Returns a dict ready to be JSON-serialized and passed to the debate model.
    On failure of any individual source, returns partial data — never blocks.
    """
    cache = _load_cache()
    now = time.time()
    result = {"fetched_at": datetime.now(timezone.utc).isoformat(), "sources": {}}

    # ── Fear & Greed ──
    fg_key = "fear_greed"
    if force or now - cache.get(fg_key, {}).get("fetched_at", 0) > CACHE_TTL[fg_key]:
        fg = fetch_fear_greed()
        if fg:
            cache[fg_key] = {"data": fg, "fetched_at": now}
            logger.info(f"Fear & Greed: {fg['value']} ({fg['classification']})")
    if fg_key in cache:
        result["sources"]["fear_greed"] = cache[fg_key]["data"]

    # ── CoinGecko Trending ──
    cg_key = "coingecko_trending"
    if force or now - cache.get(cg_key, {}).get("fetched_at", 0) > CACHE_TTL["coingecko"]:
        trending = fetch_trending()
        if trending:
            cache[cg_key] = {"data": trending, "fetched_at": now}
            names = [c["symbol"] for c in trending.get("top_trending", [])]
            logger.info(f"Trending: {', '.join(names[:5])}")
    if cg_key in cache:
        result["sources"]["coingecko_trending"] = cache[cg_key]["data"]

    # ── CoinGecko Global ──
    gl_key = "coingecko_global"
    if force or now - cache.get(gl_key, {}).get("fetched_at", 0) > CACHE_TTL["global"]:
        gl = fetch_global()
        if gl:
            cache[gl_key] = {"data": gl, "fetched_at": now}
            logger.info(f"Global: MCap=${gl.get('total_market_cap_usd', 0)/1e12:.1f}T "
                        f"BTC.D={gl.get('btc_dominance_pct', 0):.1f}% "
                        f"24h={gl.get('market_cap_change_24h_pct', 0):+.1f}%")
    if gl_key in cache:
        result["sources"]["coingecko_global"] = cache[gl_key]["data"]

    # ── BTC Stats ──
    btc_key = "btc_stats"
    if force or now - cache.get(btc_key, {}).get("fetched_at", 0) > CACHE_TTL["btc_stats"]:
        btc = fetch_btc_stats()
        if btc:
            cache[btc_key] = {"data": btc, "fetched_at": now}
            logger.info(f"BTC: ${btc.get('price_usd', 0):,.0f} "
                        f"24h={btc.get('price_change_24h_pct', 0):+.1f}% "
                        f"7d={btc.get('price_change_7d_pct', 0):+.1f}%")
    if btc_key in cache:
        result["sources"]["btc_stats"] = cache[btc_key]["data"]

    _save_cache(cache)
    result["source_count"] = len(result["sources"])
    result["sources"]["equity_markets"] = fetch_equity_markets()
    return result
