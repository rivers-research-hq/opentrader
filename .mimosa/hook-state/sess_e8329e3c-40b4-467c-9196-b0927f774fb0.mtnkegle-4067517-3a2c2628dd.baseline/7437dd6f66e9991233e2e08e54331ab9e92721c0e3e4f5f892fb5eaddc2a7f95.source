"""Diagnose volume_fp distribution of closed markets in a window."""
import requests, json
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

a = ts("2026-07-10T00:00:00Z")
b = ts("2026-07-12T00:00:00Z")

r = requests.get(f"{K}/markets",
                 params={"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 200},
                 headers=UA, timeout=30)
print("HTTP", r.status_code)
body = r.json()
ms = body.get("markets", [])
print("fetched:", len(ms), "cursor:", bool(body.get("cursor")))

# distribution of volume_fp
vols = sorted((float(m.get("volume_fp") or 0) for m in ms), reverse=True)
print("volume_fp top 20:", vols[:20])
print("volume_fp > 100:", sum(1 for v in vols if v > 100))
print("volume_fp > 500:", sum(1 for v in vols if v > 500))
print("volume_fp > 2000:", sum(1 for v in vols if v > 2000))

# market_type breakdown
from collections import Counter
print("market_type:", Counter(m.get("market_type") for m in ms))
print("result:", Counter(m.get("result") for m in ms))

# sample one full market record
if ms:
    print("\nsample record:")
    print(json.dumps(ms[0], indent=1, default=str)[:1500])
