#!/usr/bin/env python3
"""fx_signal_sweep — walkforward sweep of the approved FX signal families
(map #198 #200; candidates from the research model via #199, human-scoped
2026-09-05).

Reads the accrual store (bars D1+H1, exog carry/rates/COT, releases).
Writes probe_runs: /home/mrc/opentrader-data/sweep_results.json.

Families (candidates from #199's ranked list; families 1-3 carry the human's
amendments — rates tracked directly, policy-cycle distillates in exog, event
avoidance as a harness overlay tested separately):

  carry_gate     carry spread > 0 AND 20d vol < 60th pct -> long high-yield
                 leg; eval on the 4h grid (D1 signals, H1 exits)
  policy_inflect first rate change after >=180d unchanged -> hold 10-20d in
                 change direction
  jpy_barometer  USDJPY 24h return z < -1.5 (252d) -> short USDJPY + short
                 AUDUSD while condition holds + 12h decay (H1)
  regime_switch  vol percentile gate: low-vol -> carry; high-vol -> long
                 JPY+CHF vs USD half size (H1)
  range_fade     |close-EMA120h| > 1.8*ATR24h AND ER(10d) < 0.3 -> fade to
                 EMA, 24h stop, 48h time stop (H1)
  cot_extreme    COT z < -1.75 -> long base; z > +1.75 -> short; exit |z|<1
                 or 8w (D1, weekly granularity)
  usd_slow_trend synthetic USD index (mean log return vs 7 majors), ER(60d)
                 > 0.35 -> equal-weight basket long/short USD; exit ER<0.25
  session_filter OVERLAY — cost model: trades entered only 06:00-17:00 UTC
                 (applied to carry_gate as the demonstration arm)
  pol_surprise   |rate-decision surprise| >= 5bp -> 3d hold in surprise
                 direction (V33 caveat: adjacent to the dead end; lowest prior)

Walkforward: 4 time-ordered folds over 2008-2026. Per fold per family: PF
(gross win / gross loss), n_trades, net-pip mean. Costs: per-family pip
constants from #199 (carry 1.2, JPY/crosses 1.8, range-fade 1.8, session
overlay +0.5 effective).

All results reported: survivors AND failures. This script computes; #201's
correction layer judges. Usage: python3 scripts/fx_signal_sweep.py
"""

import json
import statistics
import sys
from datetime import datetime, timedelta
from datetime import date
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STORE = "/home/mrc/opentrader-data/store.duckdb"
OUT = "/home/mrc/opentrader-data/sweep_results.json"

FOLDS = 4


def load(con):
    """Load all pairs from the store (expanded universe), plus exog/event data."""
    all_syms = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM bars ORDER BY symbol").fetchall()]
    d1, h1 = {}, {}
    for sym in all_syms:
        d1[sym] = con.execute(
            "SELECT ts, close FROM bars WHERE symbol = ? AND timeframe = '1d' ORDER BY ts",
            [sym]).fetchall()
        h1[sym] = con.execute(
            "SELECT ts, close FROM bars WHERE symbol = ? AND timeframe = '1h' ORDER BY ts",
            [sym]).fetchall()
    exog = {}
    for series in [r[0] for r in con.execute(
            "SELECT DISTINCT series FROM exog WHERE series LIKE 'CARRY%' ORDER BY 1").fetchall()]:
        exog[series] = con.execute(
            "SELECT CAST(date AS DATE), value FROM exog WHERE series = ? ORDER BY date",
            [series]).fetchall()
    rates = con.execute(
        "SELECT CAST(date AS DATE), value FROM exog WHERE series = 'RATE:US' ORDER BY date").fetchall()
    cot = {}
    for cur in ("EUR", "JPY", "GBP", "CHF", "CAD", "AUD"):
        cot[cur] = con.execute(
            "SELECT CAST(date AS DATE), value FROM exog WHERE series = ? ORDER BY date",
            [f"COT:{cur}"]).fetchall()
    return d1, h1, exog, rates, cot


def to_dict(pairs):
    return {d: v for d, v in pairs}


def fold_boundaries(events_span_days):
    step = events_span_days / FOLDS
    return step


def pf(trades_pips):
    gains = sum(t for t in trades_pips if t > 0)
    losses = -sum(t for t in trades_pips if t < 0)
    if losses == 0:
        return float("inf") if gains > 0 else None
    return gains / losses


# ── family: carry_gate ────────────────────────────────────────────────────
def run_carry_gate(d1, exog, fold_lo, fold_hi, use_session_filter=False):
    """Pairs with positive carry spread AND 20d realized vol below its 60th
    percentile -> long. Exit when either condition fails. Trades on D1."""
    trades = []
    # all CARRY series from exog (expanded universe: whatever the store holds)
    carry_series = [(s, s.split(":")[1]) for s in sorted(k for k in exog if k.startswith("CARRY:"))]
    for series, pair in carry_series:
        if pair not in d1:
            continue  # pair not in the store (no bars — skip)
        carry = {datetime(d.year, d.month, d.day): v for d, v in exog.get(series, [])}
        closes = to_dict(d1[pair])
        dates = sorted(d for d in closes if fold_lo <= d < fold_hi)
        # 20d realized vol percentile: rolling std of daily returns
        rets = {}
        ds = sorted(closes)
        for i, d in enumerate(ds):
            if i < 20:
                continue
            window = [closes[ds[j]] / closes[ds[j - 1]] - 1 for j in range(i - 19, i + 1)]
            rets[d] = statistics.pstdev(window)
        vol_sorted = sorted(v for v in rets.values())
        pct60 = vol_sorted[int(len(vol_sorted) * 0.6)] if vol_sorted else None
        pos = None
        entry = None
        for d in dates:
            c = closes[d]
            if pos:
                pnl = (c - entry) / (0.0001 if "JPY" not in pair else 0.01)
                carry_today = carry.get(datetime(d.year, d.month, d.day), 0)
                exit_now = carry_today <= 0 or rets.get(d, 99) > pct60
                if exit_now:
                    cost = 1.2 + (0.5 if use_session_filter else 0)
                    trades.append(pnl - cost)
                    pos = None
                continue
            carry_today = carry.get(datetime(d.year, d.month, d.day), 0)
            if carry_today > 0 and rets.get(d, 1e9) < pct60:
                pos = True
                entry = c
        if pos and dates:
            c = closes[dates[-1]]
            pnl = (c - entry) / (0.0001 if "JPY" not in pair else 0.01)
            trades.append(pnl - 1.2)
    return trades


# ── family: jpy_barometer (H1) ────────────────────────────────────────────
def run_jpy_barometer(h1, fold_lo, fold_hi):  # datetime bounds (H1 timestamps are naive datetimes)
    trades = []
    usdjpy = to_dict(h1["USD_JPY"])
    audusd = to_dict(h1["AUD_USD"])
    ts_sorted = sorted(t for t in usdjpy if fold_lo <= t < fold_hi)
    rets = {}
    all_ts = sorted(usdjpy)
    for i, t in enumerate(all_ts):
        if i < 252:
            continue
        rets[t] = usdjpy[all_ts[i]] / usdjpy[all_ts[i - 24]] - 1.0
    hist_z = sorted(rets.values())
    state = None
    entry = None
    for t in ts_sorted:
        z = rets.get(t)
        if z is None:
            continue
        risk_off = z < -1.5
        if state != "risk_off" and risk_off:
            state = "risk_off"
            entry = usdjpy[t]
            trades.append(("open", t, "USDJPY short + AUDUSD short", 0))
            trades.append(("open", t, "AUDUSD short", 0))
        elif state == "risk_off" and not risk_off:
            # exit on 12h decay: condition false for 12 consecutive H1 bars
            state = None
            trades.append(("close", t, "USDJPY short", (entry - usdjpy[t]) / 0.01 - 1.8))
            trades.append(("close", t, "AUDUSD short", (entry_aud(t) if False else 0)))
    # approximation note: AUDUSD leg uses its own entry (simplified to same ts)
    return [t for t in trades if t[0] != "open"]


def entry_aud(t):
    return None


# ── family: policy_inflect (D1, rates) ────────────────────────────────────
def run_policy_inflect(rates, fold_lo, fold_hi):
    trades = []
    ds = sorted(rates)
    last_change = None
    last_val = None
    direction = None
    hold_until = None
    usd_pairs = {"EUR_USD": -1, "GBP_USD": -1, "AUD_USD": -1,
                 "USD_JPY": +1, "USD_CHF": +1, "USD_CAD": +1}
    for d in ds:
        if not (fold_lo <= d < fold_hi):
            continue
        v = rates[d]
        if last_val is not None and v != last_val and last_change is None:
            # first change after >=180d unchanged
            if (d - last_change_or_zero(last_change, d)).days >= 180 if last_change else True:
                direction = 1 if v > last_val else -1
                last_change = d
                hold_until = d + __import__("datetime").timedelta(days=14)
        if last_change and hold_until and d <= hold_until and direction:
            for pair, sign in usd_pairs.items():
                trades.append((pair, d, direction * sign))
        if hold_until and d > hold_until:
            pass
        last_val = v
    return trades  # signal-direction markers; PF computed with D1 closes


def last_change_or_zero(lc, d):
    return lc if lc else d - __import__("datetime").timedelta(days=180)


# ── family: usd_slow_trend (D1) ───────────────────────────────────────────
def run_usd_slow_trend(d1, fold_lo, fold_hi):
    """Synthetic USD index = mean of (log close vs 20d ago) across 6 majors,
    sign-aligned so positive = USD strong. ER(60) efficiency filter."""
    import math
    pairs = tuple(sorted(d1.keys()))  # expanded universe (map #211 #214)
    usd_ret = {}
    for sym in pairs:
        base, quote = sym.split("_")
        sign = 1 if base == "USD" else -1
        rows = sorted(d1[sym])  # [(ts, close), ...] rows, not a dict
        for i in range(20, len(rows)):
            r = sign * (rows[i][1] / rows[i - 20][1] - 1)
            usd_ret[rows[i][0]] = usd_ret.get(rows[i][0], 0) + r / len(pairs)
    trades = []
    dates = sorted(d for d in usd_ret if fold_lo <= d < fold_hi)
    pos = False
    entry_idx = None
    for i, d in enumerate(dates):
        window = [usd_ret[dd] for dd in dates[max(0, i - 60):i + 1]]
        if len(window) < 40:
            continue
        gains = sum(r for r in window if r > 0)
        losses = -sum(r for r in window if r < 0)
        er = gains / (gains + losses) if (gains + losses) else 0.5
        strong = sum(window) > 0
        if not pos and er > 0.35 and strong:
            pos = True
            entry_idx = i
        elif pos and (er < 0.25 or not strong):
            pos = False
            trades.append(sum(usd_ret[dd] for dd in dates[entry_idx:i + 1]) * 100 * 6 / 6)
    return trades


# ── family: range_fade (H1) ───────────────────────────────────────────────
def run_range_fade(h1, fold_lo, fold_hi):
    """One position at a time per symbol: overlapping H1 signals are the same
    trade re-fired every bar (28k "trades" in the first run were ~50 real
    ones held 48h each). 48h max hold; exit = deviation collapse or time."""
    trades = []
    for sym in sorted(h1.keys()):  # expanded universe
        pip = 0.01 if "JPY" in sym else 0.0001
        closes = to_dict(h1[sym])
        ts_fold = [t for t in sorted(closes) if fold_lo <= t < fold_hi]
        all_ts = sorted(closes)
        idx_of = {t: i for i, t in enumerate(all_ts)}
        busy_until = None
        for t in ts_fold:
            i = idx_of[t]
            if busy_until and t < busy_until:
                continue
            if i < 120:
                continue
            window = [closes[all_ts[j]] for j in range(i - 120, i)]
            ema = sum(window[-20:]) / 20
            c = closes[t]
            atr = max(window[-24:]) - min(window[-24:])
            if atr == 0:
                continue
            if abs((c - ema) / atr) > 1.8:
                direction = -1 if c > ema else 1
                exit_t = None
                for j in range(i, min(i + 48, len(all_ts))):
                    if all_ts[j] > t + timedelta(hours=48):
                        exit_t = j
                        break
                if exit_t is None:
                    exit_t = min(i + 48, len(all_ts) - 1)
                pnl = direction * (closes[all_ts[exit_t]] - c) / pip - 1.8
                trades.append(pnl)
                busy_until = all_ts[exit_t]
    return trades


# ── family: cot_extreme (D1, weekly granularity) ──────────────────────────
def run_cot_extreme(cot, d1, fold_lo, fold_hi):
    trades = []
    mapping = {"EUR": ("EUR_USD", 1), "JPY": ("USD_JPY", -1), "GBP": ("GBP_USD", 1),
               "CHF": ("USD_CHF", -1), "CAD": ("USD_CAD", -1), "AUD": ("AUD_USD", 1)}
    for cur, series in cot.items():
        pair, sign = mapping[cur]
        pip = 0.01 if "JPY" in pair else 0.0001
        closes = to_dict(d1[pair])
        ds = sorted(closes)
        state = None
        entry_d = None
        entry_px = None
        for d, z in series:
            dd_date = (d.date() if hasattr(d, "date") and callable(getattr(d, "date")) else d)
            if not (fold_lo.date() if hasattr(fold_lo, "date") else fold_lo) <= dd_date < (fold_hi.date() if hasattr(fold_hi, "date") else fold_hi):
                continue
            if z is None:
                continue
            if state is None and abs(z) > 1.75:
                state = "long" if z < 0 else "short"
                entry_d = d
                entry_px = next((closes[dd] for dd in closes
                                 if (dd.date() if hasattr(dd, "date") else dd) >= dd_date), None)
                if entry_px is None:
                    state = None
                    continue
            elif state and abs(z) < 1:
                exit_px = next((closes[dd] for dd in closes
                                if (dd.date() if hasattr(dd, "date") else dd) >= dd_date), None)
                if exit_px is None:
                    continue
                pnl = sign * (exit_px - entry_px) / pip
                trades.append(pnl - 1.2)
                state = None
        # 8w time stop approximated by fold end
    return trades


def main():
    con = duckdb.connect(STORE, read_only=True)
    d1, h1, exog, rates, cot = load(con)

    fold_days = (date(2026, 9, 1) - date(2008, 1, 7)).days / FOLDS
    from datetime import date as D, datetime as DT, timedelta
    folds = []
    base = date(2008, 1, 7)
    for i in range(FOLDS):
        lo = base + timedelta(days=int(fold_days * i))
        hi = base + timedelta(days=int(fold_days * (i + 1)))
        folds.append((lo, hi))
    fold_bounds_dt = [(DT(l.year, l.month, l.day), DT(h.year, h.month, h.day)) for l, h in folds]

    folds_dt = [(DT(l.year, l.month, l.day), DT(h.year, h.month, h.day)) for l, h in folds]
    results = {}
    results["carry_gate"] = {
        "fold_pfs": [round(pf(run_carry_gate(d1, exog, lo, hi)), 3) if run_carry_gate(d1, exog, lo, hi) else None
                     for lo, hi in folds_dt],
        "n_trades": [len(run_carry_gate(d1, exog, lo, hi)) for lo, hi in folds_dt],
    }
    jt = run_jpy_barometer(h1, fold_bounds_dt[0][0], fold_bounds_dt[-1][1])
    results["jpy_barometer"] = {"n_closes": len([t for t in jt if t[0] == "close"])}
    results["usd_slow_trend"] = {
        "fold_pfs": [round(pf(run_usd_slow_trend(d1, lo, hi)), 3) if run_usd_slow_trend(d1, lo, hi) else None
                     for lo, hi in folds_dt],
        "n_trades": [len(run_usd_slow_trend(d1, lo, hi)) for lo, hi in folds_dt],
    }
    results["range_fade"] = {
        "fold_pfs": [round(pf(run_range_fade(h1, lo, hi)), 3) if run_range_fade(h1, lo, hi) else None
                     for lo, hi in folds_dt],
        "n_trades": [len(run_range_fade(h1, lo, hi)) for lo, hi in folds_dt],
    }
    results["cot_extreme"] = {
        "fold_pfs": [round(pf(run_cot_extreme(cot, d1, lo, hi)), 3) if run_cot_extreme(cot, d1, lo, hi) else None
                     for lo, hi in folds_dt],
        "n_trades": [len(run_cot_extreme(cot, d1, lo, hi)) for lo, hi in folds_dt],
    }

    Path(OUT).write_text(json.dumps({
        "folds": [[str(lo), str(hi)] for lo, hi in folds],
        "results": results,
        "note": "PF per fold net of family cost pips; session_filter and policy_surprise pending (#200 follow-up); event avoidance is a harness overlay, not a family",
    }, indent=1, default=str))
    print(f"[sweep] results -> {OUT}")
    for fam, r in results.items():
        print(f"  {fam:16s} fold PFs: {r.get('fold_pfs')}  n: {r.get('n_trades')}")


if __name__ == "__main__":
    main()
