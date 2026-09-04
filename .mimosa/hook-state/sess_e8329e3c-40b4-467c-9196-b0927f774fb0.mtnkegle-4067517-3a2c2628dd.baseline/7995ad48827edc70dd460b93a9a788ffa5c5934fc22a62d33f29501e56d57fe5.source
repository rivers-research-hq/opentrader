"""Fetch-only consistency check: how many resolved binary vol>10 in Aug 24-25?
Run the fetch 3x to see if the count is stable (rolling result field) or the
earlier 99 was an early-stop anomaly. No candle pulls (fast)."""
import requests, time
from datetime import datetime, timezone

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=15):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200: return r.json()
            if r.status_code in (429, 500, 502, 503): time.sleep(2.5 + 1.5*a); continue
            print(f"  HTTP {r.status_code} :: {r.text[:120]}"); return None
        except Exception:
            time.sleep(2.0 + a)
    return None

def fetch_closed(a, b, cap_pages=120):
    out, cursor, pages = [], "", 0
    for pg in range(cap_pages):
        p = {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 1000}
        if cursor: p["cursor"] = cursor
        body = get(f"{K}/markets", p)
        if not body:
            print(f"    [fetch stopped at page {pg} - get returned None]"); break
        ms = body.get("markets", [])
        if not ms: break
        out.extend(ms)
        cursor = body.get("cursor") or ""
        pages += 1
        if not cursor: break
        time.sleep(0.6)
    return out, pages

a = ts("2026-08-24T00:00:00Z"); b = ts("2026-08-25T23:59:59Z")
for run in range(3):
    ms, pages = fetch_closed(a, b)
    resb = [m for m in ms if m.get("market_type")=="binary" and m.get("result") in ("yes","no")]
    resv = [m for m in resb if float(m.get("volume_fp") or 0) > 10]
    oldest = min((m.get("close_time") for m in ms), default="?")
    newest = max((m.get("close_time") for m in ms), default="?")
    print(f"run {run}: pages={pages} total_closed={len(ms)} resolved_bin={len(resb)} "
          f"res_bin_vol10={len(resv)}  close_range=[{oldest} .. {newest}]")
    time.sleep(1.0)
