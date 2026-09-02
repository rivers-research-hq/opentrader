"""
Diag: how much RESOLVED data is actually in the LIVE db?
1) Scan back day-by-day (Aug 1-25) counting closed binary markets WITH result populated.
2) In the populated window, show volume distribution of resolved binary markets.
Read-only, no-auth.
"""
import requests, time
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=8):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200: return r.json()
            if r.status_code in (429, 500, 502, 503): time.sleep(2.0 + 1.5*a); continue
            print(f"  HTTP {r.status_code} {url} :: {r.text[:120]}"); return None
        except Exception:
            time.sleep(2.0 + a)
    return None

def closed_day(day):
    a = ts(day + "T00:00:00Z"); b = ts(day + "T23:59:59Z")
    out, cursor = [], ""
    for pg in range(40):
        p = {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 1000}
        if cursor: p["cursor"] = cursor
        body = get(f"{K}/markets", p)
        if not body: break
        ms = body.get("markets", [])
        if not ms: break
        out.extend(ms)
        cursor = body.get("cursor") or ""
        if not cursor: break
        time.sleep(0.4)
    return out

print("day-by-day resolved-binary counts (live db):")
print(f"  {'day':>12} {'closed':>7} {'binary':>7} {'res_bin':>8} {'res_vol100':>11}")
for d in range(1, 26):
    day = f"2026-08-{d:02d}"
    ms = closed_day(day)
    binm = [m for m in ms if m.get("market_type") == "binary"]
    resb = [m for m in binm if m.get("result") in ("yes", "no")]
    resv = [m for m in resb if float(m.get("volume_fp") or 0) > 100]
    print(f"  {day:>12} {len(ms):>7} {len(binm):>7} {len(resb):>8} {len(resv):>11}")
    time.sleep(0.3)
