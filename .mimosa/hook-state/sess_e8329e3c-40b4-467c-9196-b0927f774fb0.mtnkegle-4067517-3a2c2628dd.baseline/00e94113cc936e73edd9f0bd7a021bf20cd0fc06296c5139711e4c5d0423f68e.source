"""Probe closed-market density around early July in live DB."""
import requests, time
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(params, tries=6):
    for a in range(tries):
        r = requests.get(f"{K}/markets", params=params, headers=UA, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(3.0 * (a + 1)); continue
        print("  HTTP", r.status_code, r.text[:150]); return None
    return None

for day in ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10", "2026-07-11", "2026-07-13", "2026-07-15"]:
    b = ts(day + "T00:00:00Z")
    body = get({"status": "closed", "max_close_ts": b, "limit": 3})
    if body:
        ms = body.get("markets", [])
        latest = ms[0].get("close_time") if ms else "-"
        print(f"max_close_ts={day}: latest close before = {latest}")
    time.sleep(1.5)
