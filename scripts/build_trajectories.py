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
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from strategies.fx_traj import fade_events, FEATURES  # noqa: E402
from strategies import valuehead as vh  # noqa: E402

CANDLES = PROJECT / "data" / "signal_gym" / "candles.json"       # frozen benchmark window
CANDLES_DEEP = PROJECT / "data" / "signal_gym" / "candles_deep.json"  # training history
EXOG = PROJECT / "data" / "exog_cache.json"
OUT = PROJECT / "data" / "agent_gym" / "trajectories.jsonl"
EPISODES = [(85, 145), (235, 295), (385, 445)]  # bar indices INTO THE SHORT CACHE


def main():
    argv = sys.argv
    deep_path = Path(argv[argv.index("--candles") + 1]) if "--candles" in argv else CANDLES_DEEP

    # episode cutoffs are the FROZEN protocol windows' start timestamps,
    # resolved from the short cache regardless of which cache trains from
    short = json.load(open(CANDLES))
    short_dates = sorted({int(ts) for s in short.values() for ts in s})
    cutoffs = [short_dates[lo] for lo, _hi in EPISODES]

    series = {s: {int(ts): tuple(px) for ts, px in d.items()}
              for s, d in json.load(open(deep_path)).items()}
    alldates = sorted({ts for ss in series.values() for ts in ss})
    bars = {s: [series[s].get(ts) for ts in alldates] for s in series}
    exog = json.load(open(EXOG)) if EXOG.exists() else {}

    events = list(fade_events(bars, alldates, exog))
    for e in events:
        e["source"] = "oanda-d1-deep/isolated-counterfactual/spread-adjusted"
    OUT.write_text("\n".join(json.dumps(e, default=str) for e in events) + "\n")

    rs = [e["r_multiple"] for e in events]
    wins = [e["win"] for e in events]
    span0 = datetime.fromtimestamp(min(e["ts"] for e in events), tz=timezone.utc).date()
    span1 = datetime.fromtimestamp(max(e["ts"] for e in events), tz=timezone.utc).date()
    print(f"fade events: {len(events)}  win rate {sum(wins) / len(wins):.1%}  "
          f"mean R {sum(rs) / len(rs):+.3f}  span {span0} -> {span1}")
    print(f"dataset: {OUT}")

    print("\nwalkforward sanity at frozen episode boundaries "
          "(train = events EXITING before episode start; strict no-leakage):")
    for k, cut in enumerate(cutoffs):
        train = [e for e in events if e["exit_ts"] < cut]
        d = datetime.fromtimestamp(cut, tz=timezone.utc).date()
        if not train:
            print(f"  ep{k} (start {d}): NO training events — head untrained")
            continue
        model = vh.train([e["features"] for e in train],
                         [e["win"] for e in train], FEATURES)
        a_in = vh.auc(model, [e["features"] for e in train], [e["win"] for e in train])
        print(f"  ep{k} (start {d}): train n={len(train)} "
              f"winrate {sum(e['win'] for e in train) / len(train):.1%} in-sample AUC {a_in}")


if __name__ == "__main__":
    main()
