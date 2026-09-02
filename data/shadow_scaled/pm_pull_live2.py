"""
pm5: Pull the FULL result-populated window from the LIVE db (Aug 24-25, where
`result` is actually set) + hourly candlesticks -> early + final pre-resolution prices.
Read-only, no-auth, zero-capital. Lower volume floor (vol>10) for power; report the
volume distribution so the analysis can check robustness to the floor.

Price references per market (hourly candles over [close-7d, close+1h]):
  p_early  = close of the FIRST candle in the window (price at open, or 7d-before-close if older)
  p_final  = close of the LAST candle with end_period_ts <= close_time (final tradeable price)
  spread   = yes_ask - yes_bid at the final candle (for the MM spread-capture estimate)
"""
import requests, time, os, pickle
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"

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
            print(f"  HTTP {r.status_code} {url} :: {r.text[:140]}"); return None
        except Exception:
            time.sleep(2.0 + a)
    return None

def fetch_closed(a, b, cap_pages=80):
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
        time.sleep(0.5)
    return out

def qclose(q, key):
    v = (q or {}).get(key)
    try: return float(v)
    except (TypeError, ValueError): return None

def pull_chunk(tickers, start, end, interval=60, tries=3):
    """Batch candlesticks; halve the chunk on the total-candlestick 400."""
    if not tickers:
        return {}
    r = get(f"{K}/markets/candlesticks",
            {"market_tickers": ",".join(tickers), "start_ts": start, "end_ts": end,
             "period_interval": interval})
    if r is None and tries > 0:
        # likely the total-candlestick cap -> split in half
        mid = len(tickers) // 2
        left = pull_chunk(tickers[:mid], start, end, interval, tries - 1)
        right = pull_chunk(tickers[mid:], start, end, interval, tries - 1)
        left.update(right)
        return left
    csmap = {}
    if r:
        for mk in r.get("markets", []):
            csmap[mk["market_ticker"]] = mk.get("candlesticks", [])
    return csmap

def main():
    a = ts("2026-08-24T00:00:00Z"); b = ts("2026-08-25T23:59:59Z")
    print("fetching closed markets Aug 24-25 (result-populated window) ...")
    ms = fetch_closed(a, b)
    print(f"  total closed: {len(ms)}")
    sel = [m for m in ms
           if m.get("market_type") == "binary"
           and m.get("result") in ("yes", "no")
           and float(m.get("volume_fp") or 0) > 10]
    print(f"  resolved binary vol>10: {len(sel)}")
    sel.sort(key=lambda m: ts(m["close_time"]))

    feats = []
    CHUNK = 20
    for i in range(0, len(sel), CHUNK):
        chunk = sel[i:i+CHUNK]
        start = min(ts(m["created_time"]) for m in chunk) - 86400
        end = max(ts(m["close_time"]) for m in chunk) + 3600
        csmap = pull_chunk([m["ticker"] for m in chunk], start, end, interval=60)
        for m in chunk:
            t = m["ticker"]; cs = csmap.get(t, []); close_ts = ts(m["close_time"])
            if not cs:
                continue
            cs = sorted(cs, key=lambda c: c.get("end_period_ts", 0))
            first = cs[0]
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts]
            last = pre[-1] if pre else cs[-1]
            # early price
            yb = qclose(first.get("yes_bid"), "close_dollars"); ya = qclose(first.get("yes_ask"), "close_dollars")
            p_early = (yb + ya) / 2 if (yb is not None and ya is not None) else None
            # final price + spread
            lb = qclose(last.get("yes_bid"), "close_dollars"); la = qclose(last.get("yes_ask"), "close_dollars")
            p_final = (lb + la) / 2 if (lb is not None and la is not None) else None
            spread = (la - lb) if (lb is not None and la is not None) else None
            if p_early is None and p_final is None:
                continue
            feats.append({
                "ticker": t, "result": 1 if m["result"] == "yes" else 0,
                "p_early": p_early, "p_final": p_final, "spread": spread,
                "close_ts": close_ts, "created_ts": ts(m["created_time"]),
                "lead_h": (close_ts - ts(m["created_time"])) / 3600.0,
                "volume": float(m.get("volume_fp") or 0),
                "series": (m.get("event_ticker") or "")[:16],
                "n_candles": len(cs), "source": "live2",
            })
        print(f"  pulled {min(i+CHUNK, len(sel))}/{len(sel)} (feats {len(feats)})")
        time.sleep(0.5)

    pickle.dump(feats, guarded_open(outp, "wb"))
    pickle.dump(feats, open(outp, "wb"))
    import statistics
    def stat(name, vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            print(f"{name}: (none)"); return
        print(f"{name}: n={len(vals)} min={min(vals):.3f} med={statistics.median(vals):.3f} max={max(vals):.3f}")
    print(f"\nSaved {len(feats)} live2 features -> {outp}")
    stat("p_early", [f["p_early"] for f in feats])
    stat("p_final", [f["p_final"] for f in feats])
    stat("spread ", [f["spread"] for f in feats])
    vols = [f["volume"] for f in feats]
    print(f"volume: n={len(vols)} med={statistics.median(vols):.0f} p90={sorted(vols)[int(0.9*len(vols))]:.0f}")
    print(f"result yes rate: {sum(f['result'] for f in feats)/len(feats):.3f}")
    print(f"lead_h: med={statistics.median([f['lead_h'] for f in feats]):.1f}h")

if __name__ == "__main__":
    main()
