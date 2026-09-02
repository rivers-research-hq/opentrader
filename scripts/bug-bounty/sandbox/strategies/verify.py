#!/usr/bin/env python3
"""Verify the repo strategies/ modules reproduce the tournament results.

R1 (US registry 2008-2026): momtrend ann 23.2% / Calmar 0.469 / 4/4 folds;
  multiasset ann 7.2% / Calmar 0.39 / 4/4 folds.
OOS (intl 2021-2026): momtrend Calmar 0.852; multiasset Calmar 1.289.
"""

import pickle
import sys

import pandas as pd

sys.path.insert(0, "/home/mrc/opentrader")
from strategies.momtrend import run as momtrend
from strategies.multiasset import backtest as multiasset

US = pickle.load(open("/tmp/opentrader/swarm/swarm_data.pkl", "rb"))
INTL = pickle.load(open("/tmp/opentrader/swarm/intl_data.pkl", "rb"))


def fmt(s):
    if "error" in s:
        return f"ERROR {s['error']}"
    return (f"ann={s['ann']*100:.1f}% sharpe={s['sharpe']:.2f} "
            f"maxdd={s['maxdd']*100:.1f}% calmar={s['calmar']:.3f} "
            f"folds={s['folds_beat_basket']}/4 recent={s['recent_2024_26_net']}")


def main():
    print("=== R1 (US registry, 2008-2026) — expect momtrend calmar ~0.469, multiasset ~0.39 ===")
    import strategies.scorer as sc
    eq_mt = momtrend(US["closes"], mom_lb=60, k=5, rebal=20,
                     breadth_thr=0.6, breadth_win=100, force_exit=False)
    s_mt = sc.score_equity(eq_mt)
    print("  momtrend  :", fmt(s_mt))

    eq_ma = multiasset(US["basket"], rebal=63, vol_lb=120, mom_lb=180,
                       topk=10, eq_frac=0.4, mom_gate=False)
    s_ma = sc.score_equity(eq_ma)
    print("  multiasset:", fmt(s_ma))

    print("\n=== OOS (international, 2021-2026) — expect momtrend calmar ~0.85, multiasset ~1.29 ===")
    import strategies.scorer_intl as si
    eq_mt2 = momtrend(INTL["closes"], universe=INTL["TRADABLES"], mom_lb=60, k=5,
                      rebal=20, breadth_thr=0.6, breadth_win=100, force_exit=False)
    s_mt2 = si.score_equity(eq_mt2)
    print("  momtrend  :", "ann=%.1f%% sharpe=%.2f maxdd=%.1f%% calmar=%.3f beats_basket_calmar=%s" % (
        s_mt2["ann"]*100, s_mt2["sharpe"], s_mt2["maxdd"]*100, s_mt2["calmar"], s_mt2.get("beats_basket_calmar")))

    eq_ma2 = multiasset(INTL["closes"][INTL["TRADABLES"]], rebal=63, vol_lb=120,
                        mom_lb=180, topk=8, eq_frac=0.4, mom_gate=False)
    s_ma2 = si.score_equity(eq_ma2)
    print("  multiasset:", "ann=%.1f%% sharpe=%.2f maxdd=%.1f%% calmar=%.3f beats_basket_calmar=%s" % (
        s_ma2["ann"]*100, s_ma2["sharpe"], s_ma2["maxdd"]*100, s_ma2["calmar"], s_ma2.get("beats_basket_calmar")))


if __name__ == "__main__":
    main()
