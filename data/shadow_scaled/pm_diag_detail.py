"""Does GET /markets/{ticker} (detail) populate result for an older closed market?
Also measure historical DB pagination density."""
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

# 1. Find an older closed binary market (week of Aug 10-14) with volume
a = ts("2026-08-10T00:00:00Z"); b = ts("2026-08-14T00:00:00Z")
body = get(f"{K}/markets", {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 100})
ms = (body or {}).get("markets", [])
cand = [m for m in ms if m.get("market_type") == "binary" and float(m.get("volume_fp") or 0) > 500]
print(f"week 08-10: {len(ms)} closed, {len(cand)} binary vol>500")
if cand:
    m = cand[0]
    print(f"list record: ticker={m['ticker']} result={m.get('result')!r} status={m.get('status')!r} "
          f"settlement_ts={m.get('settlement_ts')!r} vol={m.get('volume_fp')}")
    time.sleep(1.5)
    # detail endpoint
    d = get(f"{K}/markets/{m['ticker']}", {})
    if d:
        dm = d.get("market", d)
        print(f"DETAIL: ticker={dm.get('ticker')} result={dm.get('result')!r} status={dm.get('status')!r} "
              f"settlement_ts={dm.get('settlement_ts')!r} settlement_value={dm.get('settlement_value_dollars')!r}")
        print("  detail keys w/ result-ish:", [k for k in dm if 'result' in k or 'settle' in k or 'status' in k])

# 2. Historical DB pagination density: how far back in N pages?
print("\n=== HISTORICAL pagination density ===")
cursor = ""
for page in range(6):
    p = {"limit": 1000}
    if cursor: p["cursor"] = cursor
    body = get(f"{K}/historical/markets", p)
    if not body: break
    ms = body.get("markets", [])
    if not ms: break
    closes = [m.get("close_time") for m in ms]
    nres = sum(1 for m in ms if m.get("result") in ("yes", "no"))
    print(f"page {page}: n={len(ms)} close [{min(closes)} .. {max(closes)}] resolved={nres}")
    cursor = body.get("cursor") or ""
    if not cursor: break
    time.sleep(1.0)
