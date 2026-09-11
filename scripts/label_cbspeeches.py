#!/usr/bin/env python3
"""T5 — label pairing for the CB-speech fine-tune (GLM plan §4).

Reads the harvested corpus JSONL and pairs each doc with FX outcome labels:
  ret_1d, ret_5d = the doc's base currency vs USD forward return, from
  decision-vintage closes ONLY (doc date -> next full-session closes; never the
  same session — leakage).

Conditioning features at doc time (stress snapshot) are appended as separate
columns so the primary task stays numeric. This is the make-or-break step: the
QLoRA is worthless unless these labels are vintage-clean.

Output: one JSONL, same schema + {ret_1d, ret_5d, stress_*} per doc.

Usage: .venv/bin/python3 scripts/label_cbspeeches.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

STORE = "/home/mrc/opentrader-data/store.duckdb"
CORPUS = "/home/mrc/opentrader-data/feeds/cbspeeches/corpus.jsonl"
OUT = "/home/mrc/opentrader-data/feeds/cbspeeches/corpus_labeled.jsonl"

# bank -> pair used for the "vs USD" return (banks normalized to UPPERCASE).
# FED (USD) has no USD pair — its base currency is the dollar itself, so it
# uses the DXY proxy (broad dollar index) or is skipped for the numeric task.
BANK_PAIR = {
    "ECB": "EUR_USD", "BOJ": "USD_JPY", "BOE": "GBP_USD", "RBA": "AUD_USD",
    "FED": None,
}
DXY_PROXY = "FRED:DTWEXBGS"  # nominal broad dollar index (if in exog)
# DXY-style dollar basket (weights) — computed from the FX pairs when the FRED
# index isn't in the store. Exponent sign: + for USD-quote pairs, - for
# base-USD pairs (a rising EUR_USD lowers the dollar index).
DXY_W = [("EUR_USD", -0.576), ("USD_JPY", 0.136), ("GBP_USD", -0.119),
         ("USD_CAD", 0.091), ("USD_SEK", 0.042), ("USD_CHF", 0.036)]

# stress snapshot series -> output column name (same fields as the warden's
# instability table): VIX, US HY OAS, EM HY OAS, UST10Y, curve 2s10s
STRESS_SERIES = {
    "FRED:VIXCLS": "stress_vix_z",
    "FRED:BAMLH0A0HYM2": "stress_us_hy_z",
    "FRED:BAMLEMHYHYLCRPIUSOAS": "stress_em_hy_z",
    "FRED:DGS10": "stress_ust10y_z",
    "FRED:T10Y2Y": "stress_curve_z",
}


def _compute_dxy(closes):
    """DXY-style dollar index level per date from the FX pairs (fallback when
    the FRED index is absent). Unscaled — only ratios matter for returns."""
    pairs = [p for p, _ in DXY_W if p in closes]
    if len(pairs) < 4:
        return {}
    dates = sorted(set.intersection(*(set(closes[p]) for p in pairs)))
    dxy = {}
    for d in dates:
        v = 1.0
        for p, w in DXY_W:
            if p in closes and d in closes[p]:
                v *= closes[p][d] ** w
        dxy[d] = v
    return dxy


def _load_closes(con):
    """pair -> {date: close} for D1 bars; also the DXY proxy series."""
    pairs = {p for p in BANK_PAIR.values() if p} | {p for p, _ in DXY_W}
    closes = {}
    for pair in pairs:
        rows = con.execute(
            "SELECT ts, close FROM bars WHERE symbol=? AND timeframe='1d' ORDER BY ts",
            [pair]).fetchall()
        closes[pair] = {str(ts)[:10]: float(c) for ts, c in rows if c is not None}
    # DXY proxy (daily exog) -> {date: value}; fall back to the FX-pair basket
    dxy = {}
    try:
        rows = con.execute(
            "SELECT date, value FROM exog WHERE series=? ORDER BY date",
            [DXY_PROXY]).fetchall()
        dxy = {str(d)[:10]: float(v) for d, v in rows if v is not None}
    except Exception:
        pass
    if not dxy:
        dxy = _compute_dxy(closes)
    return closes, dxy


def _load_stress(con):
    """series -> {date: value}, plus a trailing 252d z-score per date."""
    out = {}
    for series in STRESS_SERIES:
        rows = con.execute(
            "SELECT date, value FROM exog WHERE series=? ORDER BY date", [series]).fetchall()
        vals = [(str(d)[:10], float(v)) for d, v in rows if v is not None]
        if not vals:
            continue
        dates = [d for d, _ in vals]
        seq = [v for _, v in vals]
        z = {}
        for i in range(len(seq)):
            hist = seq[max(0, i - 251): i + 1]
            mu = sum(hist) / len(hist)
            sd = (sum((x - mu) ** 2 for x in hist) / len(hist)) ** 0.5
            z[dates[i]] = (seq[i] - mu) / sd if sd > 0 else 0.0
        out[series] = (dict(zip(dates, seq)), z)
    return out


def _next_session_dates(closes_by_pair, doc_date, n):
    """Return the closes for the n sessions strictly AFTER doc_date (vintage)."""
    # use the union of all pair dates to find trading sessions after doc_date
    all_days = sorted({d for closes in closes_by_pair.values() for d in closes})
    later = [d for d in all_days if d > doc_date]
    return later[:n]


def main():
    con = duckdb.connect(STORE, read_only=True)
    closes, dxy = _load_closes(con)
    stress = _load_stress(con)
    con.close()

    if not Path(CORPUS).exists():
        print(f"[label] corpus not found: {CORPUS} — run fetch_cbspeeches.py first")
        sys.exit(1)

    labeled = 0
    skipped = 0
    with open(CORPUS) as fin, open(OUT, "w") as fout:
        for line in fin:
            if not line.strip():
                continue
            doc = json.loads(line)
            bank = (doc.get("bank") or "").upper()
            pair = BANK_PAIR.get(bank)
            date = str(doc.get("date") or "")[:10]
            if not date or len(date) != 10:
                skipped += 1
                continue
            ret_1d = ret_5d = None
            if pair and pair in closes:
                c = closes[pair]
                prior = sorted(d for d in c if d <= date)
                later = [d for d in sorted(c) if d > date]
                if prior and later:
                    p0 = c.get(date) or c[prior[-1]]
                    ret_1d = (c[later[0]] / p0 - 1) if p0 else None
                    if len(later) >= 5:
                        ret_5d = (c[later[4]] / p0 - 1) if p0 else None
            elif bank == "FED" and dxy:
                prior = sorted(d for d in dxy if d <= date)
                later = [d for d in sorted(dxy) if d > date]
                if prior and later:
                    p0 = dxy.get(date) or dxy[prior[-1]]
                    ret_1d = (dxy[later[0]] / p0 - 1) if p0 else None
                    if len(later) >= 5:
                        ret_5d = (dxy[later[4]] / p0 - 1) if p0 else None
            doc["ret_1d"] = round(ret_1d, 6) if ret_1d is not None else None
            doc["ret_5d"] = round(ret_5d, 6) if ret_5d is not None else None
            # stress snapshot at doc date (z-score of each series as-of that date)
            for series, col in STRESS_SERIES.items():
                if series in stress:
                    _, z = stress[series]
                    doc[col] = round(z.get(date, 0.0), 4)
            fout.write(json.dumps(doc) + "\n")
            labeled += 1
    print(f"[label] paired {labeled} docs (skipped {skipped}) -> {OUT}")


if __name__ == "__main__":
    main()
