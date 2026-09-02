"""Inspect result population in live DB (older week) + historical DB structure."""
import requests, time, json
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=6):
    for a in range(tries):
        r = requests.get(url, params=params, headers=UA, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(3.0 * (a + 1)); continue
        print("  HTTP", r.status_code, r.text[:150]); return None
    return None

# 1. Live DB, week of Aug 14-21: what do closed markets look like?
a = ts("2026-08-14T00:00:00Z"); b = ts("2026-08-21T00:00:00Z")
body = get(f"{K}/markets", {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 20})
if body:
    ms = body.get("markets", [])
    print(f"=== LIVE DB week 08-14: {len(ms)} markets ===")
    from collections import Counter
    print("market_type:", Counter(m.get("market_type") for m in ms))
    print("result:", Counter(repr(m.get("result")) for m in ms))
    if ms:
        print("sample:", json.dumps(ms[0], default=str)[:400])

time.sleep(1.5)
# 2. Historical DB structure
body = get(f"{K}/historical/markets", {"limit": 3})
print("\n=== HISTORICAL /historical/markets (limit 3) ===")
if body:
    ms = body.get("markets", [])
    print("n:", len(ms), "cursor:", bool(body.get("cursor")))
    if ms:
        print("keys:", sorted(ms[0].keys()))
        print("sample:", json.dumps(ms[0], default=str)[:600])
        print("close_times:", [m.get("close_time") for m in ms])

time.sleep(1.5)
# 3. Historical cutoff
body = get(f"{K}/historical/cutoff", {})
print("\n=== HISTORICAL cutoff ===")
print(json.dumps(body, default=str)[:300] if body else "None")
