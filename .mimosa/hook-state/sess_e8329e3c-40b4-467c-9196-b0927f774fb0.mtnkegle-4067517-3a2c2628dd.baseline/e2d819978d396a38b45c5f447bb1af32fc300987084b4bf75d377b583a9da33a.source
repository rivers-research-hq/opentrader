#!/usr/bin/env python3
"""Walk-forward out-of-sample validation of the setup-search loop.

For each fold we RE-RUN the search (CPU-only: jitter + random around the
current best) on the expanding TRAIN window, then evaluate the chosen config
on the following UNSEEN TEST window. The pooled test results are the honest
out-of-sample estimate. We also run two reference configs OOS on the same
windows for comparison: the DEFAULT_CONFIG (what the live system was doing)
and the best config from the 2y in-sample search (to quantify selection bias).

Protocol: 5y daily bars; min train = 500 bars (2y); test horizon = 250 bars
(1y); 3 folds. Search budget 350 configs per fold (no GPU / scientist).
"""

import json
import random
from pathlib import Path

from setup_search.core import (
    DEFAULT_CONFIG,
    clamp_config,
    objective,
    summary_bundle,
)
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import run_backtest
from setup_search.loop import jitter, random_cfg

OUT = Path(__file__).resolve().parent.parent / "data" / "setup_search"
MIN_TRAIN = 500
TEST_HORIZON = 250
SEARCH_BUDGET = 150
SEED = 7


def _scalars(m):
    return {k: v for k, v in m.items() if k != "equity"}


def _active(metrics):
    return int(metrics.get("n_trades", 0)) >= 8


def _slice(al, i0, i1):
    closes, highs, lows, vols = al
    idx = next(iter(closes.values())).index
    lo_date, hi_date = idx[i0], idx[i1 - 1]

    def _slc(d):
        return {s: c.loc[(c.index >= lo_date) & (c.index <= hi_date)] for s, c in d.items()}

    return (_slc(closes), _slc(highs), _slc(lows), _slc(vols))


def cpu_search(al_train, budget=SEARCH_BUDGET, seed=SEED):
    rng = random.Random(seed)
    best = clamp_config(DEFAULT_CONFIG)
    m = run_backtest(al_train, best)
    met = _scalars(m)
    best_score = objective(met) if _active(met) else -999.0
    best_cfg = best
    best_met = met
    for _ in range(budget):
        cand = (
            jitter(best_cfg, rng, sigma=0.18) if rng.random() < 0.65 else random_cfg(rng)
        )
        mm = run_backtest(al_train, cand)
        mm_met = _scalars(mm)
        if _active(mm_met):
            s = objective(mm_met)
            if s > best_score:
                best_score = s
                best_cfg = cand
                best_met = mm_met
    return best_cfg, best_score, best_met


def main():
    data = load_ohlcv("5y")
    syms = [s for s in data if s != REGIME_SYM]
    al = align(data, syms)
    total = len(next(iter(al[0].values())).index)
    print(f"[wf] data: {len(syms)} symbols, {total} bars")

    try:
        insample_best = json.load(open(OUT / "best.json"))["config"]
    except Exception:
        insample_best = None

    # The validated contract as recorded in the ledger (max-score config).
    # best.json alone is NOT enough as a reference: it was clobbered once
    # (2026-08-10, agent run af1e6d83 seeded it from DEFAULT_CONFIG), which
    # silently replaced the rule floor with the losing default. Reading the
    # ledger best keeps the floor measurable even if best.json drifts.
    contract = None
    try:
        ledger_best_score, contract = -999.0, None
        for line in (OUT / "ledger.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("score", -999) > ledger_best_score:
                ledger_best_score = rec["score"]
                contract = rec["config"]
    except Exception:
        contract = None

    folds = []
    t = MIN_TRAIN
    while t + TEST_HORIZON <= total:
        folds.append((0, t, t, t + TEST_HORIZON))
        t += TEST_HORIZON

    print(f"[wf] folds: {len(folds)} (train→test): {[f'{f[1]}→{f[3]}' for f in folds]}")

    report = {"folds": [], "pooled_oos": {}, "references": {}}
    pooled = {"ret": [], "sharpe": [], "dd": [], "trades": []}

    for fi, (tr0, tr1, te0, te1) in enumerate(folds, 1):
        al_tr = _slice(al, tr0, tr1)
        al_te = _slice(al, te0, te1)
        cfg, tr_score, tr_met = cpu_search(al_tr)
        oos = _scalars(run_backtest(al_te, cfg))
        pooled["ret"].append(oos["net_return"])
        pooled["sharpe"].append(oos["ann_sharpe"])
        pooled["dd"].append(oos["max_drawdown"])
        pooled["trades"].append(oos["n_trades"])
        fold = {
            "fold": fi,
            "train_bars": (tr1 - tr0),
            "test_bars": (te1 - te0),
            "train_score": tr_score,
            "train": summary_bundle(tr_met),
            "oos": summary_bundle(oos),
            "oos_metrics": oos,
            "config": cfg,
        }
        report["folds"].append(fold)
        print(
            f"[wf] fold {fi}: train score={tr_score:.3f} | OOS: "
            f"{summary_bundle(oos)}"
        )

        for name, ref_cfg in (
            ("default", DEFAULT_CONFIG),
            ("insample_best", insample_best),
            ("contract", contract),
        ):
            if ref_cfg is None:
                continue
            r = _scalars(run_backtest(al_te, ref_cfg))
            report["references"].setdefault(name, []).append(
                {**r, "fold": fi}
            )

    n = len(pooled["ret"])
    report["pooled_oos"] = {
        "n_folds": n,
        "mean_oos_return": round(sum(pooled["ret"]) / n, 4),
        "mean_oos_sharpe": round(sum(pooled["sharpe"]) / n, 3),
        "mean_oos_maxdd": round(sum(pooled["dd"]) / n, 4),
        "total_oos_trades": sum(pooled["trades"]),
        "positive_oos_folds": sum(1 for r in pooled["ret"] if r > 0),
    }
    print("\n[wf] POOLED OOS:")
    for k, v in report["pooled_oos"].items():
        print(f"   {k}: {v}")

    # Full-archive appendix: fold windows cover only 750 of ~1255 bars, so a
    # sparse regime-gated config may show 0 trades per fold yet be alive on
    # the full span. Always report the full-archive run for each reference.
    report["full_archive"] = {}
    for name, ref_cfg in (
        ("default", DEFAULT_CONFIG),
        ("insample_best", insample_best),
        ("contract", contract),
    ):
        if ref_cfg is None:
            continue
        r = _scalars(run_backtest(al, ref_cfg))
        report["full_archive"][name] = r
        print(f"[wf] full-archive {name}: {summary_bundle(r)}")

    with open(OUT / "walkforward_report.json", "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"[wf] report -> {OUT / 'walkforward_report.json'}")


if __name__ == "__main__":
    main()
