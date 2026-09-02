"""
pm3a: Pull resolved Kalshi binary markets from the LIVE db (recent week, where
`result` is populated) + batch daily candlesticks -> pre-resolution price features.
Read-only, no-auth, zero-capital.
"""
import requests, time, json, os, sys, random, pickle
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
random.seed(7)

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=8):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2.0 + 1.5 * a); continue
            print(f"  HTTP {r.status_code} {url} :: {r.text[:120]}"); return None
        except Exception as e:
            time.sleep(2.0 + a)
    return None

def fetch_closed(a, b, cap_pages=60):
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
        time.sleep(0.6)
    return out

def mid(c):
    yb = (c.get("yes_bid") or {}).get("close_dollars")
    ya = (c.get("yes_ask") or {}).get("close_dollars")
    if yb is None or ya is None: return None, None
    yb, ya = float(yb), float(ya)
    return (yb + ya) / 2, (ya - yb)

def main():
    a = ts("2026-08-20T00:00:00Z"); b = ts("2026-08-25T23:59:59Z")
    print("fetching closed markets Aug 20-25 ...")
    ms = fetch_closed(a, b)
    print(f"  total closed: {len(ms)}")
    # resolved binary with volume
    sel = [m for m in ms
           if m.get("market_type") == "binary"
           and m.get("result") in ("yes", "no")
           and float(m.get("volume_fp") or 0) > 100]
    print(f"  resolved binary vol>100: {len(sel)}")

    feats = []
    for i in range(0, len(sel), 20):  # small chunks: keep total candlesticks under the per-request cap
        chunk = sel[i:i+20]
        tickers = [m["ticker"] for m in chunk]
        start = min(ts(m["created_time"]) for m in chunk) - 86400
        end = max(ts(m["close_time"]) for m in chunk) + 3600
        r = get(f"{K}/markets/candlesticks",
                {"market_tickers": ",".join(tickers), "start_ts": start, "end_ts": end,
                 "period_interval": 1440})
        csmap = {}
        if r:
            for mk in r.get("markets", []):
                csmap[mk["market_ticker"]] = mk.get("candlesticks", [])
        for m in chunk:
            t = m["ticker"]; cs = csmap.get(t, []); close_ts = ts(m["close_time"])
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts - 86400]
            if pre:
                c = max(pre, key=lambda x: x["end_period_ts"]); p, sp = mid(c); src = "pre24h"
            elif cs:
                c = min(cs, key=lambda x: x["end_period_ts"]); p, sp = mid(c); src = "first"
            else:
                p, sp = None, None
            if p is None: continue
            feats.append({
                "ticker": t, "result": 1 if m["result"] == "yes" else 0,
                "p_pre": p, "spread": sp, "src": src,
                "close_ts": close_ts, "created_ts": ts(m["created_time"]),
                "lead_h": (close_ts - ts(m["created_time"])) / 3600.0,
                "volume": float(m.get("volume_fp") or 0),
                "series": (m.get("event_ticker") or "")[:14],
                "n_candles": len(cs), "source": "live",
            })
        print(f"  pulled {min(i+20, len(sel))}/{len(sel)} (feats {len(feats)})")
        time.sleep(0.5)

    pickle.dump(feats, guarded_open(outp, "wb"))
    pickle.dump(feats, open(outp, "wb"))
    import statistics
    ps = [f["p_pre"] for f in feats]
    print(f"\nSaved {len(feats)} live features -> {outp}")
    if ps:
        print(f"p_pre: min={min(ps):.3f} max={max(ps):.3f} median={statistics.median(ps):.3f}")
        print(f"result yes rate: {sum(f['result'] for f in feats)/len(feats):.3f}")
        print(f"src pre24h: {sum(1 for f in feats if f['src']=='pre24h')}, first: {sum(1 for f in feats if f['src']=='first')}")

if __name__ == "__main__":
    main()
