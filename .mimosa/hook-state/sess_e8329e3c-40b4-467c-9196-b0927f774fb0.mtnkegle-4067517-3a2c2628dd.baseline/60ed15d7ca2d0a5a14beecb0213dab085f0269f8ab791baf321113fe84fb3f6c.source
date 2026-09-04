"""Verify historical per-ticker candlestick schema + result field on a real market."""
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

# grab a resolved binary market from the historical db
body = get(f"{K}/historical/markets", {"limit": 200})
ms = (body or {}).get("markets", [])
cand = [m for m in ms if m.get("market_type") == "binary" and m.get("result") in ("yes","no")
        and float(m.get("volume_fp") or 0) > 500]
print(f"historical page0: {len(ms)} markets, {len(cand)} resolved binary vol>500")
if cand:
    m = cand[0]
    print(f"picked: {m['ticker']} result={m['result']} close={m['close_time']} created={m['created_time']} vol={m['volume_fp']}")
    ct = ts(m["close_time"]); cr = ts(m["created_time"])
    r = get(f"{K}/historical/markets/{m['ticker']}/candlesticks",
            {"start_ts": cr - 86400, "end_ts": ct + 3600, "period_interval": 1440})
    print("candlestick response keys:", list(r.keys()) if r else None)
    cs = (r or {}).get("candlesticks", [])
    print(f"n_candles: {len(cs)}")
    if cs:
        print("first candle:", json.dumps(cs[0], default=str))
        print("last  candle:", json.dumps(cs[-1], default=str))
