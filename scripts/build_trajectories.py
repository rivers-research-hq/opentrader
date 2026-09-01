#!/usr/bin/env python3
"""build_trajectories — pilot dataset for the value head (RLHF spec §3, §4).

Generates the labeled fade-event dataset (strategies/fx_traj.fade_events)
from the gym's cached candle history and writes
data/agent_gym/trajectories.jsonl. SOURCE LABEL (goes in every row and the
summary): historical gym candles, isolated counterfactual outcomes, spread-
adjusted — NOT live/shadow ledgers, so this is benchmark-internal pilot data;
the production training gates V1–V4 (live ledger volumes) are unchanged.

Also prints the walkforward sanity table at the frozen episode boundaries:
for each episode, the training set = events with exit BEFORE the episode
start (strict no-leakage), with its size, win rate, and in-sample AUC.
"""

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from strategies.fx_traj import fade_events, FEATURES  # noqa: E402
from strategies import valuehead as vh  # noqa: E402

CANDLES = PROJECT / "data" / "signal_gym" / "candles.json"
EXOG = PROJECT / "data" / "exog_cache.json"
OUT = PROJECT / "data" / "agent_gym" / "trajectories.jsonl"
EPISODES = [(85, 145), (235, 295), (385, 445)]


def main():
    series = {s: {int(ts): tuple(px) for ts, px in d.items()}
              for s, d in json.load(open(CANDLES)).items()}
    alldates = sorted({ts for ss in series.values() for ts in ss})
    bars = {s: [series[s].get(ts) for ts in alldates] for s in series}
    exog = json.load(open(EXOG)) if EXOG.exists() else {}

    events = list(fade_events(bars, alldates, exog))
    for e in events:
        e["source"] = "gym-candles-historical/isolated-counterfactual/spread-adjusted"
    OUT.write_text("\n".join(json.dumps(e, default=str) for e in events) + "\n")

    rs = [e["r_multiple"] for e in events]
    wins = [e["win"] for e in events]
    print(f"fade events: {len(events)}  win rate {sum(wins) / len(wins):.1%}  "
          f"mean R {sum(rs) / len(rs):+.3f}  dataset: {OUT}")

    print("\nwalkforward sanity at frozen episode boundaries "
          "(train = events EXITING before episode start; strict no-leakage):")
    for k, (lo, _hi) in enumerate(EPISODES):
        cutoff = alldates[lo]
        train = [e for e in events if e["exit_ts"] < cutoff]
        in_ep = [e for e in events if lo <= e["bar"] < _hi]
        if not train:
            print(f"  ep{k}: NO training events — head untrained")
            continue
        model = vh.train([e["features"] for e in train],
                         [e["win"] for e in train], FEATURES)
        a_in = vh.auc(model, [e["features"] for e in train], [e["win"] for e in train])
        print(f"  ep{k}: train n={len(train)} winrate {sum(e['win'] for e in train) / len(train):.1%} "
              f"in-sample AUC {a_in} | events inside episode: {len(in_ep)}")


if __name__ == "__main__":
    main()
