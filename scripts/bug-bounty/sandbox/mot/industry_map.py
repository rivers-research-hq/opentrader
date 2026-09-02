#!/usr/bin/env python3
"""Industry Registry — 40 sub-industries, ~500 tickers, GICS 11 sectors.

Exposes INDUSTRY_REGISTRY for universe expansion and alt-data binding.
Dynamic discovery via `discover_sector: "uranium_miners"` at runtime.
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.industry")

PROJECT = Path(__file__).resolve().parent.parent
CACHE_DB = PROJECT / "data" / "ticker_industry_cache.db"

# ── 40 Sub-Industries with ~500 tickers total ──────────────────

INDUSTRY_REGISTRY: Dict[str, List[str]] = {
    # GICS 10 — Energy
    "petroleum_producers": [
        "XOM",
        "CVX",
        "COP",
        "EOG",
        "OXY",
        "DVN",
        "MPC",
        "PSX",
        "VLO",
        "HES",
        "PXD",
        "FANG",
        "MRO",
        "APA",
        "OVV",
        "CTRA",
        "CHK",
    ],
    "refiners": ["VLO", "MPC", "PSX", "DK", "PBF", "CLNE", "DINO", "CVI"],
    "oil_services": [
        "SLB",
        "HAL",
        "BKR",
        "NOV",
        "FTI",
        "WFRD",
        "CHX",
        "OII",
        "HP",
        "TDW",
        "RES",
    ],
    "natural_gas": [
        "LNG",
        "AR",
        "RRC",
        "EQT",
        "CTRA",
        "SWN",
        "UNG",
        "NFG",
        "CNX",
        "CRK",
    ],
    "coal": ["BTU", "ARCH", "CEIX", "HCC", "KOL", "CNX", "ARLP", "NRP"],
    # GICS 15 — Materials
    "copper_miners": [
        "FCX",
        "SCCO",
        "BHP",
        "RIO",
        "TECK",
        "FM",
        "HBM",
        "PICK",
        "FCX",
        "TGB",
        "CS",
        "LUN",
    ],
    "gold_miners": [
        "NEM",
        "GOLD",
        "AEM",
        "GFI",
        "KGC",
        "AU",
        "WPM",
        "GDX",
        "BTG",
        "RGLD",
        "OR",
        "SAND",
        "AGI",
    ],
    "iron_miners": ["BHP", "RIO", "VALE", "CLF", "NUE", "AA", "SID", "TX", "SIM"],
    "lithium": ["ALB", "SQM", "LAC", "SGML", "PLL", "LIT", "LTHM", "SLI", "LI"],
    "uranium_miners": [
        "CCJ",
        "UEC",
        "DNN",
        "UUUU",
        "NXE",
        "URNM",
        "URA",
        "EU",
        "UROY",
        "U.L",
    ],
    "chemicals": [
        "LIN",
        "APD",
        "DOW",
        "DD",
        "LYB",
        "NTR",
        "CF",
        "MOS",
        "EMN",
        "FMC",
        "AVNT",
        "WLK",
        "AXTA",
    ],
    "steel_producers": [
        "NUE",
        "STLD",
        "CLF",
        "X",
        "CMC",
        "RS",
        "SLX",
        "GGB",
        "SID",
        "MT",
        "TX",
        "PKX",
    ],
    # GICS 20 — Industrials
    "aerospace_defense": [
        "LMT",
        "RTX",
        "BA",
        "NOC",
        "GD",
        "HWM",
        "TDG",
        "LHX",
        "HII",
        "AXON",
        "CW",
        "SPR",
        "HEI",
    ],
    "construction_machinery": [
        "CAT",
        "DE",
        "CMI",
        "PCAR",
        "ALSN",
        "VMC",
        "URI",
        "OSK",
        "TEX",
        "MTW",
    ],
    "industrial_conglomerates": [
        "GE",
        "MMM",
        "HON",
        "ITW",
        "ETN",
        "PH",
        "ROK",
        "DOV",
        "IR",
        "XYL",
        "AOS",
        "MSA",
    ],
    "airlines": ["DAL", "UAL", "AAL", "LUV", "JETS", "ALK", "JBLU", "SAVE", "AZUL"],
    "railroads": ["UNP", "CSX", "NSC", "CP", "CNI", "WAB", "GBX", "TRN", "RAIL"],
    "waste_management": ["WM", "RSG", "WCN", "GFL", "CLH", "PESI", "CWST"],
    "electrical_equipment": [
        "AME",
        "ETN",
        "EMR",
        "ABB",
        "SIE",
        "SU",
        "VRT",
        "HUBB",
        "ENS",
        "AEIS",
    ],
    # GICS 25 — Consumer Discretionary
    "automobiles": [
        "TSLA",
        "F",
        "GM",
        "RIVN",
        "LCID",
        "TM",
        "HMC",
        "STLA",
        "HMC",
        "NIO",
        "XPEV",
        "LI",
        "GGR",
    ],
    "luxury_retail": [
        "LVMUY",
        "KERING",
        "RACE",
        "LULU",
        "TPR",
        "RL",
        "BURBY",
        "CPRI",
        "TIF",
        "EL",
    ],
    "ecommerce": [
        "AMZN",
        "BABA",
        "JD",
        "MELI",
        "ETSY",
        "W",
        "CPNG",
        "SE",
        "SHOP",
        "PDD",
        "CART",
    ],
    "casinos_gaming": [
        "LVS",
        "WYNN",
        "MGM",
        "CZR",
        "DKNG",
        "PENN",
        "CHDN",
        "SRAD",
        "BALY",
    ],
    "restaurants": [
        "MCD",
        "SBUX",
        "CMG",
        "YUM",
        "DRI",
        "DPZ",
        "QSR",
        "WEN",
        "TXRH",
        "CAKE",
        "PLAY",
        "WING",
    ],
    "home_builders": [
        "DHI",
        "LEN",
        "PHM",
        "TOL",
        "NVR",
        "XHB",
        "KBH",
        "MDC",
        "TMHC",
        "MHO",
    ],
    # GICS 30 — Consumer Staples
    "consumer_staples": [
        "PG",
        "KO",
        "PEP",
        "WMT",
        "COST",
        "PM",
        "MO",
        "CL",
        "KMB",
        "HSY",
        "MDLZ",
        "KHC",
        "GIS",
        "K",
        "CAG",
        "SJM",
        "CPB",
    ],
    "food_retail": [
        "KR",
        "ACI",
        "SFM",
        "BJ",
        "BBY",
        "DLTR",
        "DG",
        "COST",
        "WMT",
        "TGT",
    ],
    # GICS 35 — Health Care
    "pharmaceuticals": [
        "JNJ",
        "PFE",
        "MRK",
        "ABBV",
        "LLY",
        "BMY",
        "GILD",
        "AMGN",
        "BIIB",
        "VRTX",
        "BAX",
        "TMO",
        "DHR",
    ],
    "biotech": [
        "MRNA",
        "BNTX",
        "REGN",
        "ILMN",
        "CRSP",
        "NTLA",
        "ALNY",
        "BBIO",
        "XBI",
        "INCY",
        "EXAS",
        "SRPT",
        "IONS",
    ],
    "health_equipment": [
        "ABT",
        "SYK",
        "BSX",
        "BDX",
        "MDT",
        "EW",
        "ISRG",
        "DXCM",
        "ZBH",
        "PODD",
        "HOLX",
        "IDXX",
    ],
    "managed_care": ["UNH", "CI", "HUM", "CNC", "ELV", "MOH", "OSCR", "ALHC", "HQY"],
    # GICS 40 — Financials
    "banks_major": [
        "JPM",
        "BAC",
        "WFC",
        "C",
        "GS",
        "MS",
        "USB",
        "PNC",
        "SCHW",
        "TFC",
        "COF",
        "BK",
        "STT",
    ],
    "regional_banks": [
        "TFC",
        "CFG",
        "KEY",
        "FITB",
        "HBAN",
        "RF",
        "KRE",
        "ZION",
        "EWBC",
        "WAL",
        "CMA",
        "FHB",
        "PB",
        "OZK",
    ],
    "insurance": [
        "BRK.B",
        "AIG",
        "MET",
        "PRU",
        "ALL",
        "TRV",
        "PGR",
        "CB",
        "AFL",
        "HIG",
        "LNC",
        "GL",
        "MMC",
        "AJG",
    ],
    "fintech": [
        "SQ",
        "PYPL",
        "COIN",
        "AFRM",
        "SOFI",
        "HOOD",
        "NU",
        "FIS",
        "FI",
        "TOST",
        "BILL",
        "MQ",
        "FOUR",
        "ADYEN",
    ],
    # GICS 45 — Information Technology
    "semiconductors": [
        "NVDA",
        "AMD",
        "INTC",
        "TSM",
        "AVGO",
        "QCOM",
        "MU",
        "TXN",
        "AMAT",
        "LRCX",
        "ASML",
        "ADI",
        "SMH",
        "MRVL",
        "ON",
        "MCHP",
        "MPWR",
        "NXPI",
    ],
    "software": [
        "MSFT",
        "ORCL",
        "ADBE",
        "CRM",
        "NOW",
        "SNOW",
        "PLTR",
        "ANET",
        "PANW",
        "CRWD",
        "ZS",
        "DDOG",
        "MDB",
        "WDAY",
        "TEAM",
        "SPLK",
        "OKTA",
        "DT",
    ],
    "cloud_infra": [
        "AMZN",
        "GOOGL",
        "MSFT",
        "ORCL",
        "IBM",
        "NET",
        "FSLY",
        "MDB",
        "RXT",
        "HCP",
    ],
    "consumer_electronics": [
        "AAPL",
        "SONY",
        "SAMSUNG",
        "LG",
        "GRMN",
        "SONO",
        "ROKU",
        "VUZI",
    ],
    "enterprise_it": [
        "ACN",
        "IBM",
        "CSCO",
        "HPQ",
        "DELL",
        "CDW",
        "INFY",
        "CTSH",
        "WIT",
        "EPAM",
        "GLOB",
        "COHR",
    ],
    # GICS 50 — Communication Services
    "social_media": ["META", "SNAP", "PINS", "MTCH", "BILI", "RDDT", "NEGG"],
    "telecom": ["T", "VZ", "TMUS", "CMCSA", "CHTR", "LUMN", "AMT", "CCI", "IRDM"],
    "gaming_online": ["EA", "TTWO", "RBLX", "NTES", "GME", "U", "SE", "PLTK"],
    # GICS 55 — Utilities
    "electric_utilities": [
        "NEE",
        "DUK",
        "SO",
        "D",
        "AEP",
        "EXC",
        "SRE",
        "ED",
        "XEL",
        "WEC",
        "PPL",
        "FE",
        "EIX",
        "ES",
    ],
    "renewable_energy": [
        "ENPH",
        "SEDG",
        "FSLR",
        "RUN",
        "NOVA",
        "ICLN",
        "NEP",
        "TAN",
        "BE",
        "PLUG",
        "BLDP",
        "FCEL",
        "ARRY",
    ],
    # GICS 60 — Real Estate
    "reits": [
        "O",
        "SPG",
        "PLD",
        "AMT",
        "CCI",
        "EQIX",
        "DLR",
        "PSA",
        "WELL",
        "AVB",
        "EQR",
        "ESS",
        "UDR",
        "MAA",
        "CPT",
    ],
    # Agriculture + Mining cross-sector ETFs
    "agriculture_corn": ["CORN", "DE", "ADM", "BG", "INGR", "DBA", "TAGS", "RJA"],
    "agriculture_wheat": ["WEAT", "ADM", "BG", "DBA", "TAGS"],
    "agriculture_soybean": ["SOYB", "ADM", "BG", "DBA"],
}

INDUSTRY_META: Dict[str, dict] = {
    "petroleum_producers": {"gics": 10, "median_price": 120},
    "refiners": {"gics": 10, "median_price": 100},
    "oil_services": {"gics": 10, "median_price": 50},
    "natural_gas": {"gics": 10, "median_price": 35},
    "coal": {"gics": 10, "median_price": 25},
    "copper_miners": {"gics": 15, "median_price": 55},
    "gold_miners": {"gics": 15, "median_price": 40},
    "iron_miners": {"gics": 15, "median_price": 60},
    "lithium": {"gics": 15, "median_price": 30},
    "uranium_miners": {"gics": 15, "median_price": 25},
    "chemicals": {"gics": 15, "median_price": 80},
    "steel_producers": {"gics": 15, "median_price": 50},
    "aerospace_defense": {"gics": 20, "median_price": 200},
    "construction_machinery": {"gics": 20, "median_price": 150},
    "industrial_conglomerates": {"gics": 20, "median_price": 120},
    "airlines": {"gics": 20, "median_price": 50},
    "railroads": {"gics": 20, "median_price": 200},
    "waste_management": {"gics": 20, "median_price": 150},
    "electrical_equipment": {"gics": 20, "median_price": 100},
    "automobiles": {"gics": 25, "median_price": 50},
    "luxury_retail": {"gics": 25, "median_price": 100},
    "ecommerce": {"gics": 25, "median_price": 100},
    "casinos_gaming": {"gics": 25, "median_price": 60},
    "restaurants": {"gics": 25, "median_price": 180},
    "home_builders": {"gics": 25, "median_price": 100},
    "consumer_staples": {"gics": 30, "median_price": 80},
    "food_retail": {"gics": 30, "median_price": 50},
    "pharmaceuticals": {"gics": 35, "median_price": 100},
    "biotech": {"gics": 35, "median_price": 60},
    "health_equipment": {"gics": 35, "median_price": 120},
    "managed_care": {"gics": 35, "median_price": 300},
    "banks_major": {"gics": 40, "median_price": 80},
    "regional_banks": {"gics": 40, "median_price": 40},
    "insurance": {"gics": 40, "median_price": 100},
    "fintech": {"gics": 40, "median_price": 60},
    "semiconductors": {"gics": 45, "median_price": 120},
    "software": {"gics": 45, "median_price": 150},
    "cloud_infra": {"gics": 45, "median_price": 150},
    "consumer_electronics": {"gics": 45, "median_price": 120},
    "enterprise_it": {"gics": 45, "median_price": 100},
    "social_media": {"gics": 50, "median_price": 100},
    "telecom": {"gics": 50, "median_price": 40},
    "gaming_online": {"gics": 50, "median_price": 80},
    "electric_utilities": {"gics": 55, "median_price": 70},
    "renewable_energy": {"gics": 55, "median_price": 50},
    "reits": {"gics": 60, "median_price": 100},
    "agriculture_corn": {"gics": "agriculture", "median_price": 35},
    "agriculture_wheat": {"gics": "agriculture", "median_price": 25},
    "agriculture_soybean": {"gics": "agriculture", "median_price": 28},
}


def _init_cache():
    os.makedirs(CACHE_DB.parent, exist_ok=True)
    with sqlite3.connect(str(CACHE_DB)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ticker_industry "
            "(ticker TEXT PRIMARY KEY, industry TEXT)"
        )


def _build_ticker_map() -> Dict[str, str]:
    """Build ticker -> industry reverse lookup, cached in SQLite."""
    _init_cache()
    with sqlite3.connect(str(CACHE_DB)) as conn:
        row = conn.execute("SELECT COUNT(*) FROM ticker_industry").fetchone()
        if row and row[0] > 0:
            return {r[0]: r[1] for r in conn.execute("SELECT * FROM ticker_industry")}

    # First time: build from registry
    mapping = {}
    for industry, tickers in INDUSTRY_REGISTRY.items():
        for t in tickers:
            mapping[t.upper()] = industry
    with sqlite3.connect(str(CACHE_DB)) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO ticker_industry VALUES (?, ?)",
            mapping.items(),
        )
    return mapping


_TICKER_MAP: Optional[Dict[str, str]] = None


def classify_ticker_to_industry(ticker: str) -> Optional[str]:
    global _TICKER_MAP
    if _TICKER_MAP is None:
        _TICKER_MAP = _build_ticker_map()
    return _TICKER_MAP.get(ticker.upper())


def expand_industry(industry: str, n_top: int = 20) -> List[str]:
    """Get the top N tickers from an industry. Supports aliases."""
    # Common aliases
    aliases = {
        "ai": "semiconductors",
        "tech": "software",
        "crypto": "fintech",
        "ag": "agriculture_corn",
        "mining": "copper_miners",
        "energy": "petroleum_producers",
    }
    industry = aliases.get(industry.lower(), industry)
    tickers = INDUSTRY_REGISTRY.get(industry, [])
    if not tickers:
        # Try partial match
        for ind_name, tks in INDUSTRY_REGISTRY.items():
            if (
                industry.lower() in ind_name.lower()
                or ind_name.lower() in industry.lower()
            ):
                tickers = tks
                break
    return tickers[:n_top]


def load_industry_alt_data() -> dict:
    """Load industry->alt_data bindings. Returns {industry: {tools: [...]}}."""
    bindings = {}
    yaml_path = PROJECT / "config" / "industry_alt_data.yaml"
    if yaml_path.exists():
        try:
            import yaml

            bindings = yaml.safe_load(yaml_path.read_text()) or {}
        except ImportError:
            try:
                bindings = json.loads(yaml_path.read_text())
            except Exception:
                pass

    # Default bindings (hardcoded — override via YAML)
    defaults = {
        "petroleum_producers": {"tools": [{"get_eia_inventory": "petroleum"}]},
        "natural_gas": {"tools": [{"get_eia_inventory": "natural_gas"}]},
        "refiners": {"tools": [{"get_eia_inventory": "petroleum"}]},
        "copper_miners": {"tools": [{"get_minerals": "copper"}]},
        "iron_miners": {"tools": [{"get_minerals": "iron"}]},
        "uranium_miners": {"tools": [{"get_minerals": "uranium"}]},
        "lithium": {"tools": [{"get_minerals": "lithium"}]},
        "coal": {"tools": [{"get_minerals": "coal"}]},
        "agriculture_corn": {
            "tools": [
                {"get_weather": "corn_belt"},
                {"get_crop_progress": "CORN"},
                {"get_drought_signal": "us"},
            ]
        },
        "agriculture_wheat": {
            "tools": [
                {"get_weather": "corn_belt"},
                {"get_crop_progress": "WHEAT"},
                {"get_drought_signal": "us"},
            ]
        },
        "agriculture_soybean": {
            "tools": [
                {"get_weather": "corn_belt"},
                {"get_crop_progress": "SOYBEANS"},
                {"get_drought_signal": "us"},
            ]
        },
        "electric_utilities": {"tools": [{"get_eia_inventory": "natural_gas"}]},
    }

    # Merge YAML overrides with defaults
    for ind in INDUSTRY_REGISTRY:
        if ind not in bindings:
            bindings[ind] = defaults.get(ind, {"tools": []})
        elif ind in defaults:
            # YAML takes precedence, defaults fill gaps
            existing_tools = {
                (list(t.keys())[0] if t else ""): t
                for t in bindings[ind].get("tools", [])
            }
            for dt in defaults[ind].get("tools", []):
                key = list(dt.keys())[0]
                if key not in existing_tools:
                    bindings[ind].setdefault("tools", []).append(dt)

    # Sanity check: every registry industry has an entry
    for ind in INDUSTRY_REGISTRY:
        if ind not in bindings:
            bindings[ind] = {"tools": []}
    return bindings


# ── Universe tickers (replace hardcoded list) ──

_UNIVERSE_CACHE = None


def get_universe_tickers() -> List[str]:
    global _UNIVERSE_CACHE
    if _UNIVERSE_CACHE is None:
        # Radar spans the full curated industry registry (511 tickers), not
        # just the 66-symbol TRADABLE_UNIVERSE. The 66 was the synthetic-data
        # era's start-price table; on real prices (kraken+finnhub) every
        # registered name is priceable, and the scout LLM-curates 511→20→6
        # each cycle anyway. See docs/agents/research/alpha-*.md.
        registered = set()
        for tickers in INDUSTRY_REGISTRY.values():
            registered.update(t.upper() for t in tickers)
        _UNIVERSE_CACHE = sorted(registered)
    return _UNIVERSE_CACHE
