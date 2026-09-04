#!/usr/bin/env python3
"""The transfer-proven arsenal (Tournament R1+R2 survivors).

Two deterministic strategies that beat the basket/SPY benchmarks in-sample
(R1, 2008-2026 US) AND transferred to never-seen international symbols
(R2, 2021-2026). These are the arena's starting experts — NOT wired to the
live rule gate yet (the harness runs a different universe at real-time).

  1. momtrend   : momentum-top + market-breadth entry gate. The regime tool.
     - long top-K by 60d momentum, rebalance every `rebal` bars
     - entries gated by breadth (fraction of universe above its 100d MA
       > threshold) AND/OR SPY above its long MA — no forced exits
     - OOS: Calmar 0.852, maxDD -13.0%, Sharpe 1.05
     - reproduce: momtrend(mom=60, k=5, rebal=20, breadth_thr=0.6,
                            breadth_win=100, force_exit=False)
  2. multiasset : momentum-filtered, vol-scaled multi-asset allocation.
     The drawdown tool.
     - every `rebal` bars: keep top-`topk` of the universe by `mom_lb`-day
       momentum, size `eq_frac` equal-weight + (1-eq_frac) inverse-vol
     - OOS: Calmar 1.289, maxDD -9.0%, Sharpe 1.32
     - reproduce: multiasset(rebal=63, vol_lb=120, mom_lb=180, topk=8,
                             eq_frac=0.4)

Honesty contract (same as the tournament):
  - no same-bar lookahead: all signals read at prior close, fills at current close
  - 0.35%/side fees
  - $500 start
  - scored ONLY via strategies.scorer.score_equity
"""

from strategies.momtrend import run as momtrend_run
from strategies.multiasset import backtest as multiasset_run

__all__ = ["momtrend_run", "multiasset_run", "score_equity"]

try:
    from strategies.scorer import score_equity
except ImportError:  # allow the swarm-dir scorer when running outside the repo
    from scorer import score_equity  # type: ignore
