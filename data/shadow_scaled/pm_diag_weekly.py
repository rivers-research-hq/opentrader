"""Count closed binary markets per week in the LIVE db (min/max_close_ts)."""
import requests, time
from datetime import datetime, timezone, timedelta

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
        print("  HTTP", r.status_code, r.text[:120]); return None
    return None

d0 = datetime(2026, 6, 26, tzinfo=timezone.utc)
print("week-start  closed_total  binary_resolved  vol>100")
for w in range(9):
    a = int((d0 + timedelta(weeks=w)).timestamp())
    b = int((d0 + timedelta(weeks=w + 1)).timestamp())
    body = get({"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 1000})
    if body is None:
        print(f"{datetime.fromtimestamp(a,timezone.utc):%m-%d}  FETCH FAIL"); continue
    ms = body.get("markets", [])
    binres = [m for m in ms if m.get("market_type") == "binary" and m.get("result") in ("yes", "no")]
    vol = [m for m in binres if float(m.get("volume_fp") or 0) > 100]
    print(f"{datetime.fromtimestamp(a,timezone.utc):%m-%d}  {len(ms):>6}  {len(binres):>6}  {len(vol):>6}")
    time.sleep(1.5)
