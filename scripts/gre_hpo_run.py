#!/usr/bin/env python3
"""Run FXExpert HPO batch on the GRE using the proven direct-call pattern."""
import json, pathlib, sys, time, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from fxexpert import train
from fxexpert.recorder import record_generation
from fxexpert.gate import evaluate

OUT = pathlib.Path("data/fx_expert/hpo_batch_20260916_gre")
OUT.mkdir(parents=True, exist_ok=True)
panel = dict(np.load("data/fx_expert/panel.npz", allow_pickle=False))

configs = {
    "hpo_gre_a": dict(d_model=128, n_layers=4, n_heads=8, dropout=0.20, lr=5e-4,
                      epochs=40, batch=1024, T=40, rule="rank", lev=1.0, rebal=5,
                      score_l2=0.05, horizon=10, rank_lambda=0.05, cost_lambda=0.5),
    "hpo_gre_b": dict(d_model=192, n_layers=5, n_heads=8, dropout=0.20, lr=4e-4,
                      epochs=40, batch=1024, T=20, rule="rank", lev=1.0, rebal=5,
                      score_l2=0.05, horizon=10, rank_lambda=0.05, cost_lambda=0.5),
    "hpo_gre_c": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.10, lr=5e-4,
                      epochs=60, batch=2048, T=20, rule="rank", lev=1.0, rebal=5,
                      score_l2=0.02, horizon=20, rank_lambda=0.10, cost_lambda=0.5),
    "hpo_gre_d": dict(d_model=128, n_layers=4, n_heads=8, dropout=0.15, lr=3e-4,
                      epochs=40, batch=1024, T=40, rule="rank", lev=1.0, rebal=5,
                      vol_target=True, score_l2=0.05, horizon=20, rank_lambda=0.05, cost_lambda=0.5),
    "hpo_gre_u": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4,
                      epochs=40, batch=4096, T=20, rule="rank", lev=1.0, rebal=5,
                      score_l2=0.05, horizon=10),  # g185 baseline
}

summary = []
for tag, hp in configs.items():
    t0 = time.time()
    g = train.run_generation(tag, hp, out_dir=OUT, seed=11, panel=panel)
    secs = round(time.time() - t0, 1)
    agg = g.get("aggregate", {})
    gate_result = evaluate(tag, out_dir=OUT, write=False)
    history_row = record_generation(tag, out_dir=OUT, gate_result=gate_result)
    row = {"tag": tag, "seconds": secs, "params": g.get("params"),
           "aggregate": agg, "gate": gate_result.get("gate"),
           "history_row": history_row,
           "folds": [{"fold": f.get("fold"), "ic_oos": f.get("ic_oos"),
                      "huber_loss": f.get("huber_loss")} for f in g.get("folds", [])]}
    summary.append(row)
    print(f"[{tag}] IC {agg.get('ic_mean')} folds {agg.get('folds_positive')}/{agg.get('n_folds')} "
          f"params {g.get('params')} {secs}s")

(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))