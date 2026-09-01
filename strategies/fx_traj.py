#!/usr/bin/env python3
"""fx_traj — trajectory extraction for the value head (RLHF spec §3).

Extracts ALL raw fade events (c04's condition: close >1.5% below its 20-day
MA, NO COT filter — the COT filter is what the head should learn from data)
with the isolated uniform-risk outcome under the agent_gym engine semantics:
entry at signal-bar close, stop 1.5 / target 2.5 ATR-14 (engine convention),
stop checked before target, 14-bar hold, spread deducted once at exit.
Trades are evaluated in isolation (counterfactual: no book caps), so every
signal gets a label regardless of overlap. Outcomes that would exit beyond
the data are excluded.

Point-in-time discipline: every feature uses only bars ≤ signal bar; cot_z
uses the 3-day publication lag; the trailing-R meta-feature uses only
events whose own trade FULLY RESOLVED (exit_ts) before this signal. Walkforward
training must additionally require exit_ts < cutoff.

Feature families (v1, 2026-09-01 — the ablation against the 6-feature base
is the claim, see scripts/build_trajectories.py):
  base     fade_depth, ret5/30, atr_pct, pos_in_30d_range, cot_z (v0 set)
  normal   fade_atrs (fade depth in ATR units — vol-normalized)
  vol      atr_ratio (atr14/atr60), vol_pctile (ATR percentile in trailing year)
  trend    ret60, ret120, pos_in_1y_range
  xsec     fade_rank (depth rank among all majors that day — relative fade)
  regime   recent_fade_R (mean R of last 30 fade trades that resolved before
           this signal — the regime meta-feature the yearly table motivates)
  calendar day-of-week dummies (Mon-Thu; Fri is the base)
"""

from datetime import datetime, timedelta, timezone

BASE_FEATURES = ["fade_depth", "ret5", "ret30", "atr_pct", "pos_in_30d_range", "cot_z"]
FEATURES = ["fade_depth", "fade_atrs", "ret5", "ret30", "ret60", "ret120",
            "atr_pct", "atr_ratio", "vol_pctile", "pos_in_30d_range",
            "pos_in_1y_range", "cot_z", "fade_rank", "recent_fade_R",
            "dow_mon", "dow_tue", "dow_wed", "dow_thu"]
FADE = -0.015
ATR_STOP, ATR_TP, HOLD, SPREAD = 1.5, 2.5, 14, 0.0001
TRAILING_N = 30

# Signed positioning exposure, from the pair-trading perspective (mirrors c08's
# EXPOSURE): buying the pair = long the COT currency (+1) or short it (−1 for
# USD-base majors, where the fade buys USD = shorts the quote currency).
EXPOSURE = {"EUR_USD": ("EUR", +1), "GBP_USD": ("GBP", +1), "AUD_USD": ("AUD", +1),
            "NZD_USD": ("NZD", +1), "USD_JPY": ("JPY", -1), "USD_CHF": ("CHF", -1),
            "USD_CAD": ("CAD", -1)}


def _iso(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _exog_z(exog, key, ts):
    series = exog.get(key)
    if not series:
        return None
    d = _iso(ts)
    usable = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    cands = [k for k in series if k <= usable]
    return series[max(cands)] if cands else None


def cot_z_signed(exog, sym, ts):
    cur, sign = EXPOSURE.get(sym, (sym.split("_")[0], +1))
    z = _exog_z(exog, "COT:" + cur, ts)
    return None if z is None else round(sign * z, 4)


def _atr14(bars, i):  # engine convention (includes signal bar) — matches agent_gym sizing
    if i < 15 or bars[i] is None or bars[i - 1] is None:
        return None
    trs = []
    for j in range(i - 14, i + 1):
        if bars[j] is None or bars[j - 1] is None:
            return None
        h, l, pc = bars[j][1], bars[j][2], bars[j - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def _atr(bars, i, n):
    if i < n or any(bars[j] is None or bars[j - 1] is None
                    for j in range(i - n + 1, i + 1)):
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        h, l, pc = bars[j][1], bars[j][2], bars[j - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def _mom(bars, i, k):
    if i < k or bars[i] is None or bars[i - k] is None:
        return None
    return bars[i][3] / bars[i - k][3] - 1


def _ma20_before(bars, i):
    if i < 20 or any(bars[j] is None for j in range(i - 20, i)):
        return None
    return sum(bars[j][3] for j in range(i - 20, i)) / 20.0


def _pctile_in_window(vals, v):
    """Fraction of `vals` below v (0..1). None-safe."""
    if v is None or not vals:
        return None
    return round(sum(1 for x in vals if x < v) / len(vals), 4)


def base_features(sym, i, bars, alldates, exog):
    """Per-pair features at bar i, point-in-time. Returns None if the pair is
    not a fade signal today or data is insufficient for the event definition."""
    bl = bars[sym]
    if i < 21 or bl[i] is None:
        return None
    close = bl[i][3]
    ma20 = _ma20_before(bl, i)
    if not ma20 or (close - ma20) / ma20 >= FADE:
        return None
    atr = _atr14(bl, i)
    if not atr or atr <= 0:
        return None
    atr60 = _atr(bl, i, 60)
    range30 = [bl[j][3] for j in range(max(0, i - 29), i + 1) if bl[j]]
    lo30, hi30 = min(range30), max(range30)
    range1y = [bl[j][3] for j in range(max(0, i - 251), i + 1) if bl[j]]
    lo1y, hi1y = (min(range1y), max(range1y)) if len(range1y) >= 120 else (None, None)
    tr_hist = []
    for j in range(max(15, i - 251), i + 1):
        a = _atr14(bl, j)
        if a:
            tr_hist.append(a)
    fade_depth = close / ma20 - 1
    dow = datetime.fromtimestamp(int(alldates[i]), tz=timezone.utc).weekday()
    return {
        "fade_depth": round(fade_depth, 5),
        "fade_atrs": round((ma20 - close) / atr, 4),
        "ret5": _mom(bl, i, 5),
        "ret30": _mom(bl, i, 30),
        "ret60": _mom(bl, i, 60),
        "ret120": _mom(bl, i, 120),
        "atr_pct": round(atr / close, 5),
        "atr_ratio": round(atr / atr60, 4) if atr60 else None,
        "vol_pctile": _pctile_in_window(tr_hist, atr),
        "pos_in_30d_range": round((close - lo30) / (hi30 - lo30), 4) if hi30 > lo30 else None,
        "pos_in_1y_range": round((close - lo1y) / (hi1y - lo1y), 4) if lo1y is not None and hi1y > lo1y else None,
        "cot_z": cot_z_signed(exog, sym, alldates[i]),
        "dow_mon": 1 if dow == 0 else 0,
        "dow_tue": 1 if dow == 1 else 0,
        "dow_wed": 1 if dow == 2 else 0,
        "dow_thu": 1 if dow == 3 else 0,
    }


def _isolated_outcome(bl, i, atr):
    """Uniform-risk outcome in R units for an entry at bar i's close."""
    close = bl[i][3]
    stop, target = close - ATR_STOP * atr, close + ATR_TP * atr
    n = len(bl)
    for j in range(i + 1, n):
        if bl[j] is None:
            continue
        if bl[j][2] <= stop:
            return (stop - close - SPREAD) / atr, j
        if bl[j][1] >= target:
            return (target - close - SPREAD) / atr, j
        if j - i >= HOLD:
            return (bl[j][3] - close - SPREAD) / atr, j
    return None, None


def build_events(bars, alldates, exog):
    """All fade events with outcome + cross-sectional rank + trailing-R.
    Returns a list sorted by signal time."""
    n = len(alldates)
    # cross-sectional context: EVERY major's fade depth each day (rank is
    # among all 7, faded or not — relative fade, not among signals)
    depth_by_date = {}
    for sym, bl in bars.items():
        for i in range(21, n):
            if bl[i] is None:
                continue
            ma20 = _ma20_before(bl, i)
            if ma20:
                depth_by_date.setdefault(alldates[i], []).append(round(bl[i][3] / ma20 - 1, 5))

    signals = []
    for sym, bl in bars.items():
        for i in range(21, n):
            if bl[i] is None:
                continue
            f = base_features(sym, i, bars, alldates, exog)
            if f is None:
                continue
            signals.append({"ts": alldates[i], "exit_ts": None, "symbol": sym,
                            "bar": i, "features": f, "r_multiple": None, "win": None})
    # cross-sectional rank among ALL majors that day (0 = deepest fade)
    for s in signals:
        depths = sorted(depth_by_date[s["ts"]])
        r = depths.index(s["features"]["fade_depth"])
        s["features"]["fade_rank"] = round(r / max(1, len(depths) - 1), 4)

    # outcomes
    for s in signals:
        bl = bars[s["symbol"]]
        atr = _atr14(bl, s["bar"])
        r, j = _isolated_outcome(bl, s["bar"], atr)
        if r is None:
            continue  # unlabelable
        s["r_multiple"] = round(r, 4)
        s["win"] = 1 if r > 0 else 0
        s["exit_ts"] = alldates[j]

    # trailing realized-R regime meta-feature: last TRAILING_N fade trades
    # whose own trade FULLY RESOLVED (exit) strictly before this signal
    resolved = sorted((s for s in signals if s["exit_ts"] is not None),
                      key=lambda s: s["exit_ts"])
    for s in signals:
        prior = [p["r_multiple"] for p in resolved
                 if p["exit_ts"] < s["ts"]]
        s["features"]["recent_fade_R"] = round(sum(prior[-TRAILING_N:]) / min(TRAILING_N, len(prior)), 4) \
            if prior else None
    return [s for s in signals if s["r_multiple"] is not None]
