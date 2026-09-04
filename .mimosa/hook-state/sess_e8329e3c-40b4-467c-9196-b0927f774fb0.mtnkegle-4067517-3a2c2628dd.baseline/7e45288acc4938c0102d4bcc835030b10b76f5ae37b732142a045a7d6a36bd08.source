#!/usr/bin/env python3
"""Append one point to the A/B equity curve (MAIN 19-sym vs SHADOW 28-sym).

Read-only w.r.t. harness state: only READS the two paper_state.json files and
APPENDS to ab_equity.csv. Never writes to either ledger.

Dedup: skip the append if (main_cycle, shadow_cycle) matches the last row, so a
timer firing twice within the same cycle pair does not duplicate a point.

Run manually:  /home/mrc/rocm_venv/bin/python3 ab_log.py
"""
import csv
import json
from pathlib import Path

MAIN = Path("/home/mrc/opentrader/data/paper_state.json")
SHADOW = Path("/home/mrc/opentrader/data/shadow_scaled/paper_state.json")
CSV = Path("/home/mrc/opentrader/data/shadow_scaled/ab_equity.csv")
HDR = [
    "ts",
    "main_cycle", "main_value", "main_cash", "main_npos",
    "shadow_cycle", "shadow_value", "shadow_cash", "shadow_npos",
]


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def row(st):
    return (
        st.get("cycle"),
        round(float(st.get("portfolio_value", 0) or 0), 4),
        round(float(st.get("cash", 0) or 0), 4),
        len(st.get("positions", []) or []),
    )


def main():
    m, s = load(MAIN), load(SHADOW)
    if not m or not s:
        return  # a state file is mid-write or missing; skip this tick
    mc, mv, mca, mn = row(m)
    sc, sv, sca, sn = row(s)
    ts = s.get("timestamp") or m.get("timestamp") or ""

    if CSV.exists():
        try:
            lines = [l for l in CSV.read_text().strip().splitlines() if l]
        except Exception:
            lines = []
        if lines:
            last = lines[-1].split(",")
            if len(last) >= 6 and last[1] == str(mc) and last[5] == str(sc):
                return  # same cycle pair as last point; nothing new
    new = not CSV.exists()
    with open(CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HDR)
        w.writerow([ts, mc, mv, mca, mn, sc, sv, sca, sn])


if __name__ == "__main__":
    main()
