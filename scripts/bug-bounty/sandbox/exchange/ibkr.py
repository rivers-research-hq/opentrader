#!/usr/bin/env python3
"""IBKR Exchange — Interactive Brokers paper/demo account adapter.

Uses ib_insync for IB Gateway/TWS connection. Fetches real market data
from IBKR; executes paper trades on an in-memory ledger (same pattern
as LiveExchange and FinnhubExchange). Falls back to yfinance for OHLCV
when IBKR connection is unavailable.

Fees sourced from state/context.py FEE_TABLES["ibkr"]:
  - Stocks: $0.35/trade (min $0.35)
  - Crypto: 0.18% taker (Paxos), min $1.75
  - Forex: spread-based (no commission)
  - Futures: $0.85/contract
  - Options: $0.65/contract

Usage:
    export IBKR_HOST="127.0.0.1"        # default
    export IBKR_PORT="7497"             # TWS paper (7496=live)
    export IBKR_CLIENT_ID="1"
    python3 harness.py --exchange ibkr --symbol AAPL
"""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .base import ExchangeBase, OHLCV, OrderResult, Balance, register_exchange

logger = logging.getLogger("opentrader.ibkr")

# ib_insync contract types by asset class
_CONTRACT_TYPE = {
    "STK": "Stock",
    "CRYPTO": "Crypto",
    "CASH": "Forex",
    "FUT": "Future",
    "OPT": "Option",
}

# yfinance interval mapping for OHLCV fallback
_YF_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "1h", "1d": "1d", "1w": "1wk", "1M": "1mo",
}

# yfinance period mapping for different timeframes
_YF_PERIOD_MAP = {
    "1m": "7d", "5m": "1mo", "15m": "1mo", "30m": "1mo",
    "1h": "1mo", "4h": "3mo", "1d": "6mo", "1w": "1y", "1M": "2y",
}

_SECTOR_MAP = {
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "GOOGL": "tech",
    "META": "tech", "AMZN": "consumer", "TSLA": "consumer",
    "JPM": "finance", "BAC": "finance", "GS": "finance",
    "XOM": "energy", "CVX": "energy", "JNJ": "healthcare",
    "PFE": "healthcare", "UNH": "healthcare", "WMT": "consumer",
    "V": "finance", "MA": "finance", "PG": "consumer", "HD": "consumer",
    "DIS": "communication", "NFLX": "communication", "SPY": "etf",
    "QQQ": "etf", "TLT": "bond", "GLD": "commodity", "SONY": "consumer",
}


class IBKRExchange(ExchangeBase):
    """IBKR paper/demo account using ib_insync for market data.

    Connects to TWS/IB Gateway for real-time quotes and historical bars.
    Order execution is paper (in-memory ledger) — no real money.

    Gracefully degrades to yfinance for OHLCV when IBKR is unavailable.
    """

    ASSET_CLASS_MAP = {
        "STK": "stock",
        "ETF": "stock",
        "CRYPTO": "crypto",
        "CASH": "forex",
        "FUT": "futures",
        "OPT": "options",
        "BOND": "bond",
    }

    def __init__(self, name: str = "ibkr", config: dict = None):
        super().__init__(name, config)
        config = config or {}

        # Connection params
        self._host = config.get("host") or os.environ.get("IBKR_HOST", "127.0.0.1")
        self._port = int(config.get("port") or os.environ.get("IBKR_PORT", "7497"))
        self._client_id = int(config.get("client_id") or os.environ.get("IBKR_CLIENT_ID", "1"))
        self._ib = None
        self._fallback_mode: bool = False

        # Paper ledger state
        self._cash: float = float(config.get("initial_cash", 100_000))
        self._positions: Dict[str, float] = {}
        self._cost_basis: Dict[str, float] = {}
        self._fills: List[dict] = []
        self._order_counter: int = 1

        # Cache
        self._bar_cache: Dict[str, List[OHLCV]] = {}
        self._price_cache: Dict[str, float] = {}
        self._cache_ttl: float = float(config.get("cache_ttl", 30.0))
        self._last_fetch: Dict[str, float] = {}

    def connect(self) -> bool:
        try:
            from ib_insync import IB
            self._ib = IB()
            self._ib.connect(self._host, self._port, clientId=self._client_id, timeout=10)
            self._connected = True
            logger.info(f"IBKR: connected to {self._host}:{self._port} (client={self._client_id})")
            return True
        except Exception as e:
            logger.warning(f"IBKR connect failed ({e}) — DEGRADED: running on yfinance fallback (no live TWS).")
            self._connected = True   # yfinance fallback mode — functional without TWS
            self._fallback_mode = True
            self._ib = None
            return True              # don't trigger harness-level fallback to paper

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
        self._connected = False
        self._ib = None
        logger.info("IBKR: disconnected")

    def _infer_contract(self, symbol: str):
        """Build ib_insync contract from symbol string.

        Convention:
          - "AAPL" → Stock("AAPL", "SMART", "USD")
          - "BTC/USD" → Crypto("BTC", "PAXOS", "USD")  (IBKR crypto uses PAXOS)
          - "EUR/USD" → Forex("EURUSD")  (no '/' in forex)
        """
        from ib_insync import Stock, Crypto, Forex, Future, Option

        if "/" in symbol:
            base, quote = symbol.split("/", 1)
            if quote.upper() in ("USD", "USDT", "USDC"):
                if base.upper() in ("BTC", "ETH", "SOL", "LTC", "BCH"):
                    return Crypto(base.upper(), "PAXOS", "USD")
                return Crypto(base.upper(), "PAXOS", "USD")
            return Forex(f"{base}{quote}")

        return Stock(symbol, "SMART", "USD")

    def _classify_symbol(self, symbol: str) -> str:
        if "/" in symbol:
            base = symbol.split("/")[0].upper()
            if base in ("BTC", "ETH", "SOL", "LTC", "BCH"):
                return "crypto"
            return "forex"
        return "stock"

    def get_fee_schedule(self, symbol: str = "default") -> "FeeSchedule":
        from state.context import FEE_TABLES
        table = FEE_TABLES.get("ibkr", FEE_TABLES.get("paper", {}))
        asset_class = self._classify_symbol(symbol)
        return table.get(asset_class, table.get("stock", table.get("default", table.get("default", {}))))

    def get_current_price(self, symbol: str) -> Optional[float]:
        if symbol in self._price_cache:
            return self._price_cache[symbol]

        # Try IBKR ticker
        if self._connected and self._ib:
            try:
                contract = self._infer_contract(symbol)
                self._ib.qualifyContracts(contract)
                ticker = self._ib.reqMktData(contract, "", False, False)
                self._ib.sleep(0.5)
                price = None
                if hasattr(ticker, "last") and ticker.last and ticker.last > 0:
                    price = float(ticker.last)
                elif hasattr(ticker, "close") and ticker.close and ticker.close > 0:
                    price = float(ticker.close)
                elif hasattr(ticker, "mid") and ticker.mid:
                    price = float(ticker.mid())
                elif hasattr(ticker, "bid") and hasattr(ticker, "ask") and ticker.bid and ticker.ask:
                    price = (float(ticker.bid) + float(ticker.ask)) / 2.0
                self._ib.cancelMktData(contract)
                if price and price > 0:
                    self._price_cache[symbol] = price
                    return price
            except Exception as e:
                logger.debug(f"IBKR ticker failed for {symbol}: {e}")

        # Try yfinance fallback
        try:
            import yfinance as yf
            clean = symbol.replace("/", "-").replace("USDT", "USD")
            df = yf.download(clean, period="1d", interval="1h", progress=False, auto_adjust=True)
            if not df.empty:
                price = float(df["Close"].values[-1])
                self._price_cache[symbol] = price
                return price
        except Exception as e:
            logger.debug(f"yfinance price failed for {symbol}: {e}")

        return self._price_cache.get(symbol)

    def get_bars(self, symbol: str, timeframe: str = "1h",
                 limit: int = 100) -> List[OHLCV]:
        cache_key = f"{symbol}:{timeframe}:{limit}"
        now_ts = time.time()
        if cache_key in self._bar_cache:
            if now_ts - self._last_fetch.get(cache_key, 0) < self._cache_ttl:
                return self._bar_cache[cache_key]

        bars: List[OHLCV] = []

        # Try IBKR historical data
        if self._connected and self._ib:
            try:
                bars = self._fetch_ibkr_bars(symbol, timeframe, limit)
            except Exception as e:
                logger.debug(f"IBKR bars failed for {symbol}: {e}")

        # Fallback to yfinance
        if not bars:
            try:
                bars = self._fetch_yfinance_bars(symbol, timeframe, limit)
            except Exception as e:
                logger.warning(f"yfinance bars failed for {symbol}: {e}")

        if bars:
            self._bar_cache[cache_key] = bars
            self._last_fetch[cache_key] = now_ts
            self._price_cache[symbol] = bars[-1].close

        return bars or self._bar_cache.get(cache_key, [])

    def _fetch_ibkr_bars(self, symbol: str, timeframe: str,
                         limit: int) -> List[OHLCV]:
        from ib_insync import util
        import pandas as pd

        contract = self._infer_contract(symbol)
        self._ib.qualifyContracts(contract)

        tf_map = {
            "1m": "1 min", "5m": "5 mins", "15m": "15 mins",
            "30m": "30 mins", "1h": "1 hour", "4h": "4 hours",
            "1d": "1 day", "1w": "1 week", "1M": "1 month",
        }
        bar_size = tf_map.get(timeframe, "1 hour")

        duration_map = {
            "1m": "1 D", "5m": "2 D", "15m": "3 D", "30m": "5 D",
            "1h": "1 M", "4h": "3 M", "1d": "6 M", "1w": "1 Y", "1M": "2 Y",
        }
        duration = duration_map.get(timeframe, "1 M")

        bars_raw = self._ib.reqHistoricalData(
            contract, endDateTime="", durationStr=duration,
            barSizeSetting=bar_size, whatToShow="TRADES",
            useRTH=True, formatDate=1,
        )
        df = util.df(bars_raw)
        if df is None or df.empty:
            return []

        bars = []
        for _, row in df.tail(limit).iterrows():
            ts_val = row.get("date")
            ts = int(pd.Timestamp(ts_val).timestamp()) if ts_val is not None else 0
            bars.append(OHLCV(
                timestamp=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
            ))
        return bars

    def _fetch_yfinance_bars(self, symbol: str, timeframe: str,
                             limit: int) -> List[OHLCV]:
        import yfinance as yf
        import pandas as pd

        clean = symbol.replace("/", "-")
        if "USDT" in clean or "USDC" in clean:
            clean = clean.replace("USDT", "USD").replace("USDC", "USD")

        yf_interval = _YF_INTERVAL_MAP.get(timeframe, "1h")
        period = _YF_PERIOD_MAP.get(timeframe, "1mo")

        df = yf.download(clean, period=period, interval=yf_interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        bars = []
        for idx, row in df.tail(limit + 5).iterrows():
            ts = int(idx.timestamp())
            try:
                bars.append(OHLCV(
                    timestamp=ts,
                    open=float(row["Open"].iloc[0]) if isinstance(row["Open"], pd.Series) else float(row["Open"]),
                    high=float(row["High"].iloc[0]) if isinstance(row["High"], pd.Series) else float(row["High"]),
                    low=float(row["Low"].iloc[0]) if isinstance(row["Low"], pd.Series) else float(row["Low"]),
                    close=float(row["Close"].iloc[0]) if isinstance(row["Close"], pd.Series) else float(row["Close"]),
                    volume=float(row["Volume"].iloc[0]) if isinstance(row["Volume"], pd.Series) else float(row["Volume"]),
                ))
            except (ValueError, TypeError, KeyError, AttributeError):
                continue
        return bars

    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = "market",
                    price: Optional[float] = None) -> OrderResult:
        fill_price = price or self.get_current_price(symbol)
        if not fill_price or fill_price <= 0:
            return OrderResult(
                order_id="", symbol=symbol, side=side,
                quantity=quantity, price=0, status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw={"error": "no price data"},
            )
        cost = fill_price * quantity

        if side.upper() == "BUY":
            if cost > self._cash:
                affordable_qty = self._cash / fill_price
                if affordable_qty <= 0:
                    return OrderResult(
                        order_id=f"ibkr_{self._order_counter}",
                        symbol=symbol, side=side, quantity=quantity,
                        price=fill_price, status="rejected",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        raw={"error": "insufficient cash"},
                    )
                quantity = affordable_qty
                cost = fill_price * quantity
            self._cash -= cost
            self._positions[symbol] = self._positions.get(symbol, 0) + quantity
            self._cost_basis[symbol] = self._cost_basis.get(symbol, 0) + cost

        elif side.upper() == "SELL":
            pos = self._positions.get(symbol, 0)
            if pos <= 0:
                return OrderResult(
                    order_id=f"ibkr_{self._order_counter}",
                    symbol=symbol, side=side, quantity=quantity,
                    price=fill_price, status="rejected",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw={"error": "no position"},
                )
            quantity = min(quantity, pos)
            self._cash += fill_price * quantity
            self._positions[symbol] -= quantity
            if self._positions[symbol] <= 0:
                del self._positions[symbol]
                self._cost_basis.pop(symbol, None)

        order_id = f"ibkr_{self._order_counter}"
        self._order_counter += 1
        fill = {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": round(quantity, 8), "price": fill_price,
            "cost": round(cost, 2), "cash_after": round(self._cash, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._fills.append(fill)
        return OrderResult(
            order_id=order_id, symbol=symbol, side=side,
            quantity=round(quantity, 8), price=fill_price,
            status="filled", timestamp=fill["timestamp"], raw=fill,
        )

    def get_balance(self) -> Balance:
        portfolio_value = self._cash
        for sym, qty in self._positions.items():
            price = self._price_cache.get(sym)
            if not price or price <= 0:
                price = self.get_current_price(sym) or 0
            portfolio_value += price * qty
        return Balance(
            cash=round(self._cash, 2),
            total_value=round(portfolio_value, 2),
            positions={k: round(v, 8) for k, v in self._positions.items()},
        )

    def get_fills(self) -> List[dict]:
        return self._fills

    def load_bars(self, symbol: str, bars: List[dict]) -> None:
        cache_key = f"{symbol}:1h:{len(bars)}"
        self._bar_cache[cache_key] = [OHLCV.from_dict(b) for b in bars]
        if self._bar_cache[cache_key]:
            self._price_cache[symbol] = self._bar_cache[cache_key][-1].close

    def reset(self, initial_cash: float = 100_000) -> None:
        self._cash = initial_cash
        self._positions.clear()
        self._cost_basis.clear()
        self._fills.clear()
        self._order_counter = 1

    def discover_symbols(self, max_symbols: int = 20) -> List[str]:
        """Discover tradable symbols from IBKR or return fallback watchlist.

        If connected to TWS/Gateway, queries for US stock contracts.
        Otherwise returns a curated list of ~20 highly liquid US stocks/ETFs.
        """
        _FALLBACK_SYMBOLS = [
            "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
            "META", "TSLA", "JPM", "BAC", "V", "MA", "WMT", "XOM",
            "JNJ", "UNH", "PFE", "HD", "DIS", "NFLX", "TLT", "GLD",
        ]
        if self._connected and self._ib:
            try:
                from ib_insync import Stock, util
                active = []
                for sym in _FALLBACK_SYMBOLS:
                    contract = Stock(sym, "SMART", "USD")
                    try:
                        details = self._ib.reqContractDetails(contract)
                        if details:
                            active.append(sym)
                    except Exception:
                        pass
                    if len(active) >= max_symbols:
                        break
                if active:
                    return active[:max_symbols]
            except Exception as e:
                logger.warning(f"IBKR discover_symbols failed: {e}")
        return _FALLBACK_SYMBOLS[:max_symbols]

    def get_sector(self, symbol: str) -> str:
        return _SECTOR_MAP.get(symbol.upper(), "unknown")


register_exchange("ibkr", IBKRExchange)
register_exchange("ibkr_stock", IBKRExchange)
register_exchange("interactive_brokers", IBKRExchange)
