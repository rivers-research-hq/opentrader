"""
pm_pull_1min: Re-pull the FULL 1-min quote sequence for the 345 tradeable
favorite-edge markets (pm_kalshi_live3_real.pkl), keeping EVERY candle.

pm_pull_live3.py collapsed each market to its first-real-candle; this keeps
the whole 1-min series so the shadow maker simulator (V08/V09) can measure
realized fill rate and adverse selection. Data foundation only — no sim here.

Read-only, no-auth, zero-capital. Public endpoint GET /markets/candlesticks.

CRITICAL: period_interval is in MINUTES. 1 = 1-min candles (60s gaps).
The 10000-candle cap is window_minutes * n_markets, so we pull ONE market per
request and time-split any window > 9000 min into 9000-min sub-windows.

Output (additive, never touches pm_kalshi_live3_real.pkl):
  pm_kalshi_1min_flat.pkl        one flat row per 1-min candle
  pm_kalshi_1min_flat.manifest.json
Idempotent/resumable: re-runs skip tickers already in the manifest's pulled set.
"""
import requests, time, pickle, json, os, math
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
SRC = f"{OUT}/pm_kalshi_live3_real.pkl"
OUTPKL = f"{OUT}/pm_kalshi_1min_flat.pkl"
MANIFEST = f"{OUT}/pm_kalshi_1min_flat.manifest.json"
INTERVAL = 1          # minutes per candle (1 = 1-min)
SUBWIN = 9000 * 60    # max SECONDS per request (9000 min = 10000-candle cap / 1 market, w/ margin)
SLEEP = 0.25


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


def pull_market(ticker, start, end):
    """Pull 1-min candles for ONE market over [start,end], time-splitting
    windows > SUBWIN minutes. Returns list of raw candle dicts (merged, deduped)."""
    if end - start <= SUBWIN:
        r = get(f"{K}/markets/candlesticks",
                {"market_tickers": ticker, "start_ts": start, "end_ts": end,
                 "period_interval": INTERVAL})
        if r:
            for mk in r.get("markets", []):
                if mk["market_ticker"] == ticker:
                    return mk.get("candlesticks", [])
        return []
    # time-split
    out, seen = [], set()
    t = start
    while t < end:
        t2 = min(t + SUBWIN, end)
        r = get(f"{K}/markets/candlesticks",
                {"market_tickers": ticker, "start_ts": t, "end_ts": t2,
                 "period_interval": INTERVAL})
        if r:
            for mk in r.get("markets", []):
                if mk["market_ticker"] == ticker:
                    for c in mk.get("candlesticks", []):
                        k = c.get("end_period_ts")
                        if k not in seen:
                            seen.add(k); out.append(c)
        t = t2
        time.sleep(SLEEP)
    return out


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clean(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def price_bin(fp):
    # match pm_diag_takermaker.py bins exactly: (lo, hi]
    if fp is None:
        return "other"
    if 0.90 < fp <= 0.95:
        return "0.90-0.95"
    if 0.95 < fp <= 0.99:
        return "0.95-0.99"
    if 0.99 < fp <= 1.00:
        return "0.99-1.00"
    return "other"


def write_manifest(pulled, missing, all_rows, tickers):
    with_candles = {r["ticker"] for r in all_rows}
    manifest = {
        "n_markets_expected": len(tickers),
        "n_markets_with_candles": len(with_candles),
        "coverage_pct": round(100.0 * len(with_candles) / len(tickers), 2) if tickers else 0.0,
        "n_candles": len(all_rows),
        "missing_tickers": sorted(missing),
        "pulled_tickers": sorted(pulled),
        "set_breakdown": {"primary": len(tickers)},
        "source_pkl": SRC,
        "output_pkl": OUTPKL,
        "pull_ts": int(time.time()),
    }
    json.dump(manifest, open(MANIFEST, "w"), indent=2)
    return manifest


def main():
    import pandas as pd
    src = pd.read_pickle(SRC)
    meta = {}
    for _, r in src.iterrows():
        t = r["ticker"]
        pfr = clean(r.get("p_first_real"))
        fav_side = "yes" if (pfr is not None and pfr >= 0.5) else "no"
        fav_price = None if pfr is None else max(pfr, 1 - pfr)
        meta[t] = {
            "ticker": t,
            "series": r.get("series"),
            "result": int(r["result"]),
            "created_ts": int(r["created_ts"]),
            "close_ts": int(r["close_ts"]),
            "lead_h": float(clean(r.get("lead_h")) or 0),
            "volume": float(clean(r.get("volume")) or 0),
            "p_first_real": pfr,
            "fav_side": fav_side,
            "fav_price": fav_price,
            "price_bin": price_bin(fav_price),
            # proxy for V06 effective-N (open Q: series vs event slug)
            "event_cluster_id": r.get("series"),
        }
    tickers = sorted(meta.keys())
    print(f"loaded {len(tickers)} tickers from {SRC}")

    # resume state
    existing_rows, pulled_prev, missing_prev = [], set(), set()
    if os.path.exists(OUTPKL):
        existing_rows = pickle.load(open(OUTPKL, "rb"))
    if os.path.exists(MANIFEST):
        m0 = json.load(open(MANIFEST))
        pulled_prev = set(m0.get("pulled_tickers", []))
        missing_prev = set(m0.get("missing_tickers", []))
    todo = [t for t in tickers if t not in pulled_prev]
    print(f"resume: skip {len(tickers) - len(todo)} already pulled; todo {len(todo)}")

    all_rows = list(existing_rows)
    pulled = set(pulled_prev)
    missing = set(missing_prev)

    for i, t in enumerate(todo):
        m = meta[t]
        start = m["created_ts"] - 86400
        end = m["close_ts"] + 3600
        _t0 = time.time()
        cs = pull_market(t, start, end)
        if i < 5 or (i + 1) % 25 == 0:
            print(f"  [{i+1}] {t} win={(end-start)/60:.0f}min candles={len(cs)} took={time.time()-_t0:.1f}s", flush=True)
        if not cs:
            missing.add(t)
        for c in sorted(cs, key=lambda c: c.get("end_period_ts", 0)):
            yb = c.get("yes_bid") or {}
            ya = c.get("yes_ask") or {}
            bc = fnum(yb.get("close_dollars"))
            ac = fnum(ya.get("close_dollars"))
            all_rows.append({
                "ts": int(c.get("end_period_ts", 0)),
                "ticker": t,
                "series": m["series"],
                "bid_open": fnum(yb.get("open_dollars")),
                "bid_high": fnum(yb.get("high_dollars")),
                "bid_low": fnum(yb.get("low_dollars")),
                "bid_close": bc,
                "ask_open": fnum(ya.get("open_dollars")),
                "ask_high": fnum(ya.get("high_dollars")),
                "ask_low": fnum(ya.get("low_dollars")),
                "ask_close": ac,
                "mid": (bc + ac) / 2 if (bc is not None and ac is not None) else None,
                "spread": (ac - bc) if (bc is not None and ac is not None) else None,
                "volume": fnum(c.get("volume_fp")),
                "fav_side": m["fav_side"],
                "fav_price": m["fav_price"],
                "price_bin": m["price_bin"],
                "event_cluster_id": m["event_cluster_id"],
                "set": "primary",
            })
        pulled.add(t)
        if (i + 1) % 25 == 0 or i + 1 == len(todo):
            all_rows.sort(key=lambda r: (r["ticker"], r["ts"]))
            pickle.dump(all_rows, open(OUTPKL, "wb"))
            write_manifest(pulled, missing, all_rows, tickers)
            print(f"  {i + 1}/{len(todo)}  rows={len(all_rows)}  missing={len(missing)}", flush=True)
        time.sleep(SLEEP)

    all_rows.sort(key=lambda r: (r["ticker"], r["ts"]))
    pickle.dump(all_rows, open(OUTPKL, "wb"))
    mf = write_manifest(pulled, missing, all_rows, tickers)
    print(f"\nSaved {mf['n_candles']} candles for "
          f"{mf['n_markets_with_candles']}/{mf['n_markets_expected']} markets -> {OUTPKL}")
    print(f"coverage {mf['coverage_pct']}%  missing {len(missing)}: {sorted(missing)[:10]}")
    print(f"manifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
