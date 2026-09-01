#!/usr/bin/env python3
"""fx_traj — trajectory extraction for the value-head pilot (RLHF spec §3).

Extracts ALL raw fade events (c04's condition: close >1.5% below its 20-day
MA, NO COT filter — the COT filter is what the head should learn from data)
over the full cached history, each labeled with the isolated uniform-risk
outcome under the agent_gym engine semantics: entry at signal-bar close,
stop 1.5 / target 2.5 ATR-14 (engine convention), stop checked before target,
14-bar hold, spread deducted once at exit. Trades are evaluated in isolation
(counterfactual: no book caps), so every signal gets a label regardless of
overlap. Outcomes that would exit beyond the data are excluded.

Point-in-time discipline: features use only bars ≤ signal bar; cot_z uses the
3-day publication lag. Walkforward training must additionally require
exit_ts < cutoff so no partially-realized trade leaks its future.
"""

from datetime import datetime, timedelta, timezone

FEATURES = ["fade_depth", "ret5", "ret30", "atr_pct", "pos_in_30d_range", "cot_z"]
FADE = -0.015
ATR_STOP, ATR_TP, HOLD, SPREAD = 1.5, 2.5, 14, 0.0001

# Signed positioning exposure, from the pair-trading perspective (mirrors c08's
# EXPOSURE): buying the pair = long the COT currency (+1) or short it (−1 for
# USD-base majors, where the fade buys USD = shorts the quote currency).
EXPOSURE = {"EUR_USD": ("EUR", +1), "GBP_USD": ("GBP", +1), "AUD_USD": ("AUD", +1),
            "NZD_USD": ("NZD", +1), "USD_JPY": ("JPY", -1), "USD_CHF": ("CHF", -1),
            "USD_CAD": ("CAD", -1)}


def cot_z_signed(exog, sym, ts):
    cur, sign = EXPOSURE.get(sym, (sym.split("_")[0], +1))
    z = _exog_z(exog, "COT:" + cur, ts)
    return None if z is None else round(sign * z, 4)


def _atr14(bars, i):  # engine convention (includes signal bar) — matches agent_gym sizing
    if i < 15 or bars[i] is None:
        return None
    trs = []
    for j in range(i - 14, i + 1):
        if bars[j] is None:
            return None
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


def _iso(date_ts):
    return datetime.fromtimestamp(int(date_ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _exog_z(exog, key, ts):
    series = exog.get(key)
    if not series:
        return None
    d = _iso(ts)
    usable = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    cands = [k for k in series if k <= usable]
    return series[max(cands)] if cands else None


def fade_events(bars, alldates, exog):
    """Yield event dicts for every raw fade signal with a labelable outcome."""
    n = len(alldates)
    for sym, bl in bars.items():
        for i in range(21, n):
            if bl[i] is None:
                continue
            close = bl[i][3]
            ma20 = _ma20_before(bl, i)
            if not ma20 or (close - ma20) / ma20 >= FADE:
                continue
            atr = _atr14(bl, i)
            if not atr or atr <= 0:
                continue
            stop, target = close - ATR_STOP * atr, close + ATR_TP * atr
            r = None
            exit_ts = None
            for j in range(i + 1, n):
                if bl[j] is None:
                    continue
                age = j - i
                if bl[j][2] <= stop:
                    r, exit_ts = (stop - close - SPREAD) / atr, alldates[j]
                    break
                if bl[j][1] >= target:
                    r, exit_ts = (target - close - SPREAD) / atr, alldates[j]
                    break
                if age >= HOLD:
                    r, exit_ts = (bl[j][3] - close - SPREAD) / atr, alldates[j]
                    break
            if r is None:
                continue  # outcome beyond data — unlabelable
            range30 = [bl[j][3] for j in range(max(0, i - 29), i + 1) if bl[j]]
            lo, hi = min(range30), max(range30)
            yield {
                "ts": alldates[i], "exit_ts": exit_ts, "symbol": sym, "bar": i,
                "features": {
                    "fade_depth": round(close / ma20 - 1, 5),
                    "ret5": _mom(bl, i, 5),
                    "ret30": _mom(bl, i, 30),
                    "atr_pct": round(atr / close, 5),
                    "pos_in_30d_range": round((close - lo) / (hi - lo), 4) if hi > lo else None,
                    "cot_z": cot_z_signed(exog, sym, alldates[i]),
                },
                "r_multiple": round(r, 4), "win": 1 if r > 0 else 0,
            }
