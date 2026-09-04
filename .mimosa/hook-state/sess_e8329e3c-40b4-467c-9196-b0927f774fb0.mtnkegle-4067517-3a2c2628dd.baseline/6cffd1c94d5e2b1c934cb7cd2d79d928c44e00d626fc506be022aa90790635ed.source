"""Export the arena's trained policy as a momentum-agent training dataset.

The arena value head (trained on arena-relative rewards + war relabels) is
the policy: TAKE where V >= theta. This distills that policy into natural
language training rows for the GPU0 QLoRA fine-tune (the heavy half of the
"hand in hand" loop). Same prompt format as
setup_search.train_momentum_agent.build_dataset.
"""

import json
import random
from pathlib import Path

import numpy as np

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at
from arena import agent as agent_mod
from arena.candidates import collect

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"


def export(n_examples=400, seed=11, agent_path=OUT / "arena_value_head.pt"):
    rows, cfg = collect("5y")
    art = agent_mod.load(agent_path)
    theta = art["theta"]

    base = clamp_config(cfg)
    data = load_ohlcv("5y")
    al = align(data, list(data.keys()))
    spy = al[0].get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean()
    feat = _features(al[0], al[1], al[2], al[3], base)
    w = base

    vals = agent_mod.predict_batch(art, [r["x"] for r in rows])
    out_rows = []
    for r, v in zip(rows, vals):
        decision = "TAKE" if v >= theta else "SKIP"
        sym = r["sym"]
        f = feat[sym]
        date = r["date"]
        s = r["score"]
        regime = "up" if r["regime_up"] else "down"
        pos = al[0][sym].index.get_loc(date)
        recent = " -> ".join(
            f"{v:,.0f}" for v in al[0][sym].iloc[max(0, pos - 5) : pos + 1]
        )
        prompt = (
            f"[Market context]\nSymbol: {sym}\nRegime (SPY vs 200d): {regime}\n"
            f"Momentum score: {s:.3f} (threshold 0.28)\nRecent closes: {recent}\n\n"
            f"Decision (TAKE or SKIP this long entry):"
        )
        out_rows.append(
            {"prompt": prompt, "decision": decision, "fwd": r["fwd"], "value": float(v)}
        )
    rng = random.Random(seed)
    takes = [r for r in out_rows if r["decision"] == "TAKE"]
    skips = [r for r in out_rows if r["decision"] == "SKIP"]
    rng.shuffle(takes)
    rng.shuffle(skips)
    half = max(1, n_examples // 2)
    keep = takes[:half] + skips[:half]
    rng.shuffle(keep)
    path = OUT / "momentum_dataset.jsonl"
    with open(path, "w") as f:
        for r in keep:
            f.write(json.dumps(r) + "\n")
    pos = sum(1 for r in keep if r["decision"] == "TAKE")
    print(
        f"[arena-export] {len(keep)} examples ({pos} TAKE / {len(keep) - pos} SKIP) "
        f"theta={theta:+.3f} -> {path}"
    )
    return path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=400)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    export(args.examples, args.seed)
