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

# bank -> pair used for the "vs USD" return. Fed (USD) has no USD pair; its
# base currency is the dollar itself, so it uses the DXY proxy below or is
# skipped for the numeric primary task (kept for style/context only).
BANK_PAIR = {
    "ECB": "EUR_USD", "BoJ": "USD_JPY", "BoE": "GBP_USD", "RBA": "AUD_USD",
    "Fed": None,  # USD: no "vs USD" pair — ret via DXY proxy if available
}
DXY_PROXY = "FRED:DTWEXBGS"  # nominal broad dollar index (if in exog)

# stress snapshot series -> output column name (same fields as the warden's
# instability table): VIX, US HY OAS, EM HY OAS, UST10Y, curve 2s10s
STRESS_SERIES = {
    "FRED:VIXCLS": "stress_vix_z",
    "FRED:BAMLH0A0HYM2": "stress_us_hy_z",
    "FRED:BAMLEMHYHYLCRPIUSOAS": "stress_em_hy_z",
    "FRED:DGS10": "stress_ust10y_z",
    "FRED:T10Y2Y": "stress_curve_z",
}


def _load_closes(con):
    """pair -> {date: close} for D1 bars; also the DXY proxy series."""
    pairs = {p for p in BANK_PAIR.values() if p}
    closes = {}
    for pair in pairs:
        rows = con.execute(
            "SELECT ts, close FROM bars WHERE symbol=? AND timeframe='1d' ORDER BY ts",
            [pair]).fetchall()
        closes[pair] = {str(ts)[:10]: float(c) for ts, c in rows if c is not None}
    # DXY proxy (daily exog) -> {date: value}
    dxy = {}
    try:
        rows = con.execute(
            "SELECT date, value FROM exog WHERE series=? ORDER BY date",
            [DXY_PROXY]).fetchall()
        dxy = {str(d)[:10]: float(v) for d, v in rows if v is not None}
    except Exception:
        pass
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
            bank = doc.get("bank")
            pair = BANK_PAIR.get(bank)
            date = str(doc.get("date") or "")[:10]
            if not date or len(date) != 10:
                skipped += 1
                continue
            ret_1d = ret_5d = None
            if pair and pair in closes:
                c = closes[pair]
                later = [d for d in sorted(c) if d > date]
                if later:
                    p0 = c.get(date) or c[sorted(d for d in c if d <= date)[-1]]
                    for i, d in enumerate(later):
                        if i == 0:
                            ret_1d = (c[d] / p0 - 1) if p0 else None
                        if i == 4 and len(later) >= 5:
                            ret_5d = (c[d] / p0 - 1) if p0 else None
            elif bank == "Fed" and dxy:
                later = [d for d in sorted(dxy) if d > date]
                if later:
                    p0 = dxy.get(date) or dxy[sorted(d for d in dxy if d <= date)[-1]]
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
