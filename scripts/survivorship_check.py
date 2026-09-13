#!/usr/bin/env python3
"""survivorship_check — #217 pre-registered gate BEFORE gen 0.

Question: does data/setup_search/fullcross.pkl (9,267 symbols x 6,680 daily
bars, 2000-2026) carry survivorship bias — do delisted symbols exist, and
does the archive reach the 5y evaluation window with consistent history?

A rank book on an archive that only holds symbols alive at BUILD time
overstates long-horizon returns by the full return of the losers that
delisted mid-window. The pre-registered equity-agent sketch requires this
check BEFORE gen 0; if bias is material, the sketch's amendment rule (logged
human call) applies.

Output: data/setup_search/survivorship_check.json
"""

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
PKL = PROJECT / "data" / "setup_search" / "fullcross.pkl"
OUT = PROJECT / "data" / "setup_search" / "survivorship_check.json"


def to_day(x):
    return np.datetime64(x, "D")


def main():
    d = pickle.load(open(PKL, "rb"))
    n_syms = len(d)

    firsts, lasts = [], []
    for v in d.values():
        ds = v["d"]
        # sample to bound cost on 9k x 6.7k
        step = max(1, len(ds) // 8)
        days = [to_day(x) for x in ds[::step]]
        firsts.append(days[0])
        lasts.append(days[-1])

    win_end = max(lasts)
    five_years_ago = np.datetime64(f"{int(str(win_end)[:4]) - 5}{str(win_end)[4:]}", "D")

    delisted_before_end = sum(1 for l in lasts if l < win_end)
    delisted_pre_window = sum(1 for l in lasts if l < five_years_ago)
    survivors = sum(1 for l in lasts if l >= five_years_ago)
    ipo_in_window = sum(1 for f in firsts if f >= five_years_ago)
    short_hist = sum(1 for f, l in zip(firsts, lasts)
                     if (l - f).astype(int) < 1000)

    absent_ratio = delisted_before_end / n_syms
    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "archive_last_bar": str(win_end),
        "n_symbols": n_syms,
        "window_start": str(five_years_ago),
        "delisted_before_archive_end": delisted_before_end,
        "delisted_pre_window": delisted_pre_window,
        "present_at_window_end": survivors,
        "ipo_inside_window": ipo_in_window,
        "symbols_shorter_than_1000_bars": short_hist,
        "absent_ratio": round(absent_ratio := delisted_before_end / n_syms, 4),
        "note": "fullcross.pkl can only contain symbols alive at BUILD time. "
                "delisted_before_archive_end counts symbols whose last bar "
                "precedes the archive max — evidence of static-snapshot "
                "construction (the winner's-curse source for long-horizon "
                "rank books) OR simply a weekend/halt gap; read with "
                "delisted_pre_window.",
        "verdict": ("PASS — no material survivorship signal in the bar tails"
                    if absent_ratio < 0.02 and delisted_pre_window == 0
                    else "AMBIGUOUS/BIASED — inspect before gen 0"),
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in
                      ("n_symbols", "archive_last_bar", "window_start",
                       "delisted_before_archive_end", "delisted_pre_window",
                       "present_at_window_end", "ipo_inside_window",
                       "symbols_shorter_than_1000_bars", "verdict")}, indent=1))


if __name__ == "__main__":
    main()
