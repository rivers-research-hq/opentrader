#!/usr/bin/env python3
"""Dynamic symbol discovery — the agent can expand its tradable universe.

When the scout finds weak signals, the agent triggers discovery mode to
research and add new tickers.  Supports SEC EDGAR lookups and sector
expansion.
"""

import json
import logging
from typing import List, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("opentrader.discovery")

# Quick-serve sector map so the agent can say "show me semiconductors"
SECTOR_MAP: Dict[str, List[str]] = {
    "semiconductors": ["AMD", "INTC", "TSM", "ASML", "QCOM", "AVGO", "MU", "TXN", "AMAT"],
    "ai": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "SNOW", "PLTR", "ANET"],
    "fintech": ["SQ", "PYPL", "COIN", "AFRM", "SOFI", "HOOD", "NU", "FIS", "FISV"],
    "biotech": ["MRNA", "BNTX", "REGN", "VRTX", "GILD", "AMGN", "BIIB", "ILMN"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "DVN", "HAL", "MPC"],
    "defense": ["LMT", "RTX", "NOC", "GD", "LHX", "BA", "HII", "TDG"],
    "consumer": ["AAPL", "AMZN", "TSLA", "NKE", "SBUX", "MCD", "COST", "TGT", "HD"],
    "crypto": ["COIN", "MARA", "RIOT", "MSTR", "CLSK", "HUT", "BITF", "WULF"],
    "ev": ["TSLA", "RIVN", "LCID", "NIO", "XPEV", "F", "GM", "HMC", "TM"],
    "cloud": ["AMZN", "MSFT", "GOOGL", "CRM", "NOW", "NET", "DDOG", "MDB", "SNOW"],
    "realestate": ["SPG", "PLD", "AMT", "CCI", "EQIX", "O", "DLR", "PSA", "WELL"],
    "china_tech": ["BABA", "BIDU", "JD", "PDD", "TCEHY", "BILI", "NTES", "TME"],
}

# Price estimates for stocks not in DEFAULT_START_PRICES
PRICE_ESTIMATES: Dict[str, float] = {
    "AMD": 150, "INTC": 35, "TSM": 170, "ASML": 950, "QCOM": 185,
    "AVGO": 165, "MU": 125, "TXN": 195, "AMAT": 220, "SNOW": 155,
    "PLTR": 55, "ANET": 85, "SQ": 75, "PYPL": 65, "COIN": 210,
    "AFRM": 45, "SOFI": 14, "HOOD": 35, "NU": 12, "FIS": 75,
    "MRNA": 45, "BNTX": 115, "REGN": 950, "VRTX": 430, "GILD": 75,
    "AMGN": 310, "BIIB": 175, "ILMN": 130, "CVX": 160, "COP": 115,
    "SLB": 48, "EOG": 130, "OXY": 58, "DVN": 48, "MPC": 175,
    "LMT": 520, "RTX": 125, "NOC": 480, "GD": 300, "LHX": 240,
    "BA": 185, "HII": 275, "TDG": 1350, "NKE": 85, "SBUX": 100,
    "MCD": 510, "COST": 870, "TGT": 145, "MARA": 20, "RIOT": 11,
    "MSTR": 240, "CLSK": 10, "BITF": 3, "WULF": 4, "RIVN": 13,
    "LCID": 4, "NIO": 5, "XPEV": 9, "F": 11, "GM": 50, "HMC": 33,
    "TM": 185, "CRM": 280, "NOW": 830, "NET": 120, "DDOG": 130,
    "MDB": 280, "SPG": 165, "PLD": 115, "AMT": 210, "CCI": 110,
    "EQIX": 890, "O": 55, "DLR": 160, "PSA": 340, "WELL": 110,
    "BABA": 100, "BIDU": 100, "JD": 35, "PDD": 140, "TCEHY": 50,
    "BILI": 18, "NTES": 95, "TME": 13,
}

DISCOVERY_PROMPT = """You are scanning {{n}} assets for trading opportunities.

Current picks scored >=5: {{picked_count}}
{{picks}}

If you want more assets to choose from, output a JSON discovery request:
{"discover": ["TICKER1", "TICKER2", ...]}

You can also request a sector:
{"discover_sector": "sector_name"}

Available sectors: {{sectors}}

Or just output the standard picks array if you have enough good signals."""  # noqa: E501


def search_sec_edgar(query: str, limit: int = 10) -> List[dict]:
    """Search SEC EDGAR for company filings matching a query.

    Returns list of {cik, name, ticker} dicts.
    Uses the SEC's free EDGAR full-text search API.
    """
    url = "https://efts.sec.gov/LATEST/search-index"
    headers = {"User-Agent": "OpenTrader/1.0 (research@opentrader.dev)"}
    payload = json.dumps({
        "q": query,
        "dateRange": "custom",
        "startdt": "2025-01-01",
        "enddt": "2026-07-16",
        "category": "form-cat1",
        "forms": ["10-K", "10-Q", "8-K"],
        "count": limit,
    }).encode()

    try:
        req = Request(url, data=payload, headers=headers)
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            results = []
            for hit in data.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                company = source.get("display_names", [""])[0]
                cik = source.get("ciks", [None])[0]
                results.append({
                    "cik": cik,
                    "name": company,
                    "ticker": "",  # SEC full-text search doesn't return tickers
                })
            return results[:limit]
    except (URLError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"SEC EDGAR search failed: {e}")
        return []


def cik_to_ticker(cik: str) -> Optional[str]:
    """Map a CIK to its ticker symbol using SEC's company_tickers.json."""
    try:
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": "OpenTrader/1.0 (research@opentrader.dev)"}
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for entry in data.values():
                if str(entry.get("cik_str", "")) == str(cik).lstrip("0"):
                    return entry.get("ticker", "").upper()
    except Exception as e:
        logger.debug(f"CIK→ticker lookup failed for {cik}: {e}")
    return None


def resolve_discovery(discovery_request: dict) -> List[str]:
    """Resolve a discovery request to a list of tickers.

    Supports: {"discover": ["AAPL"]}, {"discover_sector": "ai"},
              {"discover_sec": "quantum computing companies"}
    """
    tickers = []

    if "discover_sector" in discovery_request:
        sector = discovery_request["discover_sector"].lower().replace(" ", "_")
        for name, syms in SECTOR_MAP.items():
            if sector in name or name in sector:
                tickers.extend(syms)
                break
        else:
            logger.info(f"Unknown sector '{sector}', trying partial match...")
            for name, syms in SECTOR_MAP.items():
                if any(w in name for w in sector.split("_")):
                    tickers.extend(syms)

    if "discover" in discovery_request:
        tickers.extend(discovery_request["discover"])

    if "discover_sec" in discovery_request:
        query = discovery_request["discover_sec"]
        results = search_sec_edgar(query)
        for r in results:
            if r["cik"]:
                ticker = cik_to_ticker(r["cik"])
                if ticker:
                    tickers.append(ticker)
            logger.info(f"SEC discovery: {r['name']} (CIK {r['cik']}) → {ticker or 'no ticker found'}")

    return list(set(t.upper() for t in tickers if t))


def get_sector_list() -> str:
    return ", ".join(sorted(SECTOR_MAP.keys()))


def refresh_from_exchange(exchange, fallback_universe: Optional[List[str]] = None) -> List[str]:
    """Discover tradable symbols from the exchange, falling back to a hardcoded list.

    Returns a deduplicated, sorted list of symbol strings.
    """
    try:
        live = exchange.discover_symbols()
        if live:
            logger.info(f"Discovered {len(live)} symbols from exchange")
            return sorted(set(live))
    except Exception as e:
        logger.warning(f"Exchange symbol discovery failed: {e}")

    if fallback_universe:
        logger.info(f"Using fallback universe ({len(fallback_universe)} symbols)")
        return sorted(set(fallback_universe))
    return []
