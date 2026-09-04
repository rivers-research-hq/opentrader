#!/usr/bin/env python3
"""Alpaca Paper Exchange — real prices via Alpaca/yfinance, paper settlement.

Waterfall: Alpaca (if keys) -> yfinance (cached 5min) -> synthetic GBM.
Order execution: in-memory ledger (matches exchange/paper.py pattern).
"""

import json
import logging
import os
import sqlite3
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SimpleBar:
    """Anchored-synthetic OHLCV bar. timestamp is epoch SECONDS so harness
    bar consumers (which use datetime.fromtimestamp(ts)) work unchanged."""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0
    timestamp: int = 0
from typing import Dict, List, Optional
from .base import OrderResult

logger = logging.getLogger("opentrader.exchange.alpaca")

PROJECT = Path(__file__).resolve().parent.parent
CACHE_DB = PROJECT / "data" / "price_cache.db"
CONFIG = PROJECT / "config" / "alt_data_keys.json"

# Default industry median prices (fallback when no real data)
# Expanded from 45 to 150+ tickers — covers TRADABLE_UNIVERSE + INDUSTRY_REGISTRY
INDUSTRY_MEDIAN = {
    # ── Crypto (USD pairs) ──
    "BTC/USDT": 67000, "ETH/USDT": 3300, "SOL/USDT": 170,
    "XRP/USDT": 0.60, "DOGE/USDT": 0.15, "ADA/USDT": 0.45,
    "AVAX/USDT": 35, "DOT/USDT": 7, "LINK/USDT": 14, "MATIC/USDT": 0.70,
    "UNI/USDT": 8, "ATOM/USDT": 9, "LTC/USDT": 75, "FIL/USDT": 6, "APT/USDT": 9,
    "ARB/USDT": 1.2, "OP/USDT": 2.5, "NEAR/USDT": 5, "INJ/USDT": 25, "SUI/USDT": 1.8,
    # ── Forex majors ──
    "EUR/USD": 1.08, "GBP/USD": 1.27, "USD/JPY": 150, "AUD/USD": 0.66,
    "USD/CAD": 1.35, "USD/CHF": 0.88, "NZD/USD": 0.61,
    # ── Mega-cap tech ──
    "AAPL": 190, "NVDA": 120, "MSFT": 420, "GOOGL": 175, "AMZN": 200,
    "META": 500, "TSLA": 250, "NFLX": 650, "ADBE": 520, "CRM": 290,
    "ORCL": 120, "IBM": 140, "CSCO": 50, "HPQ": 35, "DELL": 115,
    # ── Financials ──
    "JPM": 200, "BAC": 40, "WFC": 55, "C": 60, "GS": 450, "MS": 95,
    "USB": 42, "PNC": 155, "SCHW": 75, "TFC": 38, "COF": 135, "BK": 55, "STT": 75,
    "V": 280, "MA": 470, "BRK.B": 410, "AIG": 75, "MET": 70, "PRU": 110,
    # ── Consumer / Retail ──
    "JNJ": 155, "PG": 165, "WMT": 70, "HD": 370, "DIS": 100,
    "KO": 62, "PEP": 175, "COST": 720, "MCD": 285, "SBUX": 95,
    "KO": 62, "PEP": 175, "PM": 110, "MO": 48, "CL": 90, "KMB": 135,
    # ── Energy ──
    "XOM": 115, "CVX": 155, "COP": 110, "EOG": 125, "OXY": 58,
    "SLB": 48, "HAL": 35, "BKR": 37, "LNG": 160, "VLO": 140, "MPC": 170, "PSX": 140,
    # ── Industrials ──
    "GE": 165, "MMM": 100, "HON": 200, "CAT": 340, "DE": 385,
    "LMT": 470, "RTX": 112, "BA": 180, "NOC": 470, "GD": 285,
    "UNP": 240, "CSX": 34, "NSC": 235, "WM": 205, "RSG": 190,
    "DAL": 48, "UAL": 52, "AAL": 15, "LUV": 28,
    # ── Healthcare ──
    "PFE": 28, "MRK": 115, "ABBV": 170, "LLY": 780, "BMY": 48,
    "GILD": 72, "AMGN": 295, "VRTX": 410, "MRNA": 115, "BNTX": 100,
    "REGN": 920, "ABT": 108, "SYK": 340, "BSX": 68, "ISRG": 400,
    "UNH": 530, "CI": 330, "HUM": 380, "CNC": 72, "ELV": 520,
    # ── Semiconductors ──
    "AMD": 150, "INTC": 32, "TSM": 175, "AVGO": 140, "QCOM": 175,
    "MU": 95, "TXN": 190, "AMAT": 200, "LRCX": 820, "ASML": 900,
    "ADI": 215, "MRVL": 68, "ON": 72, "MCHP": 88, "MPWR": 720, "NXPI": 240,
    # ── Software / Cloud ──
    "NOW": 780, "SNOW": 155, "PLTR": 25, "PANW": 315, "CRWD": 320,
    "ZS": 185, "DDOG": 120, "MDB": 285, "WDAY": 260, "TEAM": 200,
    "OKTA": 90, "DT": 48, "NET": 85,
    # ── Fintech / Crypto-adjacent ──
    "SQ": 72, "PYPL": 68, "COIN": 210, "AFRM": 38, "SOFI": 8, "HOOD": 18,
    "NU": 12, "FIS": 70, "FI": 155, "TOST": 28,
    # ── Autos / EVs ──
    "F": 12, "GM": 45, "RIVN": 13, "LCID": 4, "TM": 185, "STLA": 22,
    "NIO": 6, "XPEV": 9, "LI": 25,
    # ── Metals / Mining ──
    "FCX": 45, "BHP": 60, "RIO": 80, "NEM": 42, "GOLD": 17, "AEM": 65,
    "KGC": 8, "GFI": 17, "WPM": 58, "VALE": 12, "CLF": 18, "NUE": 155,
    "STLD": 128, "X": 40, "ALB": 110, "SQM": 42, "LAC": 5,
    "CCJ": 48, "UEC": 7, "DNN": 1.8, "UUUU": 6, "NXE": 8,
    # ── Materials / Chemicals ──
    "LIN": 430, "APD": 280, "DOW": 55, "DD": 78, "LYB": 95,
    "NTR": 55, "CF": 78, "MOS": 32, "FMC": 60,
    # ── Homebuilders / Real Estate ──
    "DHI": 155, "LEN": 160, "PHM": 115, "TOL": 130, "NVR": 7800,
    # ── Gaming / Media ──
    "SONY": 90, "LVS": 48, "WYNN": 95, "MGM": 42, "CZR": 42, "DKNG": 38,
    "BABA": 78, "JD": 28, "MELI": 1650, "SE": 72, "SHOP": 68, "PDD": 130,
    # ── E-commerce / Internet ──
    "ETSY": 65, "CPNG": 22, "CART": 38,
    # ── Restaurants ──
    "CMG": 55, "YUM": 135, "DRI": 165, "DPZ": 440, "QSR": 72, "WEN": 18,
    # ── Regional Banks ──
    "CFG": 36, "KEY": 15, "FITB": 38, "HBAN": 14, "RF": 21,
    "ZION": 44, "EWBC": 78, "WAL": 65, "CMA": 52,
    # ── Commodity / Sector ETFs ──
    "SPY": 550, "QQQ": 470, "GLD": 220, "SLV": 28, "USO": 75, "UNG": 3.5,
    "CORN": 35, "WEAT": 50, "SOYB": 28, "DBA": 25,
    "PICK": 55, "XLE": 95, "XOP": 40, "KOL": 20, "LIT": 60, "URNM": 25,
    "XHB": 95, "KRE": 52, "XBI": 90, "JETS": 20, "GDX": 35, "SMH": 230,
    "URA": 30, "SLX": 65,
}


@dataclass
class Balance:
    cash: float = 0.0
    equity: float = 0.0
    total_value: float = 0.0
    positions: Dict[str, float] = None

    def __post_init__(self):
        if self.positions is None:
            self.positions = {}


class AlpacaPaperExchange:
    """Paper exchange with Alpaca/yfinance real prices."""

    def __init__(self, initial_cash: float = 100000.0):
        self.cash = initial_cash
        self.name = "alpaca-paper"
        self.positions: Dict[str, float] = {}
        self.trades: list = []
        self.fee_rate = 0.0005  # 5bps
        self._bars: Dict[str, list] = {}
        self._alpaca_key = ""
        self._alpaca_secret = ""
        self._yfinance_calls = 0
        self._yfinance_reset = time.time()
        self._order_counter: int = 1
        self._load_keys()
        self._init_cache()

    def _load_keys(self):
        if CONFIG.exists():
            try:
                keys = json.loads(CONFIG.read_text())
                self._alpaca_key = keys.get("ALPACA_KEY", "")
                self._alpaca_secret = keys.get("ALPACA_SECRET", "")
            except Exception:
                pass

    def _init_cache(self):
        os.makedirs(CACHE_DB.parent, exist_ok=True)
        with sqlite3.connect(str(CACHE_DB)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prices "
                "(symbol TEXT PRIMARY KEY, price REAL, source TEXT, fetched_at REAL)"
            )

    def _cached_price(self, symbol: str) -> Optional[float]:
        with sqlite3.connect(str(CACHE_DB)) as conn:
            row = conn.execute(
                "SELECT price, fetched_at FROM prices WHERE symbol=?",
                (symbol.upper(),),
            ).fetchone()
        if row:
            price, ts = row
            if time.time() - ts < 600:  # 10min TTL
                return price
        return None

    def _cache_price(self, symbol: str, price: float, source: str):
        with sqlite3.connect(str(CACHE_DB)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?)",
                (symbol.upper(), price, source, time.time()),
            )

    def _fetch_yfinance(self, symbol: str) -> Optional[float]:
        if self._yfinance_calls >= 100 and time.time() - self._yfinance_reset < 60:
            logger.debug(f"yfinance rate cap hit — using fallback for {symbol}")
            return None
        self._yfinance_calls += 1
        if time.time() - self._yfinance_reset > 3600:
            self._yfinance_calls = 0
            self._yfinance_reset = time.time()
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            if price and price > 0:
                return float(price)
        except Exception as e:
            logger.debug(f"yfinance fetch failed for {symbol}: {e}")
        return None

    def _fetch_alpaca(self, symbol: str) -> Optional[float]:
        if not self._alpaca_key:
            return None
        try:
            url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
            req = Request(url, headers={
                "APCA-API-KEY-ID": self._alpaca_key,
                "APCA-API-SECRET-KEY": self._alpaca_secret,
            })
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                quote = data.get("quote", {})
                price = quote.get("ap") or quote.get("bp")
                if price and price > 0:
                    return float(price)
        except Exception as e:
            logger.debug(f"Alpaca fetch failed for {symbol}: {e}")
        return None

    def connect(self):
        """No-op — Alpaca uses stateless REST calls."""
        return True

    def get_current_price(self, symbol: str) -> float:
        symbol = symbol.upper()
        # 1. Cache hit
        cached = self._cached_price(symbol)
        if cached:
            return cached

        # 2. Alpaca
        price = self._fetch_alpaca(symbol)
        if price:
            self._cache_price(symbol, price, "alpaca")
            return price

        # 3. yfinance
        price = self._fetch_yfinance(symbol)
        if price:
            self._cache_price(symbol, price, "yfinance")
            return price

        # 4. Industry median fallback
        return INDUSTRY_MEDIAN.get(symbol, 100.0)

    def get_prices_batch(self, symbols: list) -> dict:
        """Fetch multiple prices in one batch (Alpaca or yfinance)."""
        result = {}
        remaining = list(symbols)

        # 1. Check cache
        for sym in list(remaining):
            cached = self._cached_price(sym)
            if cached:
                result[sym] = cached
                remaining.remove(sym)
        if not remaining:
            return result

        # 2. Alpaca batch (max 200 per call)
        if self._alpaca_key:
            try:
                chunked = ','.join(remaining[:200])
                url = f"https://data.alpaca.markets/v2/stocks/quotes?symbols={chunked}"
                req = Request(url, headers={
                    "APCA-API-KEY-ID": self._alpaca_key,
                    "APCA-API-SECRET-KEY": self._alpaca_secret,
                })
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    for sym, q in (data.get("quotes", {}) or {}).items():
                        price = q.get("ap") or q.get("bp") or q.get("latest_trade", {}).get("p")
                        if price and price > 0:
                            result[sym] = float(price)
                            self._cache_price(sym, float(price), "alpaca")
                            if sym in remaining:
                                remaining.remove(sym)
            except Exception as e:
                logger.debug(f"Alpaca batch fetch failed: {e}")

        # 3. yfinance fallback per remaining symbol
        for sym in remaining:
            price = self._fetch_yfinance(sym)
            if price:
                result[sym] = price
                self._cache_price(sym, price, "yfinance")
            else:
                result[sym] = INDUSTRY_MEDIAN.get(sym, 100.0)

        return result

    def get_bars(self, symbol: str, timeframe: str = "1h", limit: int = 80,
                 seed_offset: int = 0) -> List[SimpleBar]:
        """Return OHLCV bars. Uses synthetic GBM anchored by real price."""
        key = f"{symbol}:{timeframe}"
        if seed_offset == 0 and key in self._bars and len(self._bars[key]) >= limit:
            return self._bars[key][-limit:]

        cached = self._cached_price(symbol)
        real_price = cached or INDUSTRY_MEDIAN.get(symbol.upper(), 100.0)
        import random, math
        seed_val = hash(key) % (2**31)
        if seed_offset:
            seed_val = (seed_val * 16807 + seed_offset) % (2**31)
        random.seed(seed_val)

        bars = []
        price = real_price
        import time as _time
        now = _time.time()
        for i in range(limit):
            ret = random.gauss(0.0001, 0.01)
            price *= (1 + ret)
            o = price
            c = o * (1 + random.gauss(0, 0.005))
            h = max(o, c) * (1 + abs(random.gauss(0, 0.003)))
            l = min(o, c) * (1 - abs(random.gauss(0, 0.003)))
            v = max(100, int(random.gauss(5000, 2000)))
            bars.append(SimpleBar(open=o, high=h, low=l, close=c, volume=v,
                                  timestamp=int(now) - (limit - i) * 3600))

        self._bars[key] = bars
        return bars[-limit:]

    def push_bar(self, symbol: str, bar: dict):
        """Push a new OHLCV bar (called per-cycle by harness)."""
        key = f"{symbol}:1h"
        if key not in self._bars:
            self._bars[key] = []
        b = bar[0] if isinstance(bar, list) else bar
        import time as _time
        self._bars[key].append(SimpleBar(
            open=float(b.get("open", b.get("o", 0))),
            high=float(b.get("high", b.get("h", 0))),
            low=float(b.get("low", b.get("l", 0))),
            close=float(b.get("close", b.get("c", 0))),
            volume=float(b.get("volume", 0)),
            timestamp=int(b.get("timestamp", b.get("t", _time.time()))),
        ))

    def load_bars(self, symbol: str, bars: list):
        key = f"{symbol}:1h"
        if key not in self._bars:
            self._bars[key] = []
        for b in bars:
            import time as _time
            if isinstance(b, dict):
                self._bars[key].append(SimpleBar(
                    open=float(b.get("open", 0)),
                    high=float(b.get("high", 0)),
                    low=float(b.get("low", 0)),
                    close=float(b.get("close", 0)),
                    volume=float(b.get("volume", 0)),
                    timestamp=int(b.get("timestamp", b.get("t", _time.time()))),
                ))
            elif hasattr(b, "close"):
                self._bars[key].append(SimpleBar(
                    open=getattr(b, "open", 0),
                    high=getattr(b, "high", 0),
                    low=getattr(b, "low", 0),
                    close=getattr(b, "close", 0),
                    volume=getattr(b, "volume", 0),
                    timestamp=int(getattr(b, "timestamp", getattr(b, "t", _time.time()))),
                ))

    def get_balance(self) -> Balance:
        bal = Balance(cash=self.cash, total_value=self.cash)
        for sym, qty in self.positions.items():
            price = self.get_current_price(sym)
            val = qty * price
            bal.equity += val
            bal.total_value += val
            bal.positions[sym] = qty
        return bal

    def submit_order(self, symbol: str, quantity: float, side: str) -> dict:
        price = self.get_current_price(symbol)
        cost = quantity * price
        fee = max(0.01, cost * self.fee_rate)

        if side.upper() == "BUY":
            if cost + fee > self.cash:
                quantity = (self.cash - fee) / price
                cost = quantity * price
            self.cash -= cost + fee
            self.positions[symbol] = self.positions.get(symbol, 0) + quantity
        else:  # SELL
            available = self.positions.get(symbol, 0)
            quantity = min(quantity, available)
            if quantity <= 0:
                return {"status": "rejected", "reason": "no position"}
            self.cash += cost - fee
            self.positions[symbol] = self.positions.get(symbol, 0) - quantity
            if self.positions[symbol] <= 0:
                del self.positions[symbol]

        trade = {
            "symbol": symbol, "quantity": quantity, "side": side.upper(),
            "price": price, "cost": cost, "fee": fee, "cash_after": self.cash,
        }
        self.trades.append(trade)
        return {"status": "filled", **trade}

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        result = self.submit_order(symbol, quantity, side)
        oid = f"alp-{self._order_counter:06d}"
        self._order_counter += 1
        return OrderResult(
            order_id=oid,
            symbol=symbol,
            side=side.upper(),
            quantity=result.get("quantity", quantity),
            price=result.get("price", 0),
            status=result.get("status", "rejected"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw=result,
        )

    def reset(self, initial_cash: float = 100000.0):
        self.cash = initial_cash
        self.positions.clear()
        self.trades.clear()
        self._bars.clear()

    def discover_symbols(self) -> List[str]:
        """Return known symbols from loaded bars, cache, and defaults."""
        symbols = set()
        for key in self._bars:
            sym = key.split(":")[0]
            if sym:
                symbols.add(sym)
        symbols.update(INDUSTRY_MEDIAN.keys())
        try:
            conn = sqlite3.connect(str(CACHE_DB))
            rows = conn.execute("SELECT DISTINCT symbol FROM price_cache").fetchall()
            symbols.update(r[0] for r in rows if r[0])
            conn.close()
        except Exception:
            pass
        return sorted(symbols)
