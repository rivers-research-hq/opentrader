#!/usr/bin/env python3
"""Social media sentiment fetcher for crypto assets.

Provides per-symbol sentiment scores by pulling from free public APIs:
  1. Alternative.me Fear & Greed Index (overall market mood)
  2. CoinPaprika news feed (crypto news headlines → basic NLP)
  3. Fallback: neutral scores for all symbols

Cache TTL: 15 minutes. All fetches are wrapped in try/except — never raises.
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("opentrader.social")

CACHE_DIR = Path(__file__).resolve().parent
CACHE_FILE = CACHE_DIR / "social_cache.json"
CACHE_TTL = 900  # 15 seconds → typical social feed freshness
REQUEST_TIMEOUT = 10  # seconds

# Symbol → keyword mapping for news relevance scoring
SYMBOL_KEYWORDS: Dict[str, List[str]] = {
    "BTC/USDT": ["bitcoin", "btc"],
    "ETH/USDT": ["ethereum", "eth"],
    "SOL/USDT": ["solana", "sol"],
    "AAPL": ["apple", "aapl"],
    "NVDA": ["nvidia", "nvda"],
    "SONY": ["sony", "sne"],
}

# Sentiment word lists for basic headline scoring
BULLISH_WORDS = {
    "surge", "soar", "moon", "bullish", "breakthrough", "adoption", "rally",
    "upgrade", "partnership", "launch", "approval", "positive", "gain",
    "outperform", "growth", "boom", "institutional", "etf", "halving",
}
BEARISH_WORDS = {
    "crash", "plunge", "dump", "bearish", "ban", "crackdown", "sell-off",
    "decline", "loss", "negative", "fear", "panic", "liquidation",
    "hack", "exploit", "fraud", "scam", "regulation", "fine", "lawsuit",
}


def _load_cache() -> Optional[Dict[str, Dict]]:
    """Load cached sentiment if fresh enough."""
    if not CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(CACHE_FILE.read_text())
        age = time.time() - cache.get("fetched_at", 0)
        if age < CACHE_TTL:
            return cache.get("sentiment", {})
    except Exception:
        pass
    return None


def _save_cache(sentiment: Dict[str, Dict]) -> None:
    """Save sentiment to disk cache."""
    CACHE_FILE.write_text(json.dumps({
        "sentiment": sentiment,
        "fetched_at": time.time(),
    }, indent=2))


def _score_headline(headline: str) -> float:
    """Score a headline from -1.0 (bearish) to +1.0 (bullish) using word lists."""
    words = set(re.findall(r"[a-z]+", headline.lower()))
    bull_count = len(words & BULLISH_WORDS)
    bear_count = len(words & BEARISH_WORDS)
    total = bull_count + bear_count
    if total == 0:
        return 0.0
    return (bull_count - bear_count) / total


def _fetch_fear_greed() -> Optional[float]:
    """Fetch the Fear & Greed Index from alternative.me (free, no key needed).

    Returns: float 0.0-1.0 where 0=extreme fear, 1=extreme greed, or None on failure.
    """
    url = "https://api.alternative.me/fng/?limit=1"
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "OpenTrader/1.0")
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            value = int(data["data"][0]["value"])
            normalized = value / 100.0  # 0.0-1.0
            logger.debug(f"Fear & Greed: {value}/100 → {normalized:.2f}")
            return normalized
    except Exception as e:
        logger.debug(f"Fear & Greed fetch failed: {e}")
        return None


def _fetch_cryptopanic_news() -> Optional[List[Dict]]:
    """Fetch recent crypto news from CoinPaprika's free news endpoint.

    Returns list of {title, source} dicts, or None on failure.
    """
    url = "https://api.coinpaprika.com/v1/coins/btc-bitcoin/events"
    try:
        # Use CoinPaprika's news endpoint — free, no API key needed for basic access
        req = Request(
            "https://api.coinpaprika.com/v1/coins/btc-bitcoin/events",
            method="GET",
        )
        req.add_header("User-Agent", "OpenTrader/1.0")
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            # CoinPaprika returns events; extract titles/descriptions
            headlines = []
            if isinstance(data, list):
                for event in data[:20]:
                    title = event.get("title", "")
                    desc = event.get("description", "")
                    if title:
                        headlines.append({
                            "title": title,
                            "description": desc[:200] if desc else "",
                            "source": "coinpaprika",
                        })
            return headlines if headlines else None
    except Exception as e:
        logger.debug(f"CoinPaprika news fetch failed: {e}")
        return None


def _score_news_for_symbol(news_items: List[Dict], symbol: str) -> Tuple[float, int]:
    """Score news headlines for relevance to a given symbol.

    Returns (avg_score, mention_count). Score ranges -1.0 to +1.0.
    """
    keywords = SYMBOL_KEYWORDS.get(symbol, [symbol.lower().replace("/usdt", "").replace("/", "")])
    scores = []
    mentions = 0

    for item in news_items:
        text = (item.get("title", "") + " " + item.get("description", "")).lower()
        if not any(kw in text for kw in keywords):
            continue
        mentions += 1
        headline_score = _score_headline(item.get("title", ""))
        # Blend with description if available
        desc_score = _score_headline(item.get("description", "")) if item.get("description") else 0.0
        combined = (headline_score * 0.7 + desc_score * 0.3)  # title weighted higher
        scores.append(combined)

    if not scores:
        return (0.0, 0)
    avg = sum(scores) / len(scores)
    return (avg, mentions)


def _fng_to_sentiment_label(score: float) -> str:
    """Convert Fear & Greed score to label."""
    if score >= 0.75:
        return "extreme_greed"
    elif score >= 0.55:
        return "greed"
    elif score >= 0.45:
        return "neutral"
    elif score >= 0.25:
        return "fear"
    else:
        return "extreme_fear"


def _score_to_sentiment_label(score: float) -> str:
    """Convert -1.0..1.0 score to sentiment label."""
    if score >= 0.3:
        return "bullish"
    elif score >= 0.1:
        return "slightly_bullish"
    elif score <= -0.3:
        return "bearish"
    elif score <= -0.1:
        return "slightly_bearish"
    else:
        return "neutral"


def get_social_sentiment(symbols: List[str]) -> Dict[str, Dict]:
    """Get social sentiment for a list of trading symbols.

    Combines Fear & Greed Index with crypto news headline scoring.
    Results cached for 15 minutes.

    Args:
        symbols: List of symbol strings (e.g. ["BTC/USDT", "ETH/USDT"])

    Returns:
        Dict mapping each symbol to:
            score: float 0.0-1.0 (normalized, higher = more bullish)
            raw_score: float -1.0..1.0 (raw sentiment before normalization)
            mentions: int (number of relevant news items found)
            sentiment: str label
            source: str data source used

    Example:
        {
            "BTC/USDT": {"score": 0.65, "raw_score": 0.30, "mentions": 3,
                         "sentiment": "slightly_bullish", "source": "fng+news"},
            "ETH/USDT": {"score": 0.50, "raw_score": 0.0, "mentions": 0,
                         "sentiment": "neutral", "source": "fng_only"},
        }
    """
    # Check cache
    cached = _load_cache()
    if cached is not None:
        logger.debug(f"Social cache hit: {len(cached)} symbols")
        return {sym: cached.get(sym, _neutral(sym)) for sym in symbols}

    # Fetch data sources
    fng_score = _fetch_fear_greed()
    news_items = _fetch_cryptopanic_news()

    result = {}
    for symbol in symbols:
        if not news_items:
            # FNG only
            if fng_score is not None:
                result[symbol] = {
                    "score": fng_score,
                    "raw_score": (fng_score - 0.5) * 2,  # 0..1 → -1..1
                    "mentions": 0,
                    "sentiment": _fng_to_sentiment_label(fng_score),
                    "source": "fng_only",
                }
            else:
                result[symbol] = _neutral(symbol)
        else:
            # Blend FNG + news
            raw_news_score, mentions = _score_news_for_symbol(news_items, symbol)
            if fng_score is not None:
                # Blend: FNG gives market-wide context, news gives symbol-specific
                fng_raw = (fng_score - 0.5) * 2  # 0..1 → -1..1
                blended_raw = fng_raw * 0.3 + raw_news_score * 0.7  # news weighted heavier
            else:
                blended_raw = raw_news_score

            # Clamp to [-1, 1]
            blended_raw = max(-1.0, min(1.0, blended_raw))
            # Normalize to [0, 1]
            normalized = (blended_raw + 1.0) / 2.0

            result[symbol] = {
                "score": round(normalized, 4),
                "raw_score": round(blended_raw, 4),
                "mentions": mentions,
                "sentiment": _score_to_sentiment_label(blended_raw),
                "source": "fng+news" if fng_score is not None else "news_only",
            }

    _save_cache(result)
    parts = []
    for s, v in result.items():
        sent = v["sentiment"]
        sc = v["score"]
        parts.append(f"{s}={sent}({sc})")
    logger.info(f"Social sentiment: {', '.join(parts)}")
    return result


def _neutral(symbol: str) -> Dict:
    """Return a neutral sentiment entry."""
    return {
        "score": 0.5,
        "raw_score": 0.0,
        "mentions": 0,
        "sentiment": "neutral",
        "source": "fallback",
    }


# ── Test ──
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    result = get_social_sentiment(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    print(json.dumps(result, indent=2))
