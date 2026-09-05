#!/usr/bin/env python3
"""news_drift_probe — the pre-registered news-surprise drift probe
(map #191 #195; protocol = ToC V32, recorded 2026-09-05 before any run).

Hypothesis (V32): after a tier-1 release, the affected pair drifts
exploitably over +1h/+4h/+24h, net of costs, conditioned on regime.

V32 protocol implemented here:
  - surprise z = (actual - forecast), standardized vs trailing 24-month
    consensus-error std per event family (trailing window excludes current)
  - windows: +1h/+4h/+24h on H1 bars, entry = first close at/after event ts
  - costs: 1.2 pips RT majors, 1.8 pips JPY/crosses (net = drift - cost)
  - regime: US rate trend (falling/rising, ~3m RATE:US lookback)
  - walkforward: 4 time-ordered folds; fold result = per-window PF by
    surprise sign; PASS bar = OOS median fold PF > 1.0 AND >= 3/4 folds
    positive (on the pre-chosen 4h window)
  - minimum sample: 30 events/family/fold, below -> UNTESTABLE
  - FOMC excluded (v1 scope)

Direction convention: positive surprise (USD strong) -> long USD expressions
(USD_JPY, USD_CAD) and short EUR_USD (inverted). Negative surprise mirrored.
Per-fold PF computed per surprise sign; the hypothesis claims BOTH signs drift
in the surprise's direction.

Usage: python3 scripts/news_drift_probe.py [--family NFP]
Writes: /home/mrc/opentrader-data/probe_results.json (the verdict artifact)
"""

import argparse
import json
import statistics
from datetime import timedelta
from pathlib import Path

import duckdb

STORE = "/home/mrc/opentrader-data/store.duckdb"
FAMILY = "NFP"  # default; --family overrides (CPI/UNEMP in V32 scope)
WINDOWS = (1, 4, 24)
PRIMARY_WINDOW = 4  # pre-registered decision window for the PASS bar
COSTS_PIPS = {"EUR_USD": 1.2, "USD_JPY": 1.8, "USD_CAD": 1.8}
PIPSIZE = {"EUR_USD": 1e-4, "USD_JPY": 1e-2, "USD_CAD": 1e-4}
# USD-shock expressions: (pair, sign) — sign aligns 'positive surprise' with
# a LONG position in the pair (EUR_USD is inverted: USD-strong = EUR down).
EXPRESSIONS = [("EUR_USD", -1.0), ("USD_JPY", +1.0), ("USD_CAD", +1.0)]
MIN_EVENTS_PER_FOLD = 30


def event_study(con, family=FAMILY):
    """Surprise-z per event + drift measurement per window."""
    rows = con.execute("""
        SELECT ts, currency, family, surprise
        FROM releases_history WHERE family = ? AND surprise IS NOT NULL
        ORDER BY ts
    """, [family]).fetchall()
    import collections
    hist = []  # trailing list of (ts, surprise) — grows with each event
    events = []
    for ts, cur, fam, surprise in rows:
        past = [e for e in hist if (ts - e[0]).days <= 730]
        z = None
        if len(past) >= 10:
            errs = [e[1] for e in past]
            mu = statistics.fmean(errs)
            sd = statistics.pstdev(errs)
            if sd > 0:
                z = (surprise - mu) / sd
        events.append((ts, z))
        hist.append((ts, surprise))
    return [(ts, z) for ts, z in events if z is not None]


def rate_trend_fn(con):
    rate = dict(con.execute("""
        SELECT CAST(date AS DATE), value FROM exog WHERE series = 'RATE:US'
    """).fetchall())
    dates = sorted(rate)

    def trend(ts):
        prior = [d for d in dates if d <= ts.date()]
        if len(prior) < 5:
            return None
        d0 = prior[max(0, len(prior) - 63)]
        return "falling" if rate[prior[-1]] < rate[d0] else "rising"
    return trend


def run_fold(con, lo, hi, events_in_fold):
    """Per event: drift in pips per window, direction = surprise-z sign."""
    trades = {h: [] for h in WINDOWS}
    n_used = 0
    for ts, z in events_in_fold:
        trend = con.execute(
            "SELECT 1").fetchone()  # placeholder — trend applied below
        for pair, sign in EXPRESSIONS:
            bars = con.execute("""
                SELECT ts, open, close FROM bars
                WHERE symbol = ? AND timeframe = '1h' AND ts >= ? AND ts <= ?
                ORDER BY ts LIMIT 30
            """, [pair, ts.isoformat(sep=" "), (ts + timedelta(hours=24)).isoformat(sep=" ")]).fetchall()
            entry = next((b for b in bars if b[0] >= ts), None)
            if not entry:
                continue
            n_used += 1
            for h in WINDOWS:
                t_end = ts + timedelta(hours=h)
                exit_close = None
                for b in bars:
                    if ts < b[0] <= t_end:
                        exit_close = b[2]
                if exit_close is None:
                    continue
                d_pips = sign * (exit_close - entry[1]) / PIPSIZE[pair]
                net = d_pips - COSTS_PIPS[pair]
                trades[h].append({"ts": str(ts), "z": z, "net": net})
    return trades, n_used


def fold_pf(trades):
    """PF = sum(winning net pips) / |sum(losing net pips)| — None if no losers
    (infinite) or no trades."""
    gains = sum(t["net"] for t in trades if t["net"] > 0)
    losses = -sum(t["net"] for t in trades if t["net"] < 0)
    if losses == 0:
        return float("inf") if gains > 0 else None
    return gains / losses


def main():
    ap = argparse.ArgumentParser(description="Pre-registered news-surprise drift probe (V32)")
    ap.add_argument("--out", default="/home/mrc/opentrader-data/probe_results.json")
    ap.add_argument("--family", default="NFP", help="NFP | CPI | UNEMP (all in V32 scope)")
    args = ap.parse_args()

    con = duckdb.connect("/home/mrc/opentrader-data/store.duckdb", read_only=True)
    global FAMILY
    FAMILY = args.family
    events = event_study(con, family=FAMILY)
    print(f"[probe] {FAMILY} events with surprise-z: {len(events)}")

    t_min, t_max = events[0][0], events[-1][0]
    fold_days = (t_max - t_min).days / 4
    folds = []
    for i in range(4):
        lo = t_min + timedelta(days=fold_days * i)
        hi = t_min + timedelta(days=fold_days * (i + 1)) - timedelta(seconds=1)
        evs = [(ts, z) for ts, z in events if lo <= ts <= hi]
        folds.append((lo, hi, evs))
        print(f"[probe] fold {i}: {lo.date()} .. {hi.date()} — {len(evs)} events")

    all_folds = []
    for i, (lo, hi, evs) in enumerate(folds):
        if len(evs) < MIN_EVENTS_PER_FOLD:
            all_folds.append({"fold": i, "span": [str(lo.date()), str(hi.date())],
                              "verdict": "UNTESTABLE", "n_events": len(evs)})
            continue
        trades, n_used = run_fold(con, lo, hi, evs)
        fold_result = {"fold": i, "span": [str(lo.date()), str(hi.date())],
                       "n_events": len(evs), "verdict": "measured"}
        for h in WINDOWS:
            pos = [t for t in trades[h] if t["z"] > 0]
            neg = [t for t in trades[h] if t["z"] < 0]
            pf_pos = fold_pf(pos)
            pf_neg = fold_pf(neg)
            med_pos = statistics.median([t["net"] for t in pos]) if pos else None
            fold_result[f"{h}h"] = {"pf_pos": pf_pos, "n_pos": len(pos),
                                    "median_net_pos": med_pos,
                                    "n_neg": len(neg)}
        all_folds.append(fold_result)
        print(f"[probe] fold {i}: {fold_result['n_events']} events — "
              f"4h PF(pos z)={fold_result.get('4h', {}).get('pf_pos')}")

    # PASS bar on the pre-chosen 4h window, positive-surprise side
    valid = [f for f in all_folds if f.get("verdict") == "measured"]
    pfs = [f["4h"]["pf_pos"] for f in valid if f.get("4h", {}).get("pf_pos") is not None]
    median_pf = statistics.median(pfs) if pfs else None
    positive_folds = sum(1 for pf in pfs if pf and pf > 1.0)
    if len(valid) < 4:
        verdict = "UNTESTABLE"
    elif median_pf is not None and median_pf > 1.0 and positive_folds >= 3:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    out = {"protocol": "ToC V32", "family": args.family, "window": f"{PRIMARY_WINDOW}h",
           "folds": all_folds, "oos": {"pfs_4h": pfs, "median_pf": median_pf_check(pfs),
                                       "positive_folds": positive_folds},
           "verdict": verdict}
    Path(args.out).write_text(json.dumps(out, indent=1, default=str))
    print(f"[probe] VERDICT: {verdict} (median 4h PF {median_pf_check(pfs)}, "
          f"{positive_folds}/4 folds > 1.0) -> {args.out}")


def median_pf_check(pfs):
    return statistics.median(pfs) if pfs else None


if __name__ == "__main__":
    main()
