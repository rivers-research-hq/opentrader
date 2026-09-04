"""
pm_pull_holdout: Weak-regime holdout re-pull (Q04/Q05).

Pulls ALL closed binary markets from Aug 26 00:00 UTC to now, applies EXACTLY
the pm_pull_live3.py pipeline (hourly first-real-candle probe, spread <= 0.10,
p_first_real in (0.001, 0.999)), and writes a takermaker-style diagnostic
(aggregate + per-bin + series-cluster view) for comparison with the primary
Aug 24-25 sample. Read-only, no-auth, zero-capital.

Outputs (NEW files only — never touches primary pkls):
  pm_kalshi_holdout_features.pkl   features like pm_kalshi_live3_features.pkl
  pm_kalshi_holdout_diag.txt       diagnostic stdout (bin edges + clusters)
"""
import requests, time, pickle, sys
from datetime import datetime, timezone
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
REAL_SPREAD = 0.10
FEE = 0.07

def ts(s):
    return int(datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp())

def now_ts():
    return int(time.time())

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

def fetch_closed(a, b, cap_pages=200):
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
    a = ts("2026-08-26T00:00:00Z")
    b = now_ts()
    print(f"fetching closed markets Aug 26 00:00Z -> {datetime.fromtimestamp(b, timezone.utc).strftime('%Y-%m-%d %H:%M')}Z ...")
    ms = fetch_closed(a, b)
    sel = [m for m in ms
           if m.get("market_type") == "binary"
           and m.get("result") in ("yes", "no")]
    print(f"  total closed: {len(ms)}  resolved binary: {len(sel)}")
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
        print(f"  pulled {min(i+CHUNK, len(sel))}/{len(sel)} (feats {len(feats)})", flush=True)
        time.sleep(0.5)

    pickle.dump(feats, guarded_open(outp, "wb"))
    pickle.dump(feats, open(outp, "wb"))
    print(f"\nSaved {len(feats)} features -> {outp}")

    # ---- diagnostic (mirrors pm_diag_takermaker.py) ----
    import numpy as np, pandas as pd
    d = pd.DataFrame([f for f in feats if f.get("n_real", 0) > 0])
    d = d[(d.p_first_real > 0.001) & (d.p_first_real < 0.999)].dropna(subset=["p_first_real", "spread_first_real"]).copy()
    p = d.p_first_real
    d["fav_price"] = np.maximum(p, 1 - p)
    d["fav_win"] = np.where(p >= 0.5, d.result, 1 - d.result)
    sp = d.spread_first_real
    d["fav_ask"] = d.fav_price + sp / 2
    d["fav_bid"] = d.fav_price - sp / 2

    def boot_arr(e, nboot=4000, seed=42):
        rng = np.random.default_rng(seed); n = len(e)
        m = np.array([rng.choice(e, n, replace=True).mean() for _ in range(nboot)])
        return e.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

    print(f"\n=== HOLDOUT DIAGNOSTIC (tradeable: {len(d)}) ===")
    print(f"N={len(d)}  fav wins={int(d.fav_win.sum())}/{len(d)}  avg fav_price={d.fav_price.mean():.4f}")
    print(f"avg spread={(sp.mean())*100:.2f}c")
    mk = (d.fav_win - d.fav_bid).values
    km, klo, khi = boot_arr(mk)
    print(f"MAKER aggregate edge = {km*100:+.2f}c  CI[{klo*100:+.2f},{khi*100:+.2f}]")
    me = (d.fav_win - d.fav_price - FEE*d.fav_price*(1-d.fav_price)).values
    mm, mlo, mhi = boot_arr(me)
    print(f"MID   aggregate edge = {mm*100:+.2f}c  CI[{mlo*100:+.2f},{mhi*100:+.2f}]")

    bins = [0.90, 0.95, 0.99, 1.0]
    for lo, hi in zip(bins[:-1], bins[1:]):
        b = d[(d.fav_price > lo) & (d.fav_price <= hi)]
        if len(b) < 3:
            print(f"  {lo:.2f}-{hi:.2f}  n={len(b)}  (skipped n<3)")
            continue
        mak_e = (b.fav_win - b.fav_bid).mean() * 100
        mid_e = (b.fav_win - b.fav_price - FEE*b.fav_price*(1-b.fav_price)).mean() * 100
        wins = int(b.fav_win.sum())
        print(f"  {lo:.2f}-{hi:.2f}  n={len(b):>3}  wins={wins}/{len(b)}  mid={mid_e:+.2f}  maker={mak_e:+.2f}   (avg spread {b.spread_first_real.mean()*100:.1f}c)")

    # series-cluster view on the 0.95-0.99 bin (Q03/Q04 comparable)
    bm_ = d[(d.fav_price > 0.95) & (d.fav_price <= 0.99)]
    if len(bm_) >= 3:
        g = bm_.groupby("series").agg(n=("fav_win","size"), mean_c=("fav_win", "mean"))
        g["maker_c"] = bm_.groupby("series").apply(
            lambda s: (s.fav_win - s.fav_bid).mean()*100, include_groups=False)
        print(f"\n0.95-0.99 cluster view: n={len(bm_)} clusters={bm_.series.nunique()} max_cluster={g.n.max()}")
        print(g.sort_values("n", ascending=False).to_string())

if __name__ == "__main__":
    main()
