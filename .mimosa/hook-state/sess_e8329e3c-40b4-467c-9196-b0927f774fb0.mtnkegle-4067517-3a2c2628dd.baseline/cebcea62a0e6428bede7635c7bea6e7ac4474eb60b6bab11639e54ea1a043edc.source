#!/usr/bin/env python3
"""Prop-firm challenge simulator — dry-run the validated system against each
firm's real rules BEFORE paying any challenge fee.

Replays the validated rule's actual trade sequence (5y daily archive, best.json
config) through each firm's accounting: static/trailing max loss, max daily
loss, profit targets, min trading days, time limits, inactivity clocks and
consistency rules (where they bind). Rulesets are transcribed from
docs/research/prop-firm-challenge-research.md (primary-source verified).

Sizing: the firm's loss limits force a max position size. For a trade with
stop 12.28% (validated), sizing is capped so a full stop-out stays inside both
the daily-loss and max-loss limits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from setup_search.core import clamp_config  # noqa: E402
from setup_search.data import load_ohlcv, align, REGIME_SYM  # noqa: E402
from setup_search.engine import run_backtest  # noqa: E402

STOP_PCT = 0.1228  # validated stop (best.json sl)

# Verified rulesets (docs/research/prop-firm-challenge-research.md)
FIRMS = {
    "ftmo_2step": {
        "name": "FTMO 2-Step (Swing)",
        "targets": [0.10, 0.05], "daily_loss": 0.05, "max_loss": 0.10,
        "trailing": False, "min_days": 4, "time_limit": None,
        "inactivity": None, "best_day_rule": None,
    },
    "ftmo_1step": {
        "name": "FTMO 1-Step",
        "targets": [0.10], "daily_loss": 0.03, "max_loss": 0.10,
        "trailing": True, "min_days": 4, "time_limit": None,
        "inactivity": None, "best_day_rule": 0.50,
    },
    "fundednext_stellar1": {
        "name": "FundedNext Stellar 1-Step",
        "targets": [0.10], "daily_loss": 0.03, "max_loss": 0.06,
        "trailing": False, "min_days": 2, "time_limit": None,
        "inactivity": 60, "best_day_rule": None,
    },
    "the5ers_hyper": {
        "name": "The5ers Hyper Growth",
        "targets": [0.10], "daily_loss": 0.03, "max_loss": 0.06,
        "trailing": False, "min_days": 0, "time_limit": None,
        "inactivity": 30, "best_day_rule": None,
    },
    "apex_eod": {
        "name": "Apex EOD Evaluation (30-day)",
        "targets": [0.06], "daily_loss": 0.02, "max_loss": 0.04,
        "trailing": True, "min_days": 0, "time_limit": 30,
        "inactivity": None, "best_day_rule": None,
    },
}


def _max_sizing(firm: dict, same_day_stops: int = 1) -> float:
    """Max position size so N full stop-outs on one day stay inside the daily
    loss limit, accounting for compounding: day_loss = (s*stop)/(1 - s*stop)
    per stop, N of them. The validated stop is 12.28%; size is the only knob
    (faithful replica, ADR-0001)."""
    per = firm["daily_loss"] / same_day_stops
    s = per / (STOP_PCT * (1.0 + per))  # compounding-aware
    s = min(s, firm["max_loss"] / (STOP_PCT * same_day_stops))
    return max(0.05, s)


def _load_trades(period="5y"):
    cfg = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv(period)
    al = align(data, [s for s in data if s != REGIME_SYM])
    res = run_backtest(al, cfg)
    trades = []
    for t in res["trades"]:
        trades.append({
            "entry": t.get("entry_date"),
            "exit": t.get("exit_date"),
            "pnl": float(t.get("pnl_pct", 0.0)),
        })
    return trades, cfg


def simulate(firm: dict, trades: list) -> dict:
    """Run the trade sequence through one firm's challenge accounting."""
    sizing = _max_sizing(firm, same_day_stops=2)  # survive two same-day stops
    equity = 1.0
    peak = 1.0
    phase = 0
    phases = len(firm["targets"])
    target = 1.0 + firm["targets"][0]
    trade_days = set()
    exit_days = {}
    for t in trades:
        exit_days.setdefault(t["exit"], []).append(t)
    dates = sorted(exit_days.keys())

    fail = None
    fail_date = None
    phase_done_dates = []
    best_positive_day = 0.0
    sum_positive_days = 0.0
    max_daily_loss = 0.0
    max_dd = 0.0

    for d in dates:
        day_pnl = sum(t["pnl"] for t in exit_days[d])
        trade_days.update(t["entry"] for t in exit_days[d])
        prev = equity
        equity *= (1.0 + sizing * day_pnl)
        peak = max(peak, equity)
        daily = (prev - equity) / prev
        max_daily_loss = max(max_daily_loss, daily)
        if day_pnl > 0:
            best_positive_day = max(best_positive_day, day_pnl)
            sum_positive_days += day_pnl
        # max loss check
        if not firm["trailing"]:
            if (1.0 - equity) > firm["max_loss"]:
                fail, fail_date = "max_loss", d
                break
        else:
            if (peak - equity) > firm["max_loss"]:
                fail, fail_date = "max_loss(trailing)", d
                break
        max_dd = max(max_dd, (peak - equity))
        # daily loss check
        if daily > firm["daily_loss"]:
            fail, fail_date = "daily_loss", d
            break
        # target check (phase by phase)
        if equity >= target:
            phase_done_dates.append(d)
            phase += 1
            if phase >= phases:
                break
            equity = 1.0
            peak = 1.0
            target = 1.0 + firm["targets"][phase]
    days_to_target = None
    if phase >= phases and phase_done_dates:
        from datetime import datetime
        days_to_target = (datetime.fromisoformat(str(phase_done_dates[-1]))
                          - datetime.fromisoformat(str(trades[0]["entry"]))).days
    gaps = _trade_gaps(trades)
    inactivity_fail = firm["inactivity"] is not None and gaps > firm["inactivity"]
    time_fail = False
    if firm["time_limit"] and not fail:
        # 30-day clock: does ANY sliding window reach the target without breach?
        time_fail = not _window_pass(firm, trades, sizing)
    return {
        "time_fail": time_fail,
        "sizing": sizing,
        "sizing_1stop": _max_sizing(firm, 1),
        "inactivity_fail": inactivity_fail,
        "pass": fail is None and phase >= phases and not time_fail,
        "fail": fail,
        "fail_date": str(fail_date)[:10] if fail_date else None,
        "days_to_target": days_to_target,
        "n_trades_to_target": sum(1 for t in trades if t["exit"] <= (phase_done_dates[-1] if phase_done_dates else t["exit"])),
        "min_days_met": len(trade_days) >= firm["min_days"],
        "max_daily_loss_seen": max_daily_loss,
        "max_dd_seen": max_dd,
        "longest_gap_days": gaps,
        "inactivity_limit": firm["inactivity"],
        "best_day_ratio": (best_positive_day / sum_positive_days) if sum_positive_days > 0 else None,
        "best_day_rule": firm["best_day_rule"],
    }


def _window_pass(firm: dict, trades: list, sizing: float, window_days: int = 30) -> bool:
    """Does any sliding calendar window of window_days reach the target without
    breaching the loss limits? (time-limited firms like Apex's 30-day eval)."""
    from datetime import datetime, timedelta
    if not trades:
        return False
    t0 = datetime.fromisoformat(str(trades[0]["entry"]))
    t1 = datetime.fromisoformat(str(trades[-1]["exit"]))
    target = 1.0 + firm["targets"][0]
    d = t0
    while d <= t1:
        end = d + timedelta(days=window_days)
        equity = 1.0
        peak = 1.0
        ok = True
        for t in trades:
            e = datetime.fromisoformat(str(t["exit"]))
            if e < d:
                continue
            if e > end:
                break
            prev = equity
            equity *= (1.0 + sizing * t["pnl"])
            peak = max(peak, equity)
            daily = (prev - equity) / prev
            if daily > firm["daily_loss"]:
                ok = False
                break
            if not firm["trailing"] and (1.0 - equity) > firm["max_loss"]:
                ok = False
                break
            if firm["trailing"] and (peak - equity) > firm["max_loss"]:
                ok = False
                break
            if equity >= target:
                return True
        if ok and equity >= target:
            return True
        d += timedelta(days=5)  # slide by 5-day steps
    return False


def _trade_gaps(trades) -> int:
    if not trades:
        return 0
    from datetime import datetime
    entries = sorted(datetime.fromisoformat(str(t["entry"])) for t in trades)
    gaps = [(b - a).days for a, b in zip(entries, entries[1:])]
    return max(gaps) if gaps else 0


def main():
    trades, cfg = _load_trades()
    print(f"[prop-sim] {len(trades)} trades, {cfg['regime_window']}d regime window\n")
    for key, firm in FIRMS.items():
        r = simulate(firm, trades)
        passed = r["pass"] and not r["inactivity_fail"] and not r["time_fail"]
        verdict = "PASS" if passed else (
            "FAIL(inactivity)" if r["inactivity_fail"] else
            "FAIL(time_limit)" if r["time_fail"] else f"FAIL({r['fail']})")
        print(f"{firm['name']:28s} {verdict}")
        print(f"  sizing: {r['sizing']:.0%} (2 same-day stops) / {r['sizing_1stop']:.0%} (1 stop) "
              f"| maxDD seen: {r['max_dd_seen']:.2%} "
              f"| worst day: {r['max_daily_loss_seen']:.2%}")
        if r["days_to_target"]:
            print(f"  target reached in {r['days_to_target']}d / {r['n_trades_to_target']} trades "
                  f"| min-days met: {r['min_days_met']}")
        print(f"  longest no-trade gap: {r['longest_gap_days']}d "
              f"(inactivity limit: {r['inactivity_limit'] or 'none'})")
        if r["best_day_ratio"] is not None and r["best_day_rule"]:
            print(f"  best-day ratio: {r['best_day_ratio']:.0%} (rule: <= {r['best_day_rule']:.0%})")
        print()


if __name__ == "__main__":
    main()
