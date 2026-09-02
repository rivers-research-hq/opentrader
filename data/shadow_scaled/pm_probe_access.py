"""
pm2: Verify no-auth public market-data access on Kalshi + Polymarket.
Read-only. No keys, no orders, no state writes.
"""
import json
import requests

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def probe(name, url, params=None, expect_keys=None):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=20)
        ok = r.status_code == 200
        body = None
        try:
            body = r.json()
        except Exception:
            pass
        print(f"[{'OK ' if ok else 'ERR'}] {name}: HTTP {r.status_code}")
        if ok and body is not None:
            if isinstance(body, dict):
                print(f"       top-level keys: {sorted(body.keys())[:12]}")
                if expect_keys:
                    for k in expect_keys:
                        print(f"       has '{k}': {k in body}")
            elif isinstance(body, list):
                print(f"       list len={len(body)}")
                if body and isinstance(body[0], dict):
                    print(f"       item keys: {sorted(body[0].keys())[:16]}")
        elif not ok:
            print(f"       body[:300]: {r.text[:300]}")
        return ok, body
    except Exception as e:
        print(f"[ERR] {name}: {type(e).__name__}: {e}")
        return False, None

print("=== KALSHI (no auth) ===")
ok, body = probe("markets open", f"{K}/markets", {"status": "open", "limit": 3},
                 expect_keys=["markets", "cursor"])
ok2, body2 = probe("markets resolved", f"{K}/markets", {"status": "resolved", "limit": 3},
                   expect_keys=["markets", "cursor"])

# grab a ticker from resolved set for the trades probe
ticker = None
if body2 and isinstance(body2, dict):
    ms = body2.get("markets", [])
    if ms:
        ticker = ms[0].get("ticker")
        print(f"       sample resolved market: {json.dumps(ms[0], default=str)[:600]}")
if ticker:
    probe("trades", f"{K}/markets/{ticker}/trades", {"limit": 5}, expect_keys=["trades"])
    probe("orderbook", f"{K}/markets/{ticker}/orderbook", {"depth": 2}, expect_keys=["order_book"])

print()
print("=== POLYMARKET (no auth) ===")
probe("clob markets", "https://clob.polymarket.com/markets", {"next_cursor": ""},
      expect_keys=["data", "next_cursor"])
probe("gamma markets", "https://gamma-api.polymarket.com/markets", {"limit": 2, "closed": "true"},
      expect_keys=None)
probe("data-api markets", "https://data-api.polymarket.com/markets", {"limit": 2, "closed": "true"},
      expect_keys=None)
