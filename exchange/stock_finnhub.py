#!/usr/bin/env python3
"""Finnhub Stock Exchange — free OHLCV data for US equities.

Paper execution on real market data. No real money leaves the system.
Finnhub free tier: 60 API calls/minute, all US stocks, real-time quotes.

Usage:
    export FINNHUB_API_KEY="your_key"
    python3 harness.py --exchange finnhub --symbol AAPL

This adapter follows the same ExchangeBase interface as LiveExchange (crypto).
Once registered, use --exchange finnhub exactly like --exchange kraken.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

import pandas as pd
from urllib.error import URLError

from .base import ExchangeBase, OHLCV, OrderResult, Balance, register_exchange

logger = logging.getLogger("opentrader.finnhub")

# Lazy-imported when use_realtime=True
_RealtimeFeed: Optional[type] = None

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Finnhub resolution string -> candlestick resolution code
_RESOLUTION_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "1d": "D",
    "1w": "W",
}

# Default rate limit for free tier (60 calls/min -> 1 call/sec safe)
DEFAULT_RATE_LIMIT = 1.0  # seconds between calls


class FinnhubExchange(ExchangeBase):
    """US stock exchange adapter using Finnhub free API.

    Fetches real price data from Finnhub. Order execution is paper (in-memory ledger).
    """

    def __init__(self, name: str = "finnhub", config: dict = None):
        super().__init__(name, config)
        config = config or {}

        # Read key from connections store first, then env var, then config
        self._api_key = (
            config.get("api_key")
            or self._read_key_from_store()
            or os.environ.get("FINNHUB_API_KEY", "")
        )
        if not self._api_key:
            logger.error(
                "FinnhubExchange: FINNHUB_API_KEY not set. "
                "Add your key in the dashboard Connections tab or set the env var. "
                "Exchange will not connect."
            )
            self._connected = False  # grace degrade — harness falls back

        # Paper ledger state (same pattern as LiveExchange/PaperExchange)
        self._cash: float = float(config.get("initial_cash", 100_000))
        self._positions: Dict[str, float] = {}
        self._cost_basis: Dict[str, float] = {}
        self._fills: List[dict] = []
        self._order_counter: int = 1

        # Cache
        self._bar_cache: Dict[str, List[OHLCV]] = {}
        self._price_cache: Dict[str, float] = {}
        self._cache_ttl: float = config.get("cache_ttl", 1200.0)
        self._last_fetch: Dict[str, float] = {}
        self._last_api_call: float = 0.0
        self._rate_limit: float = float(config.get("rate_limit", DEFAULT_RATE_LIMIT))

        # Delisting filter: symbols that return no data anywhere get marked
        # dead for 24h so the scanner stops burning API calls on them.
        self._dead_symbols: Dict[str, float] = {}
        self._dead_ttl: float = 24 * 3600.0

        # Realtime WebSocket feed (optional — free-tier friendly)
        self._use_realtime: bool = bool(config.get("use_realtime", False))
        self._watchlist: List[str] = config.get("watchlist", []) or []
        self._realtime: Optional[Any] = None

        # Alpaca data API (free tier) — used FIRST for bars and batch quotes;
        # finnhub + yfinance act as fallback. Keys optional: without them the
        # adapter behaves exactly as before.
        self._alpaca_key = ""
        self._alpaca_secret = ""
        self._load_alpaca_keys()

    def _load_alpaca_keys(self):
        """Read free Alpaca data API keys from config/alt_data_keys.json or env."""
        try:
            from pathlib import Path

            cfg_path = (
                Path(__file__).resolve().parent.parent / "config" / "alt_data_keys.json"
            )
            if cfg_path.exists():
                keys = json.loads(cfg_path.read_text())
                self._alpaca_key = keys.get("ALPACA_KEY", "")
                self._alpaca_secret = keys.get("ALPACA_SECRET", "")
        except Exception:
            pass
        if not self._alpaca_key:
            self._alpaca_key = os.environ.get("ALPACA_KEY", "")
            self._alpaca_secret = os.environ.get("ALPACA_SECRET", "")
        if self._alpaca_key:
            logger.info("FinnhubExchange: Alpaca data API keys present (primary source)")

    @staticmethod
    def _read_key_from_store() -> str:
        try:
            from connections import get_api_key

            return get_api_key("finnhub")
        except ImportError:
            return ""

    def connect(self) -> bool:
        if not self._api_key:
            logger.error("FinnhubExchange: no API key set")
            return False
        try:
            url = f"{FINNHUB_BASE}/quote?symbol=AAPL&token={self._api_key}"
            with urlopen(Request(url), timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if "c" in data:
                    self._connected = True
                    logger.info("FinnhubExchange: connected (free tier, 60 calls/min)")
                    if self._use_realtime:
                        self._start_realtime()
                    return True
                logger.error(f"Finnhub auth failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Finnhub connect failed: {e}")
            return False

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_api_call
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)

    # ── Alpaca data API (free, primary source) ──────────────────

    _ALPACA_TF = {
        "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
        "1h": "1Hour", "4h": "4Hour", "1d": "1Day", "1w": "1Week", "1M": "1Month",
    }

    def _alpaca_headers(self):
        return {
            "APCA-API-KEY-ID": self._alpaca_key,
            "APCA-API-SECRET-KEY": self._alpaca_secret,
        }

    def _fetch_alpaca_bars(
        self, symbol: str, timeframe: str, limit: int
    ) -> List[OHLCV]:
        """Real OHLCV bars from Alpaca's data API (free tier). Empty on failure."""
        if not self._alpaca_key:
            return []
        tf = self._ALPACA_TF.get(timeframe)
        if not tf:
            return []
        try:
            url = (
                f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
                f"?timeframe={tf}&limit={limit}&adjust=all"
            )
            with urlopen(Request(url, headers=self._alpaca_headers()), timeout=15) as resp:
                data = json.loads(resp.read().decode())
            bars = data.get("bars") or []
            out = []
            for b in bars:
                try:
                    ts = int(datetime.fromisoformat(b["t"].replace("Z", "+00:00")).timestamp())
                except Exception:
                    continue
                out.append(
                    OHLCV(
                        timestamp=ts,
                        open=float(b["o"]),
                        high=float(b["h"]),
                        low=float(b["l"]),
                        close=float(b["c"]),
                        volume=float(b.get("v", 0)),
                    )
                )
            return out
        except Exception as e:
            logger.debug(f"Alpaca bars failed for {symbol}: {e}")
            return []

    def _fetch_alpaca_batch_quotes(self, symbols: list, chunk: int = 200) -> dict:
        """Batch latest quotes — up to 200 symbols per call."""
        if not self._alpaca_key or not symbols:
            return {}
        result = {}
        try:
            for i in range(0, len(symbols), chunk):
                chunked = ",".join(symbols[i : i + chunk])
                url = f"https://data.alpaca.markets/v2/stocks/quotes?symbols={chunked}"
                with urlopen(Request(url, headers=self._alpaca_headers()), timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                for sym, q in (data.get("quotes") or {}).items():
                    price = q.get("ap") or q.get("bp")
                    if price and price > 0:
                        result[sym] = float(price)
        except Exception as e:
            logger.debug(f"Alpaca batch quotes failed: {e}")
        return result

    def _fetch_alpaca_latest_quote(self, symbol: str) -> Optional[float]:
        """Latest quote for a single symbol."""
        if not self._alpaca_key:
            return None
        try:
            url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
            with urlopen(Request(url, headers=self._alpaca_headers()), timeout=15) as resp:
                data = json.loads(resp.read().decode())
            q = data.get("quote") or {}
            price = q.get("ap") or q.get("bp")
            return float(price) if price and price > 0 else None
        except Exception as e:
            logger.debug(f"Alpaca latest quote failed for {symbol}: {e}")
            return None

    def _start_realtime(self) -> None:
        """Launch the WebSocket realtime feed (non-blocking)."""
        try:
            from .realtime_finnhub import FinnhubRealtimeFeed

            self._realtime = FinnhubRealtimeFeed(self, self._watchlist, self.config)
            self._realtime.start()
            logger.info("FinnhubExchange: realtime feed started")
        except ImportError:
            logger.warning(
                "FinnhubExchange: websocket-client not installed — "
                "realtime feed disabled.  Install with: pip install websocket-client"
            )
            self._use_realtime = False
        except Exception as exc:
            logger.warning("FinnhubExchange: realtime feed failed to start: %s", exc)
            self._use_realtime = False

    def _is_dead(self, symbol: str) -> bool:
        """True while `symbol` is within its delisting skip window."""
        marked = self._dead_symbols.get(symbol, 0.0)
        if marked and (time.time() - marked) < self._dead_ttl:
            return True
        if marked:
            self._dead_symbols.pop(symbol, None)  # window expired — retry
        return False

    def _mark_dead(self, symbol: str) -> None:
        self._dead_symbols[symbol] = time.time()
        logger.info(f"delisting filter: {symbol} gave no data — skipping 24h")

    def _api_get(self, path: str, params: dict = None) -> dict:
        """Call Finnhub REST API with rate limiting."""
        params = params or {}
        params["token"] = self._api_key
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{FINNHUB_BASE}{path}?{qs}"

        self._rate_limit_wait()
        req = Request(url)
        req.add_header("User-Agent", "OpenTrader/1.0")
        try:
            with urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
                return json.loads(raw)
        except URLError as e:
            if hasattr(e, "code") and e.code == 403:
                logger.debug(f"Finnhub 403 (free tier): {e}")
            else:
                logger.error(f"Finnhub API error: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Finnhub bad JSON: {e}")
            return {}

    # ── OHLCV ────────────────────────────────────────────────

    def _resolution_code(self, timeframe: str) -> Optional[str]:
        """Map timeframe string to Finnhub resolution code."""
        return _RESOLUTION_MAP.get(timeframe)

    def _compute_from_timestamp(self, timeframe: str, limit: int) -> int:
        """Compute 'from' unix timestamp for N candles back."""
        now = int(time.time())
        tf_minutes = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "1d": 1440,
            "1w": 10080,
        }
        minutes = tf_minutes.get(timeframe, 60)
        return now - (limit * minutes * 60)

    # yfinance interval mapping for OHLCV fallback
    _YF_INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "1h",
        "1d": "1d",
        "1w": "1wk",
        "1M": "1mo",
    }

    def get_bars(
        self, symbol: str = "AAPL", timeframe: str = "1h", limit: int = 100
    ) -> List[OHLCV]:
        cache_key = f"{symbol}:{timeframe}:{limit}"
        if self._is_dead(symbol):
            return self._bar_cache.get(cache_key, [])
        now_ts = time.time()
        if cache_key in self._bar_cache:
            if now_ts - self._last_fetch.get(cache_key, 0) < self._cache_ttl:
                return self._bar_cache[cache_key]

        bars: List[OHLCV] = []

        # Alpaca bars first — free, reliable, and finnhub's candle API is
        # premium-gated, so without this the harness fell back to yfinance.
        if self._alpaca_key:
            alpaca_bars = self._fetch_alpaca_bars(symbol, timeframe, limit)
            if len(alpaca_bars) >= 5:
                self._bar_cache[cache_key] = alpaca_bars
                self._last_fetch[cache_key] = now_ts
                self._price_cache[symbol] = alpaca_bars[-1].close
                return alpaca_bars

        # Try Finnhub candle API first (premium users only; free tier gets 403)
        if self._connected:
            resolution = self._resolution_code(timeframe)
            if resolution:
                from_ts = self._compute_from_timestamp(timeframe, limit)
                try:
                    data = self._api_get(
                        "/stock/candle",
                        {
                            "symbol": symbol,
                            "resolution": resolution,
                            "from": str(from_ts),
                            "to": str(int(time.time())),
                        },
                    )
                    if data.get("s") == "ok":
                        bars = self._parse_candle_bars(data)
                except Exception:
                    pass

        # Fallback: yfinance for free OHLCV (no API key needed)
        if not bars:
            try:
                bars = self._fetch_yfinance_bars(symbol, timeframe, limit)
            except Exception as e:
                logger.warning(f"yfinance bars failed for {symbol}: {e}")

        if bars:
            self._bar_cache[cache_key] = bars
            self._last_fetch[cache_key] = now_ts
            self._price_cache[symbol] = bars[-1].close
        else:
            self._mark_dead(symbol)

        logger.debug(f"Stock bars {symbol} ({timeframe}): {len(bars)} bars")
        return bars or self._bar_cache.get(cache_key, [])

    def _parse_candle_bars(self, data: dict) -> List[OHLCV]:
        timestamps = data.get("t", [])
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])
        bars = []
        for i in range(len(timestamps)):
            bars.append(
                OHLCV(
                    timestamp=timestamps[i],
                    open=float(opens[i]),
                    high=float(highs[i]),
                    low=float(lows[i]),
                    close=float(closes[i]),
                    volume=float(volumes[i]),
                )
            )
        return bars

    def _fetch_yfinance_bars(
        self, symbol: str, timeframe: str, limit: int
    ) -> List[OHLCV]:
        import yfinance as yf

        yf_interval = self._YF_INTERVAL_MAP.get(timeframe, "1h")
        period_map = {
            "1m": "7d",
            "5m": "1mo",
            "15m": "1mo",
            "30m": "1mo",
            "1h": "1mo",
            "4h": "3mo",
            "1d": "6mo",
            "1w": "1y",
            "1M": "2y",
        }
        period = period_map.get(timeframe, "1mo")
        df = yf.download(
            symbol,
            period=period,
            interval=yf_interval,
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            return []
        # Handle multi-level columns from yfinance (e.g. ('Open', 'AAPL'))
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        bars = []
        for idx, row in df.tail(limit + 5).iterrows():
            ts = int(idx.timestamp())
            bars.append(
                OHLCV(
                    timestamp=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )
        return bars

    def get_current_price(self, symbol: str) -> Optional[float]:
        if self._is_dead(symbol):
            return self._price_cache.get(symbol)
        # 1. WebSocket realtime (freshest; subscribe on first call)
        if self._realtime:
            self._realtime.subscribe([symbol])
            price = self._realtime.get_price(symbol)
            if price is not None:
                self._price_cache[symbol] = price
                return price

        # 2. REST cache (from earlier API calls or get_bars)
        if symbol in self._price_cache:
            return self._price_cache[symbol]

        # 2b. Alpaca latest quote (free, primary) — avoids a finnhub /quote call
        if self._alpaca_key:
            ap = self._fetch_alpaca_latest_quote(symbol)
            if ap is not None:
                self._price_cache[symbol] = ap
                return ap

        # 3. REST API call
        try:
            data = self._api_get("/quote", {"symbol": symbol})
            price = data.get("c")
            if price and price > 0:
                self._price_cache[symbol] = float(price)
                return float(price)
        except Exception as e:
            logger.debug(f"Finnhub quote failed for {symbol}: {e}")

        return self._price_cache.get(symbol)

    def get_prices_batch(self, symbols: list) -> dict:
        result = {}
        remaining = [s for s in symbols if not self._is_dead(s)]

        for sym in list(remaining):
            if sym in self._price_cache:
                result[sym] = self._price_cache[sym]
                remaining.remove(sym)

        if not remaining:
            return result

        # Alpaca batch quotes first — up to 200 symbols per call, so the whole
        # universe sweep collapses to a couple of requests (vs yfinance chunks).
        if self._alpaca_key:
            alpaca_quotes = self._fetch_alpaca_batch_quotes(remaining)
            for sym, price in alpaca_quotes.items():
                result[sym] = price
                self._price_cache[sym] = price
                if sym in remaining:
                    remaining.remove(sym)
            if not remaining:
                return result

        try:
            import yfinance as yf

            # Bounded chunks: yfinance is unreliable handing 500 tickers at
            # once (partial/empty returns, rate limiting). Chunk to ~60.
            chunk = 60
            for i in range(0, len(remaining), chunk):
                batch = remaining[i : i + chunk]
                try:
                    df = yf.download(
                        " ".join(batch),
                        period="1d",
                        interval="1d",
                        progress=False,
                        auto_adjust=True,
                        threads=True,
                    )
                except Exception as e:
                    logger.debug(f"yfinance batch chunk failed: {e}")
                    continue
                if df is None or df.empty:
                    continue
                for sym in batch:
                    try:
                        if isinstance(df.columns, pd.MultiIndex):
                            price = float(df["Close"][sym].dropna().iloc[-1])
                        else:
                            price = float(df["Close"].dropna().iloc[-1])
                        if price and price > 0:
                            result[sym] = price
                            self._price_cache[sym] = price
                            remaining.remove(sym)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"yfinance batch failed: {e}")

        # Bounded fallback: per-symbol finnhub quote is ~1s/call (free tier).
        # Don't burn minutes+429s pricing hundreds of yfinance misses — the
        # radar needs representative prices, not every ticker.
        fallback_attempts = 0
        tried_and_failed = []
        for sym in remaining:
            if fallback_attempts >= 40:
                break
            try:
                price = self.get_current_price(sym)
            except Exception:
                price = None
            if price:
                result[sym] = price
                fallback_attempts += 1
            else:
                tried_and_failed.append(sym)

        for sym in tried_and_failed:
            self._mark_dead(sym)

        return result

    # ── Paper execution ──────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> OrderResult:
        fill_price = price or self.get_current_price(symbol)
        if not fill_price or fill_price <= 0:
            return OrderResult(
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=0,
                status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw={"error": "no price data"},
            )
        # Simulate slippage: buys fill higher (ask), sells fill lower (bid)
        _slippage = 0.0005  # 5 bps half-spread
        if side.upper() == "BUY":
            fill_price = fill_price * (1.0 + _slippage)
        else:
            fill_price = fill_price * (1.0 - _slippage)
        cost = fill_price * quantity

        fee_schedule = self.get_fee_schedule(symbol)
        is_buy = side.upper() == "BUY"
        fee = fee_schedule.buy_cost(cost) if is_buy else fee_schedule.sell_cost(cost)

        if side.upper() == "BUY":
            if cost + fee > self._cash:
                affordable_qty = (self._cash - fee) / fill_price
                if affordable_qty <= 0:
                    return OrderResult(
                        order_id=f"fh_{self._order_counter}",
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=fill_price,
                        status="rejected",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        raw={"error": "insufficient cash"},
                    )
                quantity = affordable_qty
                cost = fill_price * quantity
                fee = fee_schedule.buy_cost(cost)
            self._cash -= cost + fee
            self._positions[symbol] = self._positions.get(symbol, 0) + quantity
            self._cost_basis[symbol] = self._cost_basis.get(symbol, 0) + cost

        elif side.upper() == "SELL":
            pos = self._positions.get(symbol, 0)
            if pos <= 0:
                return OrderResult(
                    order_id=f"fh_{self._order_counter}",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=fill_price,
                    status="rejected",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw={"error": "no position"},
                )
            quantity = min(quantity, pos)
            self._cash += fill_price * quantity - fee
            self._positions[symbol] -= quantity
            if self._positions[symbol] <= 0:
                del self._positions[symbol]
                self._cost_basis.pop(symbol, None)

        order_id = f"fh_{self._order_counter}"
        self._order_counter += 1
        fill = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": round(quantity, 8),
            "price": fill_price,
            "cost": round(cost, 2),
            "fee": round(fee, 2),
            "cash_after": round(self._cash, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._fills.append(fill)
        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=round(quantity, 8),
            price=fill_price,
            status="filled",
            timestamp=fill["timestamp"],
            raw=fill,
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
        """Pre-load OHLCV bars (for backtesting)."""
        cache_key = f"{symbol}:1h:{len(bars)}"
        self._bar_cache[cache_key] = [OHLCV.from_dict(b) for b in bars]
        if self._bar_cache[cache_key]:
            self._price_cache[symbol] = self._bar_cache[cache_key][-1].close

    def disconnect(self) -> None:
        if self._realtime:
            self._realtime.stop()
            self._realtime = None
        self._connected = False
        logger.info("FinnhubExchange: disconnected")

    def reset(self, initial_cash: float = 100_000) -> None:
        self._cash = initial_cash
        self._positions.clear()
        self._cost_basis.clear()
        self._fills.clear()
        self._order_counter = 1

    def discover_symbols(self, max_symbols: int = 20) -> List[str]:
        """Return US stock symbols from Finnhub."""
        if not self._connected or not self._api_key:
            return []
        try:
            data = self._api_get("/stock/symbol", {"exchange": "US", "mic": "XNYS"})
            if data and isinstance(data, list):
                syms = [item.get("symbol", "") for item in data if item.get("symbol")]
                return syms[:max_symbols] if max_symbols and max_symbols > 0 else syms
            return []
        except Exception as e:
            logger.warning(f"Finnhub symbol discovery failed: {e}")
            return []


register_exchange("finnhub", FinnhubExchange)
register_exchange("finnhub_stock", FinnhubExchange)
register_exchange("stock", FinnhubExchange)
