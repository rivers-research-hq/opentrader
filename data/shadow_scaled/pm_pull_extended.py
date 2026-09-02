"""
pm_pull_extended: Backward sim-universe extension (Aug 17-24).

Pulls ALL closed binary markets from Aug 17 00:00 UTC to Aug 24 23:59 UTC,
applies EXACTLY the pm_pull_holdout.py pipeline (hourly first-real-candle probe,
spread <= 0.10, p_first_real in (0.001, 0.999)), and writes:
  1. Extended market metadata pkl (like pm_kalshi_live3_real.pkl)
  2. Extended 1-min flat pkl (like pm_kalshi_1min_flat.pkl)
  3. Manifest JSON

Read-only API, no-auth, zero-capital. NEW files only — never touches primary pkls.

Usage:
    python3 pm_pull_extended.py

Outputs (all NEW, additive):
    pm_kalshi_extended_real.pkl
    pm_kalshi_extended_1min.pkl
    pm_kalshi_extended_1min.manifest.json
"""
import requests, time, pickle, json, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

UA = {"User-Agent": "edge-probe/0.1 (read-only research)"}
K = "https://api.elections.kalshi.com/trade-api/v2"
OUT = "/home/mrc/opentrader/data/shadow_scaled"
REAL_SPREAD = 0.10
FEE = 0.07
CHUNK = 5


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
                time.sleep(2.5 + 1.5 * a)
                continue
            print(f"  HTTP {r.status_code} {url} :: {r.text[:140]}")
            return None
        except Exception:
            time.sleep(2.0 + a)
    return None


def fetch_closed(a, b, cap_pages=200):
    out, cursor = [], ""
    for pg in range(cap_pages):
        p = {"status": "closed", "min_close_ts": a, "max_close_ts": b, "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        body = get(f"{K}/markets", p)
        if not body:
            break
        ms = body.get("markets", [])
        if not ms:
            break
        out.extend(ms)
        cursor = body.get("cursor") or ""
        if not cursor:
            break
        time.sleep(0.5)
    return out


def q(qd, key):
    v = (qd or {}).get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def build_flat_rows(csmap, sel, result_map, feat_map):
    """Build 1-min flat rows from candlestick data, matching pm_kalshi_1min_flat.pkl schema.

    fav_side/fav_price/price_bin are CONSTANT per market (from p_first_real),
    matching the primary flat pkl convention.
    """
    rows = []
    for m in sel:
        t = m["ticker"]
        cs = csmap.get(t, [])
        if not cs:
            continue
        cs = sorted(cs, key=lambda c: c.get("end_period_ts", 0))
        close_ts = ts(m["close_time"])
        pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts] or cs
        result = result_map.get(t)
        if result is None:
            continue
        # Per-market constants from first-real-candle (matching primary pkl)
        feat = feat_map.get(t)
        if feat is None or feat.get("n_real", 0) == 0:
            continue
        p_first_real = feat["p_first_real"]
        fav_side = "yes" if p_first_real >= 0.5 else "no"
        fav_price = max(p_first_real, 1 - p_first_real)
        if fav_price > 0.99:
            price_bin = "0.99-1.00"
        elif fav_price > 0.95:
            price_bin = "0.95-0.99"
        elif fav_price > 0.90:
            price_bin = "0.90-0.95"
        else:
            price_bin = "other"
        series = (m.get("event_ticker") or "")[:16]
        for c in pre:
            yb_o = q(c.get("yes_bid"), "open_dollars")
            yb_h = q(c.get("yes_bid"), "high_dollars")
            yb_l = q(c.get("yes_bid"), "low_dollars")
            yb_c = q(c.get("yes_bid"), "close_dollars")
            ya_o = q(c.get("yes_ask"), "open_dollars")
            ya_h = q(c.get("yes_ask"), "high_dollars")
            ya_l = q(c.get("yes_ask"), "low_dollars")
            ya_c = q(c.get("yes_ask"), "close_dollars")
            if yb_c is None or ya_c is None:
                continue
            mid = (yb_c + ya_c) / 2
            spread = ya_c - yb_c
            rows.append({
                "ts": c.get("end_period_ts", 0),
                "ticker": t,
                "series": series,
                "bid_open": yb_o, "bid_high": yb_h, "bid_low": yb_l, "bid_close": yb_c,
                "ask_open": ya_o, "ask_high": ya_h, "ask_low": ya_l, "ask_close": ya_c,
                "mid": mid,
                "spread": spread,
                "volume": float(c.get("volume", 0) or 0),
                "fav_side": fav_side,
                "fav_price": fav_price,
                "price_bin": price_bin,
                "event_cluster_id": series,
                "set": "extended",
            })
    return rows


def main():
    t0 = time.time()
    A = ts("2026-08-17T00:00:00Z")
    B = ts("2026-08-25T00:00:00Z")
    print(f"Pulling closed binary markets Aug 17 00:00Z -> Aug 24 23:59Z ...")
    ms = fetch_closed(A, B)
    sel = [m for m in ms if m.get("market_type") == "binary"]
    print(f"  total closed: {len(ms)}  binary: {len(sel)}")
    sel.sort(key=lambda m: ts(m["close_time"]))

    # Build result map. Aug 17-24 markets have status=closed with EMPTY result
    # (not yet finalized by Kalshi). For those, infer from last candle's yes_ask:
    #   yes_ask_close >= 0.5  ->  result = 0 ("no")
    #   yes_ask_close <  0.5  ->  result = 1 ("yes")
    # Markets with a populated API result use that directly.
    result_map = {}
    for m in sel:
        api_res = m.get("result")
        if api_res in ("yes", "no"):
            result_map[m["ticker"]] = 1 if api_res == "yes" else 0
        # else: leave out; will be filled in after candle pull

    # Pull candlesticks in chunks. Cap the time window to avoid the
    # 10,000-candle API limit (5 markets × 1440 min = 7200 max).
    feats = []
    all_flat_rows = []
    MAX_WINDOW = 1440 * 60  # 24 hours in seconds
    for i in range(0, len(sel), CHUNK):
        chunk = sel[i:i + CHUNK]
        start = min(ts(m["created_time"]) for m in chunk) - 86400
        end = max(ts(m["close_time"]) for m in chunk) + 3600
        # If the window is too wide, split into sub-windows
        if end - start > MAX_WINDOW:
            csmap = {}
            while start < end:
                sub_end = min(start + MAX_WINDOW, end)
                sub = pull_chunk([m["ticker"] for m in chunk], start, sub_end, interval=60)
                for k, v in sub.items():
                    if k in csmap:
                        csmap[k].extend(v)
                    else:
                        csmap[k] = list(v)
                start = sub_end
                time.sleep(0.3)
        else:
            csmap = pull_chunk([m["ticker"] for m in chunk], start, end, interval=60)
        # Infer results for markets with empty API result (status=closed, not finalized)
        for m in chunk:
            t = m["ticker"]
            if t in result_map:
                continue
            cs = csmap.get(t, [])
            if not cs:
                continue
            cs = sorted(cs, key=lambda c: c.get("end_period_ts", 0))
            close_ts = ts(m["close_time"])
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts] or cs
            if not pre:
                continue
            last_ya = q(pre[-1].get("yes_ask"), "close_dollars")
            if last_ya is None:
                continue
            result_map[t] = 0 if last_ya >= 0.5 else 1
        for m in chunk:
            t = m["ticker"]
            cs = csmap.get(t, [])
            close_ts = ts(m["close_time"])
            if not cs:
                continue
            cs = sorted(cs, key=lambda c: c.get("end_period_ts", 0))
            pre = [c for c in cs if c.get("end_period_ts", 10**12) <= close_ts] or cs
            rows = []
            for c in pre:
                yb = q(c.get("yes_bid"), "close_dollars")
                ya = q(c.get("yes_ask"), "close_dollars")
                if yb is None or ya is None:
                    continue
                rows.append(((yb + ya) / 2, ya - yb))
            if not rows:
                continue
            if t not in result_map:
                continue
            real = [r for r in rows if r[1] <= REAL_SPREAD]
            f = {
                "ticker": t,
                "result": result_map[t],
                "close_ts": close_ts,
                "created_ts": ts(m["created_time"]),
                "lead_h": (close_ts - ts(m["created_time"])) / 3600.0,
                "volume": float(m.get("volume_fp") or 0),
                "series": (m.get("event_ticker") or "")[:16],
                "p_first_all": rows[0][0],
                "p_last_all": rows[-1][0],
                "n_real": len(real),
                "n_total": len(rows),
            }
            if real:
                f["p_first_real"] = real[0][0]
                f["spread_first_real"] = real[0][1]
                f["p_last_real"] = real[-1][0]
                f["spread_last_real"] = real[-1][1]
            feats.append(f)
        # Build flat rows for this chunk (needs feat_map for per-market constants)
        feat_map = {f["ticker"]: f for f in feats}
        all_flat_rows.extend(build_flat_rows(csmap, chunk, result_map, feat_map))
        print(f"  pulled {min(i + CHUNK, len(sel))}/{len(sel)} (feats {len(feats)}, flat {len(all_flat_rows)})", flush=True)
        time.sleep(0.5)

    # Save metadata pkl
    pickle.dump(feats, guarded_open(meta_pkl, "wb"))
    pickle.dump(feats, open(meta_pkl, "wb"))
    print(f"\nSaved {len(feats)} market features -> {meta_pkl}")

    # Save flat pkl
    flat_pkl = f"{OUT}/pm_kalshi_extended_1min.pkl"
    pickle.dump(all_flat_rows, open(flat_pkl, "wb"))
    print(f"Saved {len(all_flat_rows)} flat candles -> {flat_pkl}")

    # Manifest
    n_markets = len(sel)
    n_with_candles = len(set(r["ticker"] for r in all_flat_rows))
    manifest = {
        "n_markets_expected": n_markets,
        "n_markets_with_candles": n_with_candles,
        "coverage_pct": round(n_with_candles / n_markets * 100, 1) if n_markets else 0,
        "n_candles": len(all_flat_rows),
        "date_range": "2026-08-17 to 2026-08-24",
        "set": "extended",
        "source": "pm_pull_extended.py",
        "pull_ts": int(time.time()),
        "elapsed_s": round(time.time() - t0, 1),
    }
    manifest_path = f"{OUT}/pm_kalshi_extended_1min.manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest -> {manifest_path}")

    # Diagnostic (mirrors pm_pull_holdout.py)
    d = pd.DataFrame([f for f in feats if f.get("n_real", 0) > 0])
    d = d[(d.p_first_real > 0.001) & (d.p_first_real < 0.999)].dropna(
        subset=["p_first_real", "spread_first_real"]).copy()
    p = d.p_first_real
    d["fav_price"] = np.maximum(p, 1 - p)
    d["fav_win"] = np.where(p >= 0.5, d.result, 1 - d.result)
    sp = d.spread_first_real
    d["fav_ask"] = d.fav_price + sp / 2
    d["fav_bid"] = d.fav_price - sp / 2

    print(f"\n=== EXTENDED DIAGNOSTIC (tradeable: {len(d)}) ===")
    print(f"N={len(d)}  fav wins={int(d.fav_win.sum())}/{len(d)}  avg fav_price={d.fav_price.mean():.4f}")
    print(f"avg spread={sp.mean() * 100:.2f}c")

    bins = [0.90, 0.95, 0.99, 1.0]
    for lo, hi in zip(bins[:-1], bins[1:]):
        b = d[(d.fav_price > lo) & (d.fav_price <= hi)]
        if len(b) < 3:
            print(f"  {lo:.2f}-{hi:.2f}  n={len(b)}  (skipped n<3)")
            continue
        mak_e = (b.fav_win - b.fav_bid).mean() * 100
        mid_e = (b.fav_win - b.fav_price - FEE * b.fav_price * (1 - b.fav_price)).mean() * 100
        wins = int(b.fav_win.sum())
        print(f"  {lo:.2f}-{hi:.2f}  n={len(b):>3}  wins={wins}/{len(b)}  mid={mid_e:+.2f}  maker={mak_e:+.2f}   (avg spread {b.spread_first_real.mean() * 100:.1f}c)")

    # 0.95-0.99 cluster view
    bm_ = d[(d.fav_price > 0.95) & (d.fav_price <= 0.99)]
    if len(bm_) >= 3:
        g = bm_.groupby("series").agg(n=("fav_win", "size"), mean_c=("fav_win", "mean"))
        g["maker_c"] = bm_.groupby("series").apply(
            lambda s: (s.fav_win - s.fav_bid).mean() * 100, include_groups=False)
        print(f"\n0.95-0.99 cluster view: n={len(bm_)} clusters={bm_.series.nunique()} max_cluster={g.n.max()}")
        print(g.sort_values("n", ascending=False).to_string())

    print(f"\nElapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
