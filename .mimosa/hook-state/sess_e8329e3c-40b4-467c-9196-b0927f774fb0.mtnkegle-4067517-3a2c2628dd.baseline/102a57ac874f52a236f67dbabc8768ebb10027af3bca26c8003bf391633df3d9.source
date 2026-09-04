"""
pm3: Pull resolved Kalshi binary markets + daily candlesticks (no-auth, read-only).
Phase 1: collect time-stratified sample of closed binary markets (weekly buckets).
Phase 2: batch-pull daily candlesticks.
Phase 3: extract pre-resolution price + outcome -> features pickle.
"""
import requests, time, json, os, sys, random
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
random.seed(7)

def get(url, params, tries=4):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(1.0 + a); continue
            print(f"  HTTP {r.status_code} {url} {params} :: {r.text[:120]}")
            return None
        except Exception as e:
            time.sleep(1.0 + a)
    return None

def ts(s):  # "2026-08-25T12:00:00Z" -> unix
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

# ---------- Phase 1: collect markets ----------
def collect():
    path = f"{OUT}/pm_kalshi_markets.json"
    if os.path.exists(path) and not sys.argv[1:]:
        print("markets file exists, loading"); return json.load(open(path))
    # weekly buckets 2026-06-26 .. 2026-08-25
    buckets = []
    d0 = datetime(2026, 6, 26, tzinfo=timezone.utc)
    for w in range(9):
        a = int((d0 + __import__("datetime").timedelta(weeks=w)).timestamp())
        b = int((d0 + __import__("datetime").timedelta(weeks=w + 1)).timestamp())
        buckets.append((a, b))
    allm = {}
    for (a, b) in buckets:
        r = get(f"{K}/markets", {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 200})
        ms = (r or {}).get("markets", [])
        keep = [m for m in ms
                if m.get("market_type") == "binary"
                and m.get("result") in ("yes", "no")
                and float(m.get("volume_fp") or 0) > 100]
        print(f"bucket {datetime.fromtimestamp(a,timezone.utc):%m-%d}..{datetime.fromtimestamp(b,timezone.utc):%m-%d}: "
              f"fetched {len(ms)}, kept {len(keep)}")
        for m in keep:
            allm[m["ticker"]] = m
        time.sleep(0.1)
    json.dump(list(allm.values()), guarded_open(path, "w"))
    json.dump(list(allm.values()), open(path, "w"))
    return list(allm.values())

# ---------- Phase 2+3: candlesticks + features ----------
def mid(c):
    yb = (c.get("yes_bid") or {}).get("close_dollars")
    ya = (c.get("yes_ask") or {}).get("close_dollars")
    if yb is None or ya is None: return None, None
    yb, ya = float(yb), float(ya)
    return (yb + ya) / 2, (ya - yb)

def features(markets):
    # subsample to keep candlestick pulls bounded but time-stratified
    by_bucket = {}
    for m in markets:
        c = ts(m["close_time"])
        wk = (c // (7 * 86400))
        by_bucket.setdefault(wk, []).append(m)
    sel = []
    for wk, ms in sorted(by_bucket.items()):
        random.shuffle(ms)
        sel.extend(ms[:150])
    print(f"selected {len(sel)} markets for candlestick pull (<=150/week)")

    feats = []
    for i in range(0, len(sel), 100):
        chunk = sel[i:i+100]
        tickers = [m["ticker"] for m in chunk]
        # window: from earliest created to latest close in chunk
        start = min(ts(m["created_time"]) for m in chunk) - 86400
        end = max(ts(m["close_time"]) for m in chunk) + 86400
        r = get(f"{K}/markets/candlesticks",
                {"market_tickers": ",".join(tickers), "start_ts": start, "end_ts": end,
                 "period_interval": 1440})
        csmap = {}
        if r:
            for mk in r.get("markets", []):
                csmap[mk["market_ticker"]] = mk.get("candlesticks", [])
        for m in chunk:
            t = m["ticker"]
            cs = csmap.get(t, [])
            close_ts = ts(m["close_time"])
            # pre-resolution candle: last daily candle ending <= close_ts - 24h
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts - 86400]
            src = None
            if pre:
                c = max(pre, key=lambda x: x["end_period_ts"])
                p, sp = mid(c); src = "pre24h"
            elif cs:
                c = min(cs, key=lambda x: x["end_period_ts"])
                p, sp = mid(c); src = "first"
            else:
                p, sp = None, None
            if p is None:
                continue
            feats.append({
                "ticker": t, "result": 1 if m["result"] == "yes" else 0,
                "p_pre": p, "spread": sp, "src": src,
                "close_ts": close_ts, "created_ts": ts(m["created_time"]),
                "volume": float(m.get("volume_fp") or 0),
                "series": m.get("event_ticker", "")[:12],
                "n_candles": len(cs),
            })
        print(f"  pulled {min(i+100, len(sel))}/{len(sel)} (feats so far {len(feats)})")
        time.sleep(0.1)
    return feats

if __name__ == "__main__":
    markets = collect()
    feats = features(markets)
    outp = f"{OUT}/pm_kalshi_features.pkl"
    import pickle
    pickle.dump(feats, open(outp, "wb"))
    print(f"\nSaved {len(feats)} features -> {outp}")
    # quick summary
    import statistics
    ps = [f["p_pre"] for f in feats]
    print(f"p_pre: min={min(ps):.3f} max={max(ps):.3f} median={statistics.median(ps):.3f}")
    print(f"result yes rate: {sum(f['result'] for f in feats)/len(feats):.3f}")
    tight = [f for f in feats if f["spread"] is not None and f["spread"] <= 0.15]
    print(f"tight-spread (<=15c) markets: {len(tight)}/{len(feats)}")
