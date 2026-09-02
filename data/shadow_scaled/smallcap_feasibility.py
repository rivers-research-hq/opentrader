#!/usr/bin/env python3
"""Small-cap data feasibility probe. READ-ONLY.

Answers: can the LIVE price path actually see small/micro caps?
The live path (exchange/stock_finnhub.py) resolves prices as:
  Alpaca data API (free, primary) -> finnhub /quote (free) -> yfinance fallback.
This probe exercises each layer on a spread of cap sizes and reports coverage.
It NEVER prints API keys.

Run: /home/mrc/rocm_venv/bin/python3 smallcap_feasibility.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

sys.path.insert(0, "/home/mrc/opentrader")
from security.guards import guarded_urlopen  # hardening layer (remediation 2026-09-02)

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Test spread: control large cap -> mid -> small -> micro/volatile (all real tickers,
# several already referenced in the project's dynamic_discovery.py).
TEST = {
    "AAPL": "large (control)",
    "SNOW": "mid",
    "PLTR": "mid",
    "RIVN": "small",
    "LCID": "small",
    "NIO": "small",
    "WULF": "micro (miner)",
    "CLSK": "micro (miner)",
    "BITF": "micro (miner)",
}


def load_finnhub_key():
    try:
        from connections import get_api_key
        k = get_api_key("finnhub")
        if k:
            return k
    except Exception:
        pass
    return os.environ.get("FINNHUB_API_KEY", "")


def load_alpaca_keys():
    key, secret = "", ""
    p = Path("/home/mrc/opentrader/config/alt_data_keys.json")
    if p.exists():
        try:
            d = json.loads(p.read_text())
            key, secret = d.get("ALPACA_KEY", ""), d.get("ALPACA_SECRET", "")
        except Exception:
            pass
    key = key or os.environ.get("ALPACA_KEY", "")
    secret = secret or os.environ.get("ALPACA_SECRET", "")
    return key, secret


def fh_get(key, path, params=None):
    params = dict(params or {})
    params["token"] = key
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{FINNHUB_BASE}{path}?{qs}"
    req = Request(url)
    req.add_header("User-Agent", "OpenTrader/1.0")
    try:
        with guarded_urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()), None
    except URLError as e:
        code = getattr(e, "code", None)
        return None, f"HTTP {code}"
    except Exception as e:
        return None, str(e)


def main():
    print("=== SMALL-CAP DATA FEASIBILITY (read-only) ===")
    fh_key = load_finnhub_key()
    ap_key, ap_secret = load_alpaca_keys()
    print(f"finnhub key present: {bool(fh_key)}")
    print(f"alpaca keys present: {bool(ap_key) and bool(ap_secret)}")
    print()

    # ── Layer 1: finnhub /quote per symbol ──
    print("── finnhub /quote (free tier) ──")
    if fh_key:
        for sym, cap in TEST.items():
            d, err = fh_get(fh_key, "/quote", {"symbol": sym})
            time.sleep(1.05)  # stay under 60/min
            if err:
                print(f"  {sym:5} [{cap:16}] ERROR {err}")
            else:
                c, t = d.get("c"), d.get("t")
                age = ""
                if t:
                    age = f" (ts {datetime.fromtimestamp(t, timezone.utc):%H:%M}Z)"
                print(f"  {sym:5} [{cap:16}] close={c}{age}")
    else:
        print("  (no finnhub key — skipped)")

    # ── Layer 2: finnhub earnings calendar (free-tier availability) ──
    print("\n── finnhub /calendar/earnings (free tier) ──")
    if fh_key:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        d, err = fh_get(fh_key, "/calendar/earnings",
                        {"from": today, "to": today, "symbol": "RIVN"})
        if err:
            print(f"  ERROR {err}")
        else:
            ev = (d.get("earningsCalendar") or [])
            print(f"  RIVN earnings events today: {len(ev)} "
                  f"(empty list = endpoint works, no event; error = gated)")
            if ev:
                print(f"    sample: {json.dumps(ev[0])[:160]}")

    # ── Layer 3: finnhub company news (free-tier availability) ──
    print("\n── finnhub /company/news (free tier) ──")
    if fh_key:
        d, err = fh_get(fh_key, "/company/news", {"symbol": "RIVN", "limit": 3})
        if err:
            print(f"  ERROR {err}")
        else:
            n = d if isinstance(d, list) else []
            print(f"  RIVN news items: {len(n)}")
            for it in n[:2]:
                print(f"    {it.get('datetime')} {str(it.get('headline'))[:80]}")

    # ── Layer 4: Alpaca data API batch quotes (the PRIMARY live source) ──
    print("\n── Alpaca data API batch quotes (primary live source) ──")
    if ap_key and ap_secret:
        hdr = {"APCA-API-KEY-ID": ap_key, "APCA-API-SECRET-KEY": ap_secret}
        syms = ",".join(TEST.keys())
        url = f"https://data.alpaca.markets/v2/stocks/quotes?symbols={syms}"
        req = Request(url, headers=hdr)
        try:
            with urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            quotes = data.get("quotes") or {}
            for sym, cap in TEST.items():
                q = quotes.get(sym)
                if q and (q.get("ap") or q.get("bp")):
                    print(f"  {sym:5} [{cap:16}] ap={q.get('ap')} bp={q.get('bp')}")
                else:
                    print(f"  {sym:5} [{cap:16}] NO QUOTE")
        except URLError as e:
            print(f"  ERROR HTTP {getattr(e, 'code', e)}")
        except Exception as e:
            print(f"  ERROR {e}")
    else:
        print("  (no alpaca keys — live path would fall through to finnhub/yfinance)")

    # ── Layer 5: Alpaca daily bars for a small cap (backtest-grade history) ──
    print("\n── Alpaca data API daily bars (2y) for small caps ──")
    if ap_key and ap_secret:
        hdr = {"APCA-API-KEY-ID": ap_key, "APCA-API-SECRET-KEY": ap_secret}
        for sym in ["RIVN", "WULF", "AAPL"]:
            url = (f"https://data.alpaca.markets/v2/stocks/{sym}/bars"
                   f"?timeframe=1Day&limit=500&adjust=all")
            req = Request(url, headers=hdr)
            try:
                with urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                bars = data.get("bars") or []
                if bars:
                    first = bars[0]["t"][:10]
                    last = bars[-1]["t"][:10]
                    print(f"  {sym:5} {len(bars)} bars  {first} .. {last}")
                else:
                    print(f"  {sym:5} NO BARS")
            except URLError as e:
                print(f"  {sym:5} ERROR HTTP {getattr(e, 'code', e)}")
            except Exception as e:
                print(f"  {sym:5} ERROR {e}")
    else:
        print("  (no alpaca keys — skipped)")

    print("\ndone")


if __name__ == "__main__":
    main()
