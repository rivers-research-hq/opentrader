#!/usr/bin/env python3
"""fxexp_transfer_v2 — transfer g185 into the panel-v2 architecture and
fine-tune (pre-registration addendum, 2026-09-12).

Why: fresh-init generations score PF ~1.02 on both panels, so they cannot
show whether the new information (carry for 57 pairs, rate diffs, event
counts, ToT, curve/real state) adds anything. The strong model is the
warm-started lineage. Feature counts differ (48 -> 61), so the input
projection is remapped BY FEATURE NAME; columns for features the v1 model
never saw start at zero, so fine-tuning begins from g185's function and the
new inputs can only enter through gradient updates.

Tags 221 (seed 11) and 222 (seed 23), hp U, standing protocol.

Usage: .venv/bin/python3 scripts/fxexp_transfer_v2.py [--from-tag 185]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402
from fxexpert import train as fxtrain  # noqa: E402
from fxexpert.loop import HPARAMS  # noqa: E402

OUT = REPO / "data" / "fx_expert"
HISTORY = OUT / "history.jsonl"


def transferred_states(src_tag, v1_names, v2_names):
    """g185 per-fold state dicts remapped onto the v2 feature axis."""
    pos = {n: v2_names.index(n) for n in v1_names if n in v2_names}
    missing = [n for n in v1_names if n not in pos]
    print(f"[transfer] {len(pos)}/{len(v1_names)} v1 features mapped onto the "
          f"v2 axis; unmapped: {missing}")
    states = {}
    for fi in range(3):
        p = OUT / "checkpoints" / f"g{src_tag}_f{fi}.pt"
        ck = torch.load(p, map_location="cpu", weights_only=True)
        sd = dict(ck["state_dict"])
        W = sd["inp.weight"]          # (d_model, n_v1_feat)
        W2 = torch.zeros((W.shape[0], len(v2_names)), dtype=W.dtype)
        for j, n in enumerate(v1_names):
            if n in pos:
                W2[:, pos[n]] = W[:, j]
        sd["inp.weight"] = W2
        states[fi] = sd
        # new-feature columns are exactly zero -> model starts as the g185
        # function with the extra inputs ignored
    zeros = [n for n in v2_names if n not in pos]
    print(f"[transfer] zero-initialized new columns: {zeros}")
    return states


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-tag", default="185")
    ap.add_argument("--plan", default="221:U:11,222:U:23")
    a = ap.parse_args()

    v1_names = [str(x) for x in np.load(OUT / "panel.npz")["feature_names"]]
    panel = dict(np.load(OUT / "panel_v2.npz"))
    v2_names = [str(x) for x in panel["feature_names"]]
    states = transferred_states(a.from_tag, v1_names, v2_names)

    plan = [(int(t), h, int(s)) for t, h, s in (x.split(":") for x in a.plan.split(","))]
    for tag, hpname, seed in plan:
        hp = HPARAMS[hpname]
        t0 = time.time()
        print(f"\n[transfer] === g{tag}: hp={hpname} seed={seed} "
              f"warm=transferred g{a.from_tag} ===")
        g = fxtrain.run_generation(str(tag), hp, warm_tag=None, seed=seed,
                                   panel=panel, warm_states=states)
        res = fxgate.evaluate(str(tag))
        m = res["model"]
        with HISTORY.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(), "tag": str(tag),
                "hp": hpname, "round": "panel_v2_transfer", "seed": seed,
                "warm_from": f"g{a.from_tag}+feat-transfer",
                "params": g["params"], "ic_mean": g["aggregate"]["ic_mean"],
                "fold_ics": [x.get("ic_oos") for x in g["folds"]],
                "folds_positive": g["aggregate"]["folds_positive"],
                "pf": m["pf"], "sharpe": m["sharpe"], "maxdd": m["maxdd"],
                "n_pairdays": m["n_pairdays"], "gate": res["gate"]["verdict"],
                "gate_reasons": res["gate"]["reasons"], "promoted": False,
                "registered": False, "secs": round(time.time() - t0, 1)}) + "\n")
        print(f"[transfer] g{tag}: gate {res['gate']['verdict']} PF {m['pf']} "
              f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()