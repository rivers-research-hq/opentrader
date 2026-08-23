#!/usr/bin/env python3
"""Universe generalization test for the rule-floor contract.

RECONSTRUCTED 2026-08-22 — the original /tmp/opentrader/universe_contract_test.py
was lost to tmp cleanup. Faithful to the AGENTS.md spec (2026-08-13):

    same contract on the 511-registry and the 7.3k-symbol fullcross archive
    (~25 min). The contract does NOT generalize beyond the 17 search names
    (−37.8% registry, −40.4% wide); treat any "edge" claim as universe-bound
    until proven otherwise.

"Contract" = the best.json config (risk 0.15, regime_filter 1/96, buy_thresh
0.28, 40 keys) — the documented rule floor. We run the repo's own run_backtest
on two OUT-OF-SEARCH universes (both ~5y / 1300 bars, regime ON via SPY):
  1. 511-registry   = harness registry ∩ fullcross archive (build_wide_aligned)
  2. 7.3k fullcross = every symbol in fullcross.pkl

No fabricated numbers — every metric is computed live from the archives.
"""
import json
import pickle
from pathlib import Path

import pandas as pd

from setup_search.data import REGIME_SYM, align
from setup_search.engine import run_backtest
from setup_search.wide import ARCHIVE, WIDE_PERIOD_BARS, build_wide_aligned

# Canonical contract = the live best.json (re-tracked + refreshed 2026-08-22).
LIVE_BEST = Path("/home/mrc/opentrader/data/setup_search/best.json")


def fmt(m):
    return (f"net={m['net_return']*100:+.2f}%  trades={m['n_trades']}  "
            f"sharpe={m['ann_sharpe']:.3f}  maxdd={m['max_drawdown']*100:.2f}%  "
            f"pf={m['profit_factor']:.2f}  win={m['win_rate']*100:.0f}%  "
            f"fees=${m['total_fees']:.2f}  fee%={m['fee_ratio']*100:.1f}%")


def _frame_from_archive(v, period_bars):
    dates = pd.to_datetime(v["d"], unit="s")
    df = pd.DataFrame(
        {
            "close": v["c"][-period_bars:],
            "high": v["h"][-period_bars:],
            "low": v["l"][-period_bars:],
            "volume": v["v"][-period_bars:],
        },
        index=dates[-period_bars:],
    )
    return df[~df.index.duplicated(keep="last")]


def load_fullcross_aligned(period_bars=WIDE_PERIOD_BARS):
    """Aligned (closes, highs, lows, vols) over the ENTIRE fullcross archive
    (all ~7.3k symbols), not just the registry intersection."""
    with open(ARCHIVE, "rb") as f:
        raw = pickle.load(f)
    data = {}
    for sym, v in raw.items():
        if v is None or len(v["c"]) < period_bars:
            continue
        data[sym] = _frame_from_archive(v, period_bars)
    del raw
    if REGIME_SYM not in data:
        raise SystemExit(f"[fullcross] {REGIME_SYM} missing from archive — cannot run regime ON")
    syms = [s for s in data if s != REGIME_SYM] + [REGIME_SYM]
    return align(data, syms)


def main():
    best = json.loads(LIVE_BEST.read_text())
    cfg = best["config"]
    print(f"contract: best.json iter={best.get('iter')}  risk={cfg['risk_pct']}  "
          f"regime={cfg['regime_filter']}/{cfg['regime_window']}  buy={cfg['buy_thresh']}  "
          f"rank_on={cfg['rank_on']}")
    print(f"window: {WIDE_PERIOD_BARS} bars (~5y), regime ON via {REGIME_SYM}\n")

    # 1) 511-registry (registry ∩ archive) — cached
    reg = build_wide_aligned()
    n_reg = len([s for s in reg[0] if len(reg[0][s]) > 0])
    m_reg = run_backtest(reg, cfg)
    print(f"[registry  {n_reg:>4} syms] {fmt(m_reg)}")

    # 2) full 7.3k fullcross
    fc = load_fullcross_aligned()
    n_fc = len([s for s in fc[0] if len(fc[0][s]) > 0])
    m_fc = run_backtest(fc, cfg)
    print(f"[fullcross {n_fc:>4} syms] {fmt(m_fc)}")

    print("\nDocumented (2026-08-13): registry −37.8%, wide −40.4% — "
          "the contract does NOT generalize beyond the 17 search names.")


if __name__ == "__main__":
    main()
