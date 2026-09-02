#!/usr/bin/env python3
"""Tournament evaluation entry point for the roster strategies.

Usage:
  python -m strategies.evaluate momtrend        # R1 + OOS for one expert
  python -m strategies.evaluate --all           # both survivors

This is the canonical bridge between the arena roster and the honest scorer:
  - loads the strategy's fixed params (from roster / module defaults)
  - runs it on the US tournament data (R1) and the intl OOS data (R2)
  - prints score_equity stats and pass/fail against the round bars
"""

import pickle
import sys

import pandas as pd

US = pickle.load(open("/tmp/opentrader/swarm/swarm_data.pkl", "rb"))
INTL = pickle.load(open("/tmp/opentrader/swarm/intl_data.pkl", "rb"))

from strategies.momtrend import run as momtrend  # noqa: E402
from strategies.multiasset import backtest as multiasset  # noqa: E402
from strategies import scorer, scorer_intl  # noqa: E402

CONFIGS = {
    "momtrend": dict(mom_lb=60, k=5, rebal=20, breadth_thr=0.6,
                     breadth_win=100, force_exit=False),
    "multiasset": dict(rebal=63, vol_lb=120, mom_lb=180, topk=10,
                       eq_frac=0.4, mom_gate=False),
}
INTL_ADAPT = {"momtrend": dict(k=5), "multiasset": dict(topk=8)}


def evaluate(expert_id: str, verbose: bool = True) -> dict:
    cfg = dict(CONFIGS[expert_id])
    out = {"expert": expert_id, "config": cfg}

    if expert_id == "momtrend":
        eq_us = momtrend(US["closes"], **cfg)
        eq_intl = momtrend(INTL["closes"], universe=INTL["TRADABLES"],
                           **INTL_ADAPT[expert_id])
    elif expert_id == "multiasset":
        eq_us = multiasset(US["basket"], **cfg)
        eq_intl = multiasset(INTL["closes"][INTL["TRADABLES"]],
                             **INTL_ADAPT[expert_id])
    else:
        raise KeyError(expert_id)

    s_us = scorer.score_equity(eq_us)
    s_oo = scorer_intl.score_equity(eq_intl)
    out["R1_us"] = s_us
    out["OOS_intl"] = s_oo
    out["R1_pass"] = scorer.round1_pass(s_us) and scorer.round2_pass(s_us)
    out["OOS_pass"] = scorer_intl.oos_pass(s_oo)

    if verbose:
        print(f"[{expert_id}] R1  (US 2008-26): ann={s_us['ann']*100:.1f}% "
              f"sharpe={s_us['sharpe']:.2f} maxdd={s_us['maxdd']*100:.1f}% "
              f"calmar={s_us['calmar']:.3f} folds={s_us['folds_beat_basket']}/4 "
              f"recent={s_us['recent_2024_26_net']}")
        print(f"[{expert_id}] OOS (intl 21-26): ann={s_oo['ann']*100:.1f}% "
              f"sharpe={s_oo['sharpe']:.2f} maxdd={s_oo['maxdd']*100:.1f}% "
              f"calmar={s_oo['calmar']:.3f} beats_basket_calmar={s_oo.get('beats_basket_calmar')}")
        print(f"[{expert_id}] verdict: R1={'PASS' if out['R1_pass'] else 'fail'} "
              f"OOS={'PASS' if out['OOS_pass'] else 'fail'}")
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "--all"
    if which == "--all":
        for e in CONFIGS:
            evaluate(e)
    else:
        evaluate(which)
