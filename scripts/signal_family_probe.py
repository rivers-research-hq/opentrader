#!/usr/bin/env python3
"""Signal-family probe: does any feature family the engine already has
generalize on the 5y-wide universe under realistic fees?

RECONSTRUCTED 2026-08-22 — the original /tmp/opentrader/signal_family_probe.py
was lost to tmp cleanup. Faithful to the AGENTS.md spec (2026-08-13):

    screens every feature family the engine already has (mom/rev/rsi/brk/z
    blends, rank, vol-scaling, filters) on the 5y-wide universe (~20 min).
    Result: NO existing family generalizes under realistic fees; only new
    signal inputs (macro/sector-relative) are untested paths.

Method (HEURISTIC — the original per-family calibration is lost; the
thresholds below are sensible defaults on each feature's natural scale that
make the family trade a reasonable number of times):
  * isolate one family in the engine's score (its weight = 1, others = 0),
  * set buy/sell thresholds on that feature's own scale,
  * keep the contract's risk / sizing / exit-ladder framework,
  * run on the 5y-wide (511-registry) universe, regime ON.
A family "generalizes" if wide net_return > 0 with >= 8 trades.
The "blend" row runs the contract as-is and should match the universe
contract test's registry number (cross-check).
"""
import json
from pathlib import Path

from setup_search.data import REGIME_SYM
from setup_search.engine import run_backtest
from setup_search.wide import build_wide_aligned

LIVE_BEST = Path("/home/mrc/opentrader/data/setup_search/best.json")

# (weights, buy_thresh, sell_thresh) per family — thresholds on the feature's
# natural scale (HEURISTIC, see module docstring).
FAMILIES = [
    ("mom",   dict(w_mom=1, w_rev=0, w_rsi=0, w_brk=0, w_z=0, rank_on=0, w_rank=0), 0.05, -0.05),
    ("rev",   dict(w_mom=0, w_rev=1, w_rsi=0, w_brk=0, w_z=0, rank_on=0, w_rank=0), 0.05, -0.05),
    ("rsi",   dict(w_mom=0, w_rev=0, w_rsi=1, w_brk=0, w_z=0, rank_on=0, w_rank=0), 0.10, -0.10),
    ("brk",   dict(w_mom=0, w_rev=0, w_rsi=0, w_brk=1, w_z=0, rank_on=0, w_rank=0), -0.02, -0.10),
    ("z",     dict(w_mom=0, w_rev=0, w_rsi=0, w_brk=0, w_z=1, rank_on=0, w_rank=0), 0.50, -0.50),
    ("rank",  dict(w_mom=0, w_rev=0, w_rsi=0, w_brk=0, w_z=0, rank_on=1, w_rank=1), 0.10, -0.10),
]


def fmt(m):
    return (f"net={m['net_return']*100:+.2f}%  trades={m['n_trades']}  "
            f"sharpe={m['ann_sharpe']:.2f}  maxdd={m['max_drawdown']*100:.1f}%  "
            f"pf={m['profit_factor']:.2f}  fees=${m['total_fees']:.2f}  "
            f"fee%={m['fee_ratio']*100:.1f}%")


def main():
    best = json.loads(LIVE_BEST.read_text())
    base = dict(best["config"])

    wide = build_wide_aligned()
    n = len([s for s in wide[0] if len(wide[0][s]) > 0])
    print(f"universe: 5y-wide (511-registry) {n} syms, regime ON via {REGIME_SYM}\n")

    rows = []
    for name, w, bt, st in FAMILIES:
        cfg = dict(base)
        cfg.update(w)
        cfg["buy_thresh"] = bt
        cfg["sell_thresh"] = st
        m = run_backtest(wide, cfg)
        rows.append((name, m))
        print(f"[{name:>5}] {fmt(m)}")

    # The contract blend, as-is (all families + its own thresholds).
    m_blend = run_backtest(wide, base)
    rows.append(("blend", m_blend))
    print(f"[blend] {fmt(m_blend)}   (contract as-is; should match the "
          f"universe-contract registry number)")

    print("\nGeneralization (net>0 and >=8 trades):")
    n_pass = 0
    for name, m in rows:
        ok = m["net_return"] > 0 and m["n_trades"] >= 8
        n_pass += ok
        print(f"  {name:>5}: {'PASS' if ok else 'fail'}")
    print(f"\n{n_pass}/{len(rows)} families generalize. "
          "Documented (2026-08-13): 0 — no existing family generalizes under "
          "realistic fees; only new signal inputs (macro/sector-relative) are "
          "untested paths.")


if __name__ == "__main__":
    main()
