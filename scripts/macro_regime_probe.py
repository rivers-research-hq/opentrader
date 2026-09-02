#!/usr/bin/env python3
"""Macro-regime probe: do FRED entry gates let a signal generalize?

RECONSTRUCTED 2026-08-22 — the original /tmp/opentrader/macro_regime_probe.py
was lost to tmp cleanup. Faithful to the AGENTS.md spec (2026-08-13):

    FRED entry gates (run_backtest(..., macro_gate=...), default off) across
    the promising families. ONE lead: incumbent + ff_falling (long only while
    Fed Funds < 60d-ago level) flips 5y-wide from −41.8% → +6.2% (PF 1.07,
    124 tr). OOS walkforward DISPROVES it as an edge (1/4 folds positive) —
    it is a loss-reducer, not a validatable edge. Do NOT repeat as a claim of
    edge. Verify with /tmp/opentrader/macro_lead_walkforward.py.

macro_gate contract (engine.run_backtest): a pandas Series (DatetimeIndex ->
bool); an entry is only allowed on dates where it is True. Default None = no
macro conditioning. The gate is built on the FRED series' own (daily) index;
the engine's macro_gate.get(date) reconciles tz and defaults missing dates to
False (no entry).

DO NOT RE-RUN as validation: the ff_falling lead is already OOS-disproved.
This script exists so the probe is reproducible, not to re-claim the edge.
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
import json
import pickle
from pathlib import Path

import pandas as pd

from setup_search.data import REGIME_SYM
from setup_search.engine import run_backtest
from setup_search.wide import OUT, build_wide_aligned

LIVE_BEST = Path("/home/mrc/opentrader/data/setup_search/best.json")
MACRO_CACHE = OUT / "macro_series.pkl"


def load_macro() -> dict:
    ck = sec_pickle_load(open(MACRO_CACHE, "rb"))
    return ck["data"]  # {"fred": {FF, T10, CPI}, "vix": Series}


def build_gates(macro: dict) -> dict:
    """Bool entry-gates on each FRED series' own daily index."""
    ff = macro["fred"]["FF"]
    t10 = macro["fred"]["T10"]
    return {
        # long only while Fed Funds is below its level 60 rows (~days) ago
        "ff_falling": (ff < ff.shift(60)).fillna(False),
        # long only while the 10y is below its level 60 rows ago
        "t10_falling": (t10 < t10.shift(60)).fillna(False),
        # the opposite regime (Fed Funds rising) — control
        "ff_rising": (ff > ff.shift(60)).fillna(False),
    }


def fmt(m):
    return (f"net={m['net_return']*100:+.2f}%  trades={m['n_trades']}  "
            f"pf={m['profit_factor']:.2f}  fees=${m['total_fees']:.2f}  "
            f"fee%={m['fee_ratio']*100:.1f}%")


def main():
    best = json.loads(LIVE_BEST.read_text())
    cfg = dict(best["config"])

    wide = build_wide_aligned()
    n = len([s for s in wide[0] if len(wide[0][s]) > 0])
    print(f"universe: 5y-wide (511-registry) {n} syms, regime ON via {REGIME_SYM}")

    gates = build_gates(load_macro())
    for name, g in gates.items():
        print(f"gate {name}: {int(g.sum())}/{len(g)} bars open ({g.mean()*100:.0f}%)")

    # incumbent (contract) with and without each gate
    print("\nincumbent (contract) — baseline vs gated:")
    base = run_backtest(wide, cfg)
    print(f"  [no gate]   {fmt(base)}")
    for name, g in gates.items():
        m = run_backtest(wide, cfg, macro_gate=g)
        print(f"  [{name}] {fmt(m)}")

    print("\nDocumented (2026-08-13): incumbent + ff_falling flips 5y-wide "
          "−41.8% → +6.2% (PF 1.07, 124 tr). OOS walkforward DISPROVES it as "
          "an edge (1/4 folds positive) — a loss-reducer, not a validatable "
          "edge. Verify with /tmp/opentrader/macro_lead_walkforward.py.")


if __name__ == "__main__":
    main()
