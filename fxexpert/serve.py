#!/usr/bin/env python3
"""fxexpert.serve — emit today's shadow signals from the best promoted expert.

Loads the loop's best checkpoint, rebuilds the panel (venue-store truth),
scores every pair on the latest date, and writes data/fx_expert/signals.json.
SHADOW ONLY — nothing here places orders; a lane cron consuming this file is
a human-gated step (ADR-0009 §4), and the OANDA venue stays authoritative.

Usage: python3 -m fxexpert.serve [--refresh]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from . import data as fxdata
from . import train as fxtrain

OUT_DIR = fxdata.OUT_DIR


def main(refresh=False):
    state = json.loads((OUT_DIR / "loop_state.json").read_text())
    if not state.get("best"):
        raise SystemExit("[serve] no promoted expert yet — run fxexpert.loop first")
    tag = state["best"]["tag"]
    ckpt = torch.load(OUT_DIR / "checkpoints" / f"g{tag}.pt", weights_only=True)

    if refresh or not (OUT_DIR / "panel.npz").exists():
        fxdata.build()
    panel = fxtrain.load_panel()
    cfg = ckpt["config"]
    model = fxtrain.FXExpert(cfg["n_feat"], cfg["d_model"], cfg["n_layers"],
                             cfg["n_heads"], cfg["dropout"], cfg["T"]).to(fxtrain.DEVICE)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    day = panel["date"]  # day numbers since epoch
    last = day.max()
    rows_v, win_v = fxtrain._windows(panel["pair_idx"], len(day))
    sel = day[rows_v] == last
    rows = rows_v[sel]
    X = panel["features"][win_v[sel]]
    Xs = np.clip((X - ckpt["feat_mean"].numpy()) / ckpt["feat_std"].numpy(), -8, 8)
    Xs = np.nan_to_num(Xs).astype(np.float32)
    with torch.no_grad():
        score = model(torch.from_numpy(Xs).to(fxtrain.DEVICE)).cpu().numpy()

    pairs = {m["idx"]: m["pair"] for m in
             json.loads((OUT_DIR / "panel_meta.json").read_text())["pairs"]}
    rule = cfg.get("rule", "thr")
    if rule == "rank":
        # the promoted book is rank-weighted: emit today's portfolio weights
        # (rebal/vol/cost knobs come from the checkpoint config)
        from . import gate as fxgate
        w = fxgate._positions_rank(
            np.full(len(rows), int(last)), panel["pair_idx"][rows], score,
            vol20=panel.get("vol20", np.array([]))[rows] if panel.get("vol20") is not None and len(panel.get("vol20")) else None,
            cost=panel["cost"][rows], lev=cfg.get("lev", 1.0),
            vol_target=bool(cfg.get("vol_target")),
            cost_cap=cfg.get("cost_cap"), rebal=cfg.get("rebal", 5))
        sig = [{"pair": pairs[int(panel["pair_idx"][i])],
                "score": round(float(s), 4), "weight": round(float(ww), 4),
                "side": "long" if ww > 0 else ("short" if ww < 0 else "flat")}
               for i, s, ww in zip(rows, score, w)]
    else:
        sig = [{"pair": pairs[int(panel["pair_idx"][i])],
                "score": round(float(s), 4), "weight": None,
                "side": "long" if s >= ckpt["q_long"] else
                        ("short" if s <= ckpt["q_short"] else "flat")}
               for i, s in zip(rows, score)]
    out = {"generated": datetime.now(timezone.utc).isoformat(),
           "expert": f"fx-expert-g{tag}", "date": str(np.datetime64(int(last), "D")),
           "q_long": ckpt["q_long"], "q_short": ckpt["q_short"],
           "note": "shadow signals only; venue (OANDA) is authoritative; live is human-gated",
           "signals": sig}
    path = OUT_DIR / "signals.json"
    path.write_text(json.dumps(out, indent=1))
    print(f"[serve] expert fx-expert-g{tag}: {len(sig)} pairs scored for {out['date']} -> {path}")
    for s in sig:
        if s["side"] != "flat":
            print(f"  {s['pair']:10s} {s['side']:5s} score {s['score']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    main(a.refresh)
