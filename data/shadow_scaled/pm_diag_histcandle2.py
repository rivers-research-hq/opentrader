"""Test historical candlestick at period_interval=1 (1-min) for short + long markets."""
import requests, time, json
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=8):
    for a in range(tries):
        r = requests.get(url, params=params, headers=UA, timeout=30)
        if r.status_code == 200: return r.json()
        if r.status_code == 429: time.sleep(3.0*(a+1)); continue
        print("  HTTP", r.status_code, r.text[:150]); return None
    return None

body = get(f"{K}/historical/markets", {"limit": 300})
ms = (body or {}).get("markets", [])
cand = [m for m in ms if m.get("market_type") == "binary" and m.get("result") in ("yes","no")
        and float(m.get("volume_fp") or 0) > 500]
# pick one short and one long (by lead time)
cand.sort(key=lambda m: ts(m["close_time"]) - ts(m["created_time"]))
short_m = cand[0]
long_m = cand[-1]
for label, m in [("SHORT", short_m), ("LONG", long_m)]:
    lead = (ts(m["close_time"]) - ts(m["created_time"]))/3600.0
    print(f"\n=== {label}: {m['ticker']} lead={lead:.1f}h result={m['result']} vol={m['volume_fp']}")
    cr = ts(m["created_time"]); ct = ts(m["close_time"])
    for interval in (1, 60):
        r = get(f"{K}/historical/markets/{m['ticker']}/candlesticks",
                {"start_ts": cr - 3600, "end_ts": ct + 3600, "period_interval": interval})
        cs = (r or {}).get("candlesticks", [])
        print(f"  interval={interval}: n_candles={len(cs)}")
        if cs:
            print(f"    first: {json.dumps(cs[0], default=str)[:220]}")
            print(f"    last : {json.dumps(cs[-1], default=str)[:220]}")
        time.sleep(0.5)
