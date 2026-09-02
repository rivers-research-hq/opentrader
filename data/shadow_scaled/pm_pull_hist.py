"""
pm3b: Pull resolved Kalshi binary markets from the HISTORICAL db (just before the
Jun 26 cutoff) + per-ticker 1-min candlesticks -> pre-resolution price features.
Read-only, no-auth, zero-capital. Checkpointed: saves selected market list first.
"""
import requests, time, json, os, random, pickle
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
random.seed(11)

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

def fetch_hist_markets(pages=10, per=1000):
    out, cursor = [], ""
    for pg in range(pages):
        p = {"limit": per}
        if cursor: p["cursor"] = cursor
        body = get(f"{K}/historical/markets", p)
        if not body: break
        ms = body.get("markets", [])
        if not ms: break
        out.extend(ms)
        cursor = body.get("cursor") or ""
        print(f"  page {pg}: +{len(ms)} (total {len(out)}) oldest_close={ms[-1].get('close_time')}")
        if not cursor: break
        time.sleep(0.7)
    return out

def mid(c):
    yb = (c.get("yes_bid") or {}).get("close")
    ya = (c.get("yes_ask") or {}).get("close")
    if yb is None or ya is None:
        # fall back to last-trade price
        pc = (c.get("price") or {}).get("close")
        if pc is None: return None, None
        return float(pc), None
    yb, ya = float(yb), float(ya)
    return (yb + ya) / 2, (ya - yb)

def main():
    sel_path = f"{OUT}/pm_kalshi_hist_selected.json"
    if os.path.exists(sel_path):
        sel = json.load(open(sel_path))
        print(f"loaded {len(sel)} selected from checkpoint")
    else:
        print("fetching historical markets (10 pages) ...")
        ms = fetch_hist_markets(10, 1000)
        print(f"total historical markets: {len(ms)}")
        res = [m for m in ms
               if m.get("market_type") == "binary"
               and m.get("result") in ("yes", "no")
               and float(m.get("volume_fp") or 0) > 100]
        print(f"resolved binary vol>100: {len(res)}")
        # time-stratify by close_time into 10 buckets, ~25 each
        res.sort(key=lambda m: ts(m["close_time"]))
        B = 10
        per_b = max(1, 250 // B)
        buckets = [res[i::B] for i in range(B)]
        sel = []
        for b in buckets:
            random.shuffle(b)
            sel.extend(b[:per_b])
        json.dump(sel, guarded_open(sel_path, "w"))
        json.dump(sel, open(sel_path, "w"))

    feats = []
    for i, m in enumerate(sel):
        t = m["ticker"]; ct = ts(m["close_time"]); cr = ts(m["created_time"])
        r = get(f"{K}/historical/markets/{t}/candlesticks",
                {"start_ts": cr - 3600, "end_ts": ct + 3600, "period_interval": 1})
        cs = (r or {}).get("candlesticks", [])
        pre = [c for c in cs if c.get("end_period_ts", 10**12) <= ct - 86400]
        if pre:
            c = max(pre, key=lambda x: x["end_period_ts"]); p, sp = mid(c); src = "pre24h"
        elif cs:
            c = min(cs, key=lambda x: x["end_period_ts"]); p, sp = mid(c); src = "first"
        else:
            p, sp = None, None
        if p is not None:
            feats.append({
                "ticker": t, "result": 1 if m["result"] == "yes" else 0,
                "p_pre": p, "spread": sp, "src": src,
                "close_ts": ct, "created_ts": cr,
                "lead_h": (ct - cr) / 3600.0,
                "volume": float(m.get("volume_fp") or 0),
                "series": (m.get("event_ticker") or "")[:14],
                "n_candles": len(cs), "source": "hist",
            })
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(sel)} (feats {len(feats)})")
        time.sleep(0.3)

    outp = f"{OUT}/pm_kalshi_hist_features.pkl"
    pickle.dump(feats, open(outp, "wb"))
    import statistics
    ps = [f["p_pre"] for f in feats]
    print(f"\nSaved {len(feats)} hist features -> {outp}")
    if ps:
        print(f"p_pre: min={min(ps):.3f} max={max(ps):.3f} median={statistics.median(ps):.3f}")
        print(f"result yes rate: {sum(f['result'] for f in feats)/len(feats):.3f}")
        print(f"src pre24h: {sum(1 for f in feats if f['src']=='pre24h')}, first: {sum(1 for f in feats if f['src']=='first')}")

if __name__ == "__main__":
    main()
