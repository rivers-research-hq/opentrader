#!/usr/bin/env python3
"""Tradable Universe — 50+ assets across crypto, equities, forex, commodities.

The agent scans this universe each cycle, picks the most promising symbols,
and only deep-debates (ADIR) the top contenders.  This gives the agent freedom
to trade any asset without drowning in inference overhead.
"""

TRADABLE_UNIVERSE = [
    # ── Crypto (top 20 by market cap) ──
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT", "MATIC/USDT",
    "UNI/USDT", "ATOM/USDT", "LTC/USDT", "FIL/USDT", "APT/USDT",
    "ARB/USDT", "OP/USDT", "NEAR/USDT", "INJ/USDT", "SUI/USDT",

    # ── US Equities (mega/large cap, liquid) ──
    "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA",
    "JPM", "V", "JNJ", "WMT", "PG", "MA", "XOM", "HD",
    "BAC", "DIS", "NFLX", "ADBE", "CRM",

    # ── Forex majors ──
    "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD",
    "USD/CHF", "NZD/USD",

    # ── Commodities / ETFs ──
    "SPY", "QQQ", "GLD", "SLV", "USO", "UNG",

    # ── Agriculture ETFs (weather/drought/crop correlated) ──
    "CORN", "WEAT", "SOYB", "DBA",

    # ── Mining & individual miners (USGS mineral correlated) ──
    "PICK", "FCX", "BHP", "RIO",

    # ── Energy ETFs (EIA inventory correlated) ──
    "XLE", "XOP",

    # ── Specialty mineral ETFs ──
    "KOL", "LIT", "URNM",
]

DEFAULT_START_PRICES = {
    "BTC/USDT": 67000, "ETH/USDT": 3300, "SOL/USDT": 170,
    "XRP/USDT": 0.60, "DOGE/USDT": 0.15, "ADA/USDT": 0.45,
    "AVAX/USDT": 35, "DOT/USDT": 7, "LINK/USDT": 14, "MATIC/USDT": 0.70,
    "UNI/USDT": 8, "ATOM/USDT": 9, "LTC/USDT": 75, "FIL/USDT": 6, "APT/USDT": 9,
    "ARB/USDT": 1.2, "OP/USDT": 2.5, "NEAR/USDT": 5, "INJ/USDT": 25, "SUI/USDT": 1.8,

    "AAPL": 190, "NVDA": 120, "MSFT": 420, "GOOGL": 175, "AMZN": 200,
    "META": 500, "TSLA": 250, "JPM": 200, "V": 280, "JNJ": 155,
    "WMT": 70, "PG": 165, "MA": 470, "XOM": 115, "HD": 370,
    "BAC": 40, "DIS": 100, "NFLX": 650, "ADBE": 520, "CRM": 290,

    "EUR/USD": 1.08, "GBP/USD": 1.27, "USD/JPY": 150, "AUD/USD": 0.66,
    "USD/CAD": 1.35, "USD/CHF": 0.88, "NZD/USD": 0.61,

    "SPY": 550, "QQQ": 470, "GLD": 220, "SLV": 28, "USO": 75, "UNG": 3.5,

    # Wave 3b: Agriculture, mining, energy ETFs
    "CORN": 35, "WEAT": 50, "SOYB": 28, "DBA": 25,
    "PICK": 55, "FCX": 45, "BHP": 60, "RIO": 80,
    "XLE": 95, "XOP": 40,
    "KOL": 20, "LIT": 60, "URNM": 25,
}

SCOUT_PROMPT = """You are scanning a universe of tradable assets. Below is a summary of current prices and recent changes.

For each asset, score its trading opportunity from 0-10:
  10 = very strong signal (clear trend, volatility, or pattern)
  0  = no edge, avoid

Return a JSON array of the top {{n}} assets you want to deep-analyze:
[{"symbol": "BTC/USDT", "score": 8, "reason": "strong uptrend + volume spike"},
 {"symbol": "NVDA", "score": 7, "reason": "breakout above resistance"},
 ...]

Only pick assets with score >= 5. If fewer than {{n}} have score >= 5, return fewer.

Current market snapshot:
{{snapshot}}"""
