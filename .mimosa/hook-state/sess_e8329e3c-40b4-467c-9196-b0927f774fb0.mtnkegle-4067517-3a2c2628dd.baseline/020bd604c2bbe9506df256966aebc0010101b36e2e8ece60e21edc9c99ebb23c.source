"""
pm7: Re-pull the result-populated live window (Aug 24-25) with CLEAN per-candle
spread tracking, so we can isolate REAL tradeable prices (tight two-sided quotes)
from degenerate 0/1 quotes on short/illiquid markets.

Per market (hourly candles over [close-7d, close+1h]) we record:
  p_first_real / spread_first_real : first candle with spread <= 0.10 (first real price)
  p_last_real  / spread_last_real  : last candle (end<=close) with spread <= 0.10
  p_first_all / p_last_all         : first / last candle regardless of spread
  n_real / n_total                 : candle counts
Only markets with >=1 real candle are kept (they have a tradeable price).
Read-only, no-auth, zero-capital.
"""
import requests, time, pickle
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
REAL_SPREAD = 0.10

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def get(url, params, tries=15):
    for a in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2.5 + 1.5 * a); continue
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

def q(qd, key):
    v = (qd or {}).get(key)
    try: return float(v)
    except (TypeError, ValueError): return None

def pull_chunk(tickers, start, end, interval=60, tries=3):
    if not tickers:
        return {}
    r = get(f"{K}/markets/candlesticks",
            {"market_tickers": ",".join(tickers), "start_ts": start, "end_ts": end,
             "period_interval": interval})
    if r is None and tries > 0:
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
    print("fetching closed markets Aug 24-25 ...")
    ms = fetch_closed(a, b)
    sel = [m for m in ms
           if m.get("market_type") == "binary"
           and m.get("result") in ("yes", "no")]
    print(f"  total closed: {len(ms)}  resolved binary (all vol): {len(sel)}")
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
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts] or cs
            # per-candle (mid, spread)
            rows = []
            for c in pre:
                yb = q(c.get("yes_bid"), "close_dollars"); ya = q(c.get("yes_ask"), "close_dollars")
                if yb is None or ya is None:
                    continue
                rows.append(((yb + ya) / 2, ya - yb))
            if not rows:
                continue
            real = [r for r in rows if r[1] <= REAL_SPREAD]
            f = {
                "ticker": t, "result": 1 if m["result"] == "yes" else 0,
                "close_ts": close_ts, "created_ts": ts(m["created_time"]),
                "lead_h": (close_ts - ts(m["created_time"])) / 3600.0,
                "volume": float(m.get("volume_fp") or 0),
                "series": (m.get("event_ticker") or "")[:16],
                "p_first_all": rows[0][0], "p_last_all": rows[-1][0],
                "n_real": len(real), "n_total": len(rows),
            }
            if real:
                f["p_first_real"] = real[0][0]; f["spread_first_real"] = real[0][1]
                f["p_last_real"] = real[-1][0]; f["spread_last_real"] = real[-1][1]
            feats.append(f)
        print(f"  pulled {min(i+CHUNK, len(sel))}/{len(sel)} (feats {len(feats)})")
        time.sleep(0.5)

    pickle.dump(feats, guarded_open(outp, "wb"))
    pickle.dump(feats, open(outp, "wb"))
    import statistics
    withreal = [f for f in feats if f.get("n_real", 0) > 0]
    print(f"\nSaved {len(feats)} features ({len(withreal)} with >=1 real candle) -> {outp}")
    def stat(name, vals):
        vals = [v for v in vals if v is not None]
        if not vals: print(f"{name}: (none)"); return
        print(f"{name}: n={len(vals)} min={min(vals):.3f} med={statistics.median(vals):.3f} max={max(vals):.3f}")
    stat("p_first_real", [f.get("p_first_real") for f in withreal])
    stat("p_last_real ", [f.get("p_last_real") for f in withreal])
    stat("spread_first", [f.get("spread_first_real") for f in withreal])
    print(f"result yes rate (with-real): {sum(f['result'] for f in withreal)/len(withreal):.3f}")

if __name__ == "__main__":
    main()
