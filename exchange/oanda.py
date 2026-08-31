#!/usr/bin/env python3
"""OANDA v20 FX Exchange — Track B venue adapter (practice env).

Real REST API against the OANDA practice environment (demo money).
Credentials are read at runtime from config/oanda_keys.json (gitignored);
the token is never printed, logged, or embedded anywhere.

OANDA is netted per instrument: long/short is expressed via signed units
(negative units = short). The local ledger mirrors paper semantics so the
harness can restore state across restarts (restore_ledger, lesson from
continuity-2: every child must have it).
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ExchangeBase, OHLCV, OrderResult, Balance, register_exchange

logger = logging.getLogger("opentrader.oanda")

# Keys live in the live tree's config dir (gitignored); sandbox falls back to it.
KEYS_PATH = Path(
    os.environ.get(
        "OANDA_KEYS",
        str(Path(__file__).resolve().parent.parent / "config" / "oanda_keys.json"),
    )
)
if not KEYS_PATH.exists():
    _FALLBACK = Path("/home/mrc/opentrader/config/oanda_keys.json")
    if _FALLBACK.exists():
        KEYS_PATH = _FALLBACK

# The 7 FX majors this adapter trades (intersected with the account's
# enabled instruments at connect time).
FX_MAJORS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "GBP_JPY", "AUD_USD", "USD_CAD"]

# harness timeframe -> OANDA candle granularity
_GRANULARITY = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "30m": "M30",
    "1h": "H1",
    "4h": "H4",
    "1d": "D",
    "1w": "W",
}


class OandaExchange(ExchangeBase):
    """OANDA v20 REST adapter (practice environment)."""

    def __init__(self, name: str = "oanda", config: dict = None):
        super().__init__(name, config)
        config = config or {}

        self._token: str = ""
        self._account_id: str = ""
        self._host: str = "https://api-fxpractice.oanda.com"
        self._load_keys()

        # Base instrument list = majors present on the account (resolved in connect)
        self._instruments: List[str] = list(FX_MAJORS)

        # Local paper-semantics ledger (mirrors stock_finnhub.py pattern)
        self._cash: float = float(config.get("initial_cash", 100_000))
        self._positions: Dict[str, float] = {}
        self._cost_basis: Dict[str, float] = {}
        self._fills: List[dict] = []
        self._order_counter: int = 1

        # Cache
        self._bar_cache: Dict[str, List[OHLCV]] = {}
        self._price_cache: Dict[str, float] = {}
        self._cache_ttl: float = float(config.get("cache_ttl", 60.0))
        self._last_fetch: Dict[str, float] = {}
        self._last_api_call: float = 0.0
        self._rate_limit: float = float(config.get("rate_limit", 0.25))

    # ── Credentials ──────────────────────────────────────────

    def _load_keys(self) -> None:
        """Read token/account/host from the gitignored keys file."""
        try:
            keys = json.loads(KEYS_PATH.read_text())
            self._token = keys.get("token", "")
            self._account_id = keys.get("account_id", "")
            self._host = keys.get("host", self._host)
        except Exception as e:
            logger.error(f"OandaExchange: cannot read {KEYS_PATH}: {e}")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _rate_limit_wait(self) -> None:
        elapsed = time.time() - self._last_api_call
        if elapsed < self._rate_limit:
            time.sleep(self._rate_limit - elapsed)

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        """One OANDA v20 REST call. Returns parsed JSON or {} on error."""
        url = f"{self._host}{path}"
        self._rate_limit_wait()
        data = json.dumps(body).encode() if body is not None else None
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "OpenTrader/1.0")
        try:
            with urlopen(req, timeout=15) as resp:
                self._last_api_call = time.time()
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            self._last_api_call = time.time()
            try:
                err = json.loads(e.read().decode())
            except Exception:
                err = {"errorMessage": str(e)}
            logger.error(f"OANDA {method} {path} -> {e.code}: {err}")
            return {"_error": err, "_status": e.code}
        except (URLError, json.JSONDecodeError) as e:
            self._last_api_call = time.time()
            logger.error(f"OANDA {method} {path} failed: {e}")
            return {}

    # ── Connection ───────────────────────────────────────────

    def connect(self) -> bool:
        if not self._token or not self._account_id:
            logger.error("OandaExchange: no credentials (config/oanda_keys.json)")
            return False
        data = self._request("GET", f"/v3/accounts/{self._account_id}")
        acc = data.get("account")
        if not acc:
            logger.error(f"OandaExchange: account query failed: {data}")
            return False
        # Intersect base majors with the account's enabled instruments
        insts = self._request(
            "GET", f"/v3/accounts/{self._account_id}/instruments?state=ENABLED"
        )
        enabled = [i.get("name", "") for i in insts.get("instruments", [])]
        if enabled:
            self._instruments = [m for m in FX_MAJORS if m in enabled]
        self._connected = True
        logger.info(
            f"OandaExchange: connected (practice) balance={acc.get('balance')} "
            f"{acc.get('currency')} instruments={self._instruments}"
        )
        return True

    # ── Market data ──────────────────────────────────────────

    def get_bars(
        self, symbol: str, timeframe: str = "1h", limit: int = 100
    ) -> List[OHLCV]:
        cache_key = f"{symbol}:{timeframe}:{limit}"
        now_ts = time.time()
        if cache_key in self._bar_cache:
            if now_ts - self._last_fetch.get(cache_key, 0) < self._cache_ttl:
                return self._bar_cache[cache_key]

        granularity = _GRANULARITY.get(timeframe, "H1")
        data = self._request(
            "GET",
            f"/v3/instruments/{symbol}/candles"
            f"?granularity={granularity}&count={limit}&includePending=false",
        )
        bars: List[OHLCV] = []
        for c in data.get("candles", []):
            if not c.get("complete", True):
                continue
            # Candles carry a mid side (bid/ask only on the pending candle).
            side = c.get("mid") or c.get("ask") or c.get("bid") or {}
            if not side.get("c"):
                continue
            bars.append(
                OHLCV(
                    timestamp=int(
                        datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
                        .timestamp()
                    ),
                    open=float(side.get("o", 0)),
                    high=float(side.get("h", 0)),
                    low=float(side.get("l", 0)),
                    close=float(side.get("c", 0)),
                    volume=float(c.get("volume", 0)),
                )
            )
        if bars:
            self._bar_cache[cache_key] = bars
            self._last_fetch[cache_key] = now_ts
            self._price_cache[symbol] = bars[-1].close
        return bars

    def _quote_price(self, p: dict) -> float:
        """Extract a representative price from a Price object (ask > mid > bid)."""
        for side in ("ask", "mid", "bid"):
            s = p.get(side) or {}
            if s.get("price"):
                return float(s["price"])
        return 0.0

    def _parse_pricing(self, data: dict) -> Dict[str, float]:
        """Parse the account pricing response into {instrument: price}.

        The v3 pricing endpoint returns {"prices": [{instrument, bids: [...],
        asks: [...]}]} — depth arrays, not flat bid/ask objects.
        """
        out: Dict[str, float] = {}
        for p in data.get("prices", []):
            sym = p.get("instrument")
            if not sym:
                continue
            price = 0.0
            for side, arr in (("asks", p.get("asks")), ("bids", p.get("bids"))):
                if arr:
                    price = float(arr[0].get("price", 0))
                    break
            if price > 0:
                out[sym] = price
        return out

    def get_current_price(self, symbol: str) -> Optional[float]:
        if symbol in self._price_cache:
            return self._price_cache[symbol]
        data = self._request("GET", f"/v3/accounts/{self._account_id}/pricing?instruments={symbol}")
        prices = self._parse_pricing(data)
        if symbol in prices:
            self._price_cache[symbol] = prices[symbol]
            return prices[symbol]
        return None

    def get_prices_batch(self, symbols: list) -> dict:
        """Batch quotes via the account pricing endpoint (one call, up to 50 instruments)."""
        result = {}
        symbols = list(dict.fromkeys(symbols))  # dedupe, preserve order
        for i in range(0, len(symbols), 50):
            chunk = symbols[i : i + 50]
            data = self._request(
                "GET",
                f"/v3/accounts/{self._account_id}/pricing?instruments={','.join(chunk)}",
            )
            for sym, price in self._parse_pricing(data).items():
                result[sym] = price
                self._price_cache[sym] = price
        return result

    # ── Orders ───────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        """Place an order. OANDA is netted: BUY adds units, SELL subtracts.

        order_type: "market" (FOK), "limit" (GTC), "mit" (market-if-touched, GTC).
        stop_loss / take_profit: attach SL/TP on fill (server-side exits —
        they survive restarts because they live on OANDA, not on this box).
        """
        is_buy = side.upper() == "BUY"
        units = int(round(quantity)) if is_buy else -int(round(quantity))
        if units == 0:
            return OrderResult(
                order_id="", symbol=symbol, side=side, quantity=quantity,
                price=0, status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw={"error": "zero units"},
            )

        if order_type == "market":
            order = {
                "type": "MARKET",
                "instrument": symbol,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
            if stop_loss:
                order["stopLossOnFill"] = {"price": f"{stop_loss:.5f}", "timeInForce": "GTC"}
            if take_profit:
                order["takeProfitOnFill"] = {"price": f"{take_profit:.5f}", "timeInForce": "GTC"}
            body = {"order": order}
        elif order_type == "limit":
            if not price:
                return OrderResult(
                    order_id="", symbol=symbol, side=side, quantity=quantity,
                    price=0, status="rejected",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw={"error": "limit order requires price"},
                )
            body = {
                "order": {
                    "type": "LIMIT",
                    "instrument": symbol,
                    "units": str(units),
                    "price": str(price),
                    "timeInForce": "GTC",
                    "positionFill": "DEFAULT",
                }
            }
        elif order_type == "mit":
            if not price:
                return OrderResult(
                    order_id="", symbol=symbol, side=side, quantity=quantity,
                    price=0, status="rejected",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw={"error": "mit order requires price"},
                )
            body = {
                "order": {
                    "type": "MARKET_IF_TOUCHED",
                    "instrument": symbol,
                    "units": str(units),
                    "price": str(price),
                    "timeInForce": "GTC",
                    "positionFill": "DEFAULT",
                }
            }
        else:
            return OrderResult(
                order_id="", symbol=symbol, side=side, quantity=quantity,
                price=0, status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw={"error": f"unsupported order_type: {order_type}"},
            )

        data = self._request(
            "POST", f"/v3/accounts/{self._account_id}/orders", body
        )
        if data.get("_error"):
            return OrderResult(
                order_id="", symbol=symbol, side=side, quantity=quantity,
                price=0, status="rejected",
                timestamp=datetime.now(timezone.utc).isoformat(),
                raw=data,
            )

        # OANDA returns orderCreateTransaction + orderFillTransaction (no
        # orderFill wrapper). The fill transaction carries the unique IDs the
        # continuity ledger dedups on.
        fill_tx = data.get("orderFillTransaction") or {}
        order_id = str(fill_tx.get("orderID") or data.get("lastTransactionID") or "")
        fill_price = float(fill_tx.get("price") or 0)
        if not fill_price:
            fill_price = self.get_current_price(symbol) or 0.0

        # Update local ledger (paper semantics)
        cost = fill_price * abs(units)
        if is_buy:
            self._cash -= cost
            self._positions[symbol] = self._positions.get(symbol, 0) + abs(units)
            self._cost_basis[symbol] = self._cost_basis.get(symbol, 0) + cost
        else:
            self._cash += cost
            self._positions[symbol] = self._positions.get(symbol, 0) - abs(units)
            if self._positions[symbol] <= 0:
                self._positions.pop(symbol, None)
                self._cost_basis.pop(symbol, None)

        fill = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": abs(units),
            "price": fill_price,
            "cost": round(cost, 2),
            "cash_after": round(self._cash, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._fills.append(fill)
        if len(self._fills) > 5000:
            del self._fills[:-5000]
        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=abs(units),
            price=fill_price,
            status="filled",
            timestamp=fill["timestamp"],
            raw=fill,
        )

    # ── Balance / ledger ─────────────────────────────────────

    def get_balance(self) -> Balance:
        """Account balance IS the cash (FX has no broker-style split).

        Positions are net units per instrument from the local ledger.
        """
        data = self._request("GET", f"/v3/accounts/{self._account_id}")
        acc = data.get("account")
        if acc:
            cash = float(acc.get("balance", self._cash))
            nav = float(acc.get("NAV", cash))
        else:
            cash = self._cash
            nav = cash
        return Balance(
            cash=round(cash, 2),
            total_value=round(nav, 2),
            positions={k: v for k, v in self._positions.items() if v != 0},
        )

    def get_fills(self) -> List[dict]:
        return self._fills

    def restore_ledger(
        self, cash: float, positions: Dict[str, float],
        cost_basis: Dict[str, float] = None, fills: list = None,
    ) -> None:
        """Restore the local mirror from persisted state (paper semantics).

        Required on every child (continuity-2 lesson): a restart must resume
        the real book, not revert to init cash / zero positions.
        """
        self._cash = float(cash)
        self._positions = dict(positions)
        self._cost_basis = dict(cost_basis or {})
        if fills is not None:
            self._fills = list(fills)

    def reset(self, initial_cash: float = 100_000) -> None:
        self._cash = initial_cash
        self._positions.clear()
        self._cost_basis.clear()
        self._fills.clear()
        self._order_counter = 1

    def discover_symbols(self, max_symbols: int = 20) -> List[str]:
        """Return the FX majors enabled on this account."""
        return self._instruments[:max_symbols] if max_symbols else self._instruments

    def disconnect(self) -> None:
        self._connected = False
        logger.info("OandaExchange: disconnected")


register_exchange("oanda", OandaExchange)
register_exchange("oanda_fx", OandaExchange)
register_exchange("fx", OandaExchange)
