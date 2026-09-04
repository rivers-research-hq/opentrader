"""Check close_time range of closed markets in live DB + how time filters behave."""
import requests, json
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def show(label, params, n=5):
    r = requests.get(f"{K}/markets", params=params, headers=UA, timeout=30)
    print(f"--- {label}: HTTP {r.status_code}")
    if r.status_code != 200:
        print("   ", r.text[:200]); return
    body = r.json()
    ms = body.get("markets", [])
    print(f"    fetched {len(ms)}, cursor={bool(body.get('cursor'))}")
    for m in ms[:n]:
        print(f"    {m['ticker']:<28} close={m.get('close_time')} vol={m.get('volume_fp')} type={m.get('market_type')} result={m.get('result')}")

# 1. no time filter, most recent closed
show("closed, no time filter", {"status": "closed", "limit": 5})

# 2. paginate to find oldest closed in live DB
cursor = ""
oldest = None
count = 0
for page in range(60):
    p = {"status": "closed", "limit": 200}
    if cursor: p["cursor"] = cursor
    r = requests.get(f"{K}/markets", params=p, headers=UA, timeout=30)
    if r.status_code != 200:
        print("page fail", r.status_code, r.text[:150]); break
    body = r.json()
    ms = body.get("markets", [])
    if not ms: break
    count += len(ms)
    oldest = ms[-1].get("close_time")
    cursor = body.get("cursor") or ""
    if not cursor: break
print(f"\npaginated {count} closed markets; oldest close_time seen: {oldest}")

# 3. try min_close_ts only (no max)
show("min_close_ts=2026-07-10 only", {"status": "closed", "min_close_ts": 1783699200, "limit": 5})
# 4. try max_close_ts only
show("max_close_ts=2026-07-12 only", {"status": "closed", "max_close_ts": 1783872000, "limit": 5})
