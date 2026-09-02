"""Can we derive outcome from settlement_value_dollars in the live DB?
And do the recent 2 weeks have enough liquid resolved binary markets?"""
import requests, time, json
from datetime import datetime, timezone
from collections import Counter

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=8):
    for a in range(tries):
        r = requests.get(url, params=params, headers=UA, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(3.0 * (a + 1)); continue
        print("  HTTP", r.status_code, r.text[:120]); return None
    return None

def fetch_all_closed(a, b, cap_pages=40):
    out, cursor = [], ""
    for pg in range(cap_pages):
        p = {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 1000}
        if cursor: p["cursor"] = cursor
        body = get(f"{K}/markets", p)
        if not body: break
        ms = body.get("markets", [])
        if not ms: break
        out.extend(ms)
        cursor = body.get("cursor") or ""
        if not cursor: break
        time.sleep(0.8)
    return out

def analyze(label, a, b):
    ms = fetch_all_closed(a, b)
    binm = [m for m in ms if m.get("market_type") == "binary"]
    print(f"\n=== {label}: {len(ms)} closed, {len(binm)} binary ===")
    if not binm:
        return
    # outcome derivability
    has_result = sum(1 for m in binm if m.get("result") in ("yes", "no"))
    has_settle = sum(1 for m in binm if m.get("settlement_value_dollars") not in (None, "", "0.0000"))
    settle_vals = Counter(str(m.get("settlement_value_dollars")) for m in binm)
    print(f"  with result in(yes,no): {has_result}")
    print(f"  settlement_value_dollars distribution: {dict(list(settle_vals.items())[:8])}")
    # volume
    vols = sorted((float(m.get("volume_fp") or 0) for m in binm), reverse=True)
    for thr in (100, 500, 1000, 2000):
        print(f"  binary vol>{thr}: {sum(1 for v in vols if v > thr)}")
    print(f"  vol top10: {[round(v) for v in vols[:10]]}")
    # cross-tab: does result align with settlement_value?
    both = [(m.get("result"), m.get("settlement_value_dollars")) for m in binm
           if m.get("result") in ("yes", "no") and m.get("settlement_value_dollars") not in (None, "")]
    print(f"  result/settle pairs (first 6): {both[:6]}")

analyze("LIVE recent (Aug 21-25)", ts("2026-08-21T00:00:00Z"), ts("2026-08-25T23:59:59Z"))
analyze("LIVE older (Aug 14-20)", ts("2026-08-14T00:00:00Z"), ts("2026-08-20T23:59:59Z"))
