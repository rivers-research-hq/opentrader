#!/usr/bin/env python3
"""Crypto market microstructure context blocks for the debate engine.

[FUNDING]   — perpetual funding rates via ccxt.krakenfutures (real, free).
[ORDERBOOK] — spot order-book depth (best bid/ask, spread, imbalance) from the
              live kraken exchange.

Prototype per wayfinder #22 — model-sees-data only (Q2-a), no signal engineering.
Funding settles every ~8h, so rates are cached (default 6h TTL).
"""

import logging
import threading
import time

logger = logging.getLogger("opentrader.market_ctx")

_FUNDING_TTL = 6 * 3600  # funding settles ~every 8h; poll every 6h
_funding_cache: dict = {}
_funding_lock = threading.Lock()
_kf = None
_kf_lock = threading.Lock()


def _krakenfutures():
    global _kf
    if _kf is None:
        with _kf_lock:
            if _kf is None:
                import ccxt

                _kf = ccxt.krakenfutures()
                _kf.load_markets()
    return _kf


def _perp_market(symbol: str):
    """Spot BASE/USDT -> the krakenfutures perpetual-swap market for BASE.

    krakenfutures quotes perps in USD (e.g. BTC/USD:USD), not USDT, so we look
    up the base asset's perpetual swap from the loaded markets.
    """
    base = symbol.split("/")[0]
    try:
        kf = _krakenfutures()
    except Exception:
        return None
    best = None
    for m, md in kf.markets.items():
        if md.get("swap") is not True:
            continue
        if md.get("base") != base:
            continue
        if best is None or md.get("quote") == "USD":
            best = m
    return best


def fetch_funding(symbols, ttl: float = _FUNDING_TTL) -> dict:
    """Funding rate per crypto symbol (spot symbol -> perp market). Cached."""
    now = time.time()
    out = {}
    to_fetch = []
    with _funding_lock:
        for s in symbols:
            if "/" not in s:
                continue
            hit = _funding_cache.get(s)
            if hit and now - hit[0] < ttl:
                out[s] = hit[1]
            else:
                to_fetch.append(s)
    if not to_fetch:
        return out

    try:
        kf = _krakenfutures()
        for s in to_fetch:
            try:
                market = _perp_market(s)
                rate = None
                try:
                    fr = kf.fetch_funding_rate(market)
                    rate = fr.get("fundingRate")
                    if rate is None:
                        rate = (fr.get("info") or {}).get("funding_rate")
                except Exception:
                    rate = None
                if rate is None:
                    t = kf.fetch_ticker(market)
                    rate = t.get("fundingRate") or (t.get("info") or {}).get("funding_rate")
                if rate is None:
                    continue
                try:
                    rate = float(rate)
                except (TypeError, ValueError):
                    continue
                funding = {
                    "rate": rate,
                    "annualized": rate * 3 * 365,  # 8h funding, 3 per day
                    "market": market,
                }
                out[s] = funding
                with _funding_lock:
                    _funding_cache[s] = (now, funding)
                logger.debug(f"[market_ctx] funding {s} -> {rate:.2e}")
            except Exception as e:
                logger.debug(f"[market_ctx] funding {s} failed: {e}")
    except Exception as e:
        logger.warning(f"[market_ctx] krakenfutures unavailable: {e}")
    return out


def funding_to_context(funding: dict) -> str:
    """Build the [FUNDING] context block."""
    lines = []
    for s, f in sorted(funding.items()):
        rate = f.get("rate")
        if rate is None:
            continue
        ann = f.get("annualized", rate * 3 * 365)
        lines.append(
            f"  {s}: {rate * 100:+.4f}% / 8h  ({ann * 100:+.1f}% annualized)"
        )
    if not lines:
        return ""
    return "[FUNDING]\n" + "\n".join(lines) + "\n"


def depth_to_context(d: dict) -> str:
    """Build the [ORDERBOOK] context block."""
    if not d:
        return ""
    return (
        f"[ORDERBOOK] {d.get('symbol', '?')}\n"
        f"  best bid={d['best_bid']:.6g} ask={d['best_ask']:.6g} "
        f"spread={d['spread_pct'] * 100:.3f}% "
        f"imbalance={d['imbalance']:+.3f} "
        f"(bid vol {d['bid_vol']:.3g} / ask vol {d['ask_vol']:.3g})\n"
    )
