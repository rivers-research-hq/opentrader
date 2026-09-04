#!/usr/bin/env python3
"""Evidence-gated research feature A/B (wayfinder #30).

For each candidate feature (a gate on the setup_search engine), runs the
baseline config vs baseline+feature on the SAME walk-forward OOS test windows
and applies the agreed promotion bar:

    promote iff  mean OOS net-return delta >= +1%/yr
            AND  mean OOS Sharpe delta > 0
            AND  positive net-return delta in >= 2/3 folds

Candidates come from the ~15 salvageable features in the legacy backlog,
encoded as engine gates (all off by default). Results land in
data/research_gate/results.json.
"""

import json
from pathlib import Path

from setup_search.core import clamp_config, summary_bundle
from setup_search.data import REGIME_SYM, load_ohlcv, align, slice_aligned
from setup_search.engine import run_backtest

OUT = Path(__file__).resolve().parent.parent / "data" / "research_gate"
PROJECT = Path(__file__).resolve().parent.parent
FOLDS = [(500, 750), (750, 1000), (1000, 1250)]  # OOS test slices (bars, ~1yr each)

FEATURES = [
    {"name": "ma_reject_30d_20pct", "desc": "reject if price > 20% above 30d MA",
     "gate": {"ma_reject_n": 30, "ma_reject_pct": 0.20}},
    {"name": "ma_reject_60d_10pct", "desc": "reject if price > 10% above 60d MA",
     "gate": {"ma_reject_n": 60, "ma_reject_pct": 0.10}},
    {"name": "vol_spike_20d_2.5x", "desc": "reject if volume > 2.5x 20d avg",
     "gate": {"vol_spike_n": 20, "vol_spike_mult": 2.5}},
    {"name": "vol_spike_10d_3x", "desc": "reject if volume > 3x 10d avg",
     "gate": {"vol_spike_n": 10, "vol_spike_mult": 3.0}},
    {"name": "vol_reduce_20d_3pct_half", "desc": "halve size when 20d vol > 3%",
     "gate": {"vol_reduce_n": 20, "vol_reduce_thr": 0.03, "vol_reduce_frac": 0.5}},
    {"name": "vol_reduce_30d_2pct_3q", "desc": "0.75 size when 30d vol > 2%",
     "gate": {"vol_reduce_n": 30, "vol_reduce_thr": 0.02, "vol_reduce_frac": 0.75}},
    {"name": "impact_cap_15pct", "desc": "cap order notional at 15% equity",
     "gate": {"impact_cap_pct": 0.15}},
    {"name": "impact_cap_25pct", "desc": "cap order notional at 25% equity",
     "gate": {"impact_cap_pct": 0.25}},
]


def _scalars(m):
    return {k: v for k, v in m.items() if k != "equity"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, [s for s in data if s != REGIME_SYM])

    base_folds = []
    for a, b in FOLDS:
        al_te = slice_aligned(al, a, b)
        base_folds.append(_scalars(run_backtest(al_te, base)))
    base_sum = " | ".join(
        f"f{i+1} {summary_bundle(b)}" for i, b in enumerate(base_folds)
    )
    print(f"[gate] baseline OOS: {base_sum}")

    results = []
    for f in FEATURES:
        gate = clamp_config({**base, **f["gate"]})
        folds = []
        for i, (a, b) in enumerate(FOLDS):
            al_te = slice_aligned(al, a, b)
            m = _scalars(run_backtest(al_te, gate))
            folds.append({
                "fold": i + 1,
                "net": round(m["net_return"], 4),
                "sharpe": round(m["ann_sharpe"], 3),
                "delta_net": round(m["net_return"] - base_folds[i]["net_return"], 4),
                "delta_sharpe": round(m["ann_sharpe"] - base_folds[i]["ann_sharpe"], 3),
                "trades": m["n_trades"],
            })
        mean_dnet = sum(x["delta_net"] for x in folds) / len(folds)
        mean_dsh = sum(x["delta_sharpe"] for x in folds) / len(folds)
        pos_folds = sum(1 for x in folds if x["delta_net"] > 0)
        promote = mean_dnet >= 0.01 and mean_dsh > 0 and pos_folds >= 2
        results.append({
            **{"name": f["name"], "desc": f["desc"]},
            "folds": folds,
            "mean_delta_net": round(mean_dnet, 4),
            "mean_delta_sharpe": round(mean_dsh, 3),
            "positive_folds": pos_folds,
            "promote": promote,
        })
        print(
            f"[gate] {f['name']:24s} Δnet={mean_dnet:+.2%} Δsharpe={mean_dsh:+.2f} "
            f"pos={pos_folds}/3 {'PROMOTE' if promote else 'reject'}"
        )

    n_promoted = sum(1 for r in results if r["promote"])
    summary = {
        "baseline_oos": base_sum,
        "n_features": len(results),
        "n_promoted": n_promoted,
        "promoted": [r["name"] for r in results if r["promote"]],
        "results": results,
    }
    (OUT / "results.json").write_text(json.dumps(summary, indent=1))
    print(f"\n[gate] {n_promoted}/{len(results)} promoted -> {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
