"""Careful retest of min_close_ts/max_close_ts with backoff."""
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

def show(label, params):
    body = get(params)
    if body is None:
        print(f"{label}: FAILED"); return
    ms = body.get("markets", [])
    closes = [m.get("close_time") for m in ms]
    print(f"{label}: n={len(ms)} cursor={bool(body.get('cursor'))} "
          f"close range [{min(closes) if closes else '-'} .. {max(closes) if closes else '-'}]")

a = ts("2026-07-10T00:00:00Z"); b = ts("2026-07-12T00:00:00Z")
print("a,b =", a, b)
show("max_close_ts only (Jul12)", {"status": "closed", "max_close_ts": b, "limit": 5})
time.sleep(2)
show("min+max (Jul10..Jul12)", {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 5})
time.sleep(2)
show("min+max (Jul10..Jul12) limit 200", {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 200})
