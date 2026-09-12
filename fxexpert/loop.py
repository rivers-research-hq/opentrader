#!/usr/bin/env python3
"""fxexpert.loop — the recursion driver.

Each generation: refresh the panel from the accrual store (data accrues
continuously), pick hyperparameters epsilon-greedy on past OOS IC, train
warm-started from the best promoted checkpoint, run the OOS gate, and
promote only on PASS. Promoted generations register a shadow challenger in
the ADR-0009 epoch registry (accrual ledger data/fx_expert/shadow_fills.jsonl);
live order flow stays human-gated.

Usage: python3 -m fxexpert.loop --generations 3 [--refresh] [--no-register]
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import data as fxdata
from . import gate as fxgate
from . import train as fxtrain

OUT_DIR = fxdata.OUT_DIR
STATE = OUT_DIR / "loop_state.json"
HISTORY = OUT_DIR / "history.jsonl"

HPARAMS = {
    # rule: thr = per-pair threshold + hysteresis exit; xs = daily long top-k /
    # short bottom-k. q = entry quantile (thr only). score_l2 = magnitude
    # penalty on predictions (sparser positions under thresholding).
    "A": dict(d_model=64, n_layers=2, n_heads=4, dropout=0.10, lr=1e-3, epochs=40, batch=4096, T=20, q=0.80, rule="thr", score_l2=0.0),
    "B": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr", score_l2=0.0),
    "C": dict(d_model=128, n_layers=4, n_heads=8, dropout=0.20, lr=5e-4, epochs=40, batch=4096, T=20, q=0.90, rule="thr", score_l2=0.0),
    "D": dict(d_model=64, n_layers=4, n_heads=4, dropout=0.10, lr=3e-4, epochs=40, batch=4096, T=20, q=0.90, rule="thr", score_l2=0.02),
    "E": dict(d_model=32, n_layers=1, n_heads=2, dropout=0.30, lr=5e-4, epochs=60, batch=2048, T=20, q=0.80, rule="xs", score_l2=0.0),
    "F": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=60, batch=2048, T=20, q=0.85, rule="xs", score_l2=0.02),
    "G": dict(d_model=96, n_layers=2, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=40, q=0.80, rule="thr", score_l2=0.02),
    "H": dict(d_model=192, n_layers=5, n_heads=8, dropout=0.20, lr=4e-4, epochs=40, batch=4096, T=20, q=0.90, rule="xs", score_l2=0.05),
    "I": dict(d_model=64, n_layers=2, n_heads=4, dropout=0.25, lr=5e-4, epochs=60, batch=2048, T=10, q=0.90, rule="xs", score_l2=0.05),
    "J": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.10, lr=5e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr", score_l2=0.05),
    # v0.3: data levers — longer label horizons (costs amortize; FX premia
    # live at 10-20d), H1 intraday features and FRED conditioning in panel
    "K": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.85, rule="thr", score_l2=0.02, horizon=10),
    "L": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.85, rule="thr", score_l2=0.02, horizon=20),
    "M": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.90, rule="thr", score_l2=0.05, horizon=20),
    "N": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.10, lr=5e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr", score_l2=0.05, horizon=10),
    "O": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr", score_l2=0.02, horizon=20),
    "P": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.85, rule="thr", score_l2=0.02, horizon=5),
    "Q": dict(d_model=96, n_layers=2, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=40, q=0.80, rule="thr", score_l2=0.0, horizon=10),
    "R": dict(d_model=128, n_layers=4, n_heads=8, dropout=0.20, lr=5e-4, epochs=40, batch=4096, T=40, q=0.90, rule="thr", score_l2=0.05, horizon=20),
    # v0.5: construction layer — the wide-universe evidence (IC 0.032, PF
    # flat) says signal is there but ±1 sizing pays EM costs on weak legs
    "S": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr_cont", size_cap=2.0, score_l2=0.05, horizon=10),
    "T": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.85, rule="thr_cont", size_cap=3.0, score_l2=0.05, horizon=10),
    "U": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, rule="rank", lev=1.0, rebal=5, score_l2=0.05, horizon=10),
    "V": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, rule="rank", lev=1.0, rebal=5, vol_target=True, score_l2=0.05, horizon=10),
    "W": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, q=0.80, rule="thr_cont", size_cap=2.0, vol_target=True, score_l2=0.05, horizon=10),
    "X": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, rule="rank", lev=1.0, rebal=5, cost_cap=0.0002, score_l2=0.05, horizon=10),
    "AA": dict(d_model=96, n_layers=3, n_heads=4, dropout=0.15, lr=7e-4, epochs=40, batch=4096, T=20, rule="rank", lev=1.0, rebal=5, vol_target=True, cost_cap=0.0002, score_l2=0.05, horizon=10),
}
EPS = 0.4  # explore probability for the hyperparameter bandit


def _load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"generation": 0, "best": None, "bandit": {}, "experts_registered": []}


def _save_state(s):
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(STATE)


def _pick_hp(state, rng):
    """Exploit on mean OOS IC. Re-specified 2026-09-12: the old rule exploited
    on mean net PF — the population study measured PF/Sharpe/mean-return to be
    one statistic (rho >= 0.985) that does not persist across periods
    (year-to-year Spearman +0.02, first/second half -0.23). IC is used here as
    a search heuristic, not as evidence (its own half-sample persistence is
    ~0.06). Explore with prob EPS."""
    rec = {k: v for k, v in state["bandit"].items() if v["runs"] > 0 and v.get("ic_sum") is not None}
    if not rec or rng.random() < EPS:
        name = str(rng.choice(sorted(HPARAMS)))
        return name, HPARAMS[name]
    name = max(rec, key=lambda k: rec[k]["ic_sum"] / rec[k]["runs"])
    return name, HPARAMS[name]


def _register_expert(tag, pf, ic):
    """Shadow challenger registration (ADR-0009 §3): eligibility only."""
    try:
        from strategies import epoch_registry
    except Exception as e:
        print(f"[loop] registry import failed: {e}")
        return False
    ledger = OUT_DIR / "shadow_fills.jsonl"
    if not ledger.exists():
        ledger.touch()
    expert_id = f"fx-expert-g{tag}"
    try:
        epoch_registry.register(
            expert_id, epoch=1, kind="challenger", family="fx-transformer",
            venue="oanda-practice", universe="16-pair accrual store D1",
            source=f"fxexpert loop generation {tag} (OOS PF {pf}, IC {ic})",
            accrual_ledger=str(ledger.relative_to(OUT_DIR.parent.parent)),
            promotion_bar="Eligibility 2026-09-12 (#257): OOS IC>0 with >=2/3 folds "
                          "positive, net mean return >0 after costs, dollar-neutral book, "
                          ">=2000 pair-days, beats the random control. NO backtest "
                          "promotion: PF/Sharpe/mean-return are one statistic that does "
                          "not persist across periods. Promotion = forward shadow "
                          "accrual; lane wiring requires human signoff (ADR-0009 §4).",
            notes="fxexpert recursive loop v0.1; numeric branch (prices/carry/rates/COT/events)",
            registered_by="agent")
        return True
    except SystemExit as e:
        print(f"[loop] registry: {e}")
        return False


def main(generations=1, refresh=False, seed=11, do_register=True, hp_queue=()):
    rng = np.random.default_rng(seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    queue = list(hp_queue)

    if refresh or not (OUT_DIR / "panel.npz").exists():
        print("[loop] building panel from accrual store...")
        fxdata.build()

    panel = fxtrain.load_panel()
    for gi in range(generations):
        gen = state["generation"]
        tag = f"{gen:02d}"
        t0 = time.time()
        if queue:
            name = queue.pop(0)
            hp = HPARAMS[name]
        else:
            name, hp = _pick_hp(state, rng)
        warm_tag = (state["best"] or state.get("warm") or {}).get("tag")
        # lifecycle guard: a cut/archived expert's checkpoint is quarantined —
        # it never warm-starts a new generation (its edge was judged dead)
        if warm_tag:
            try:
                from strategies.expert_lifecycle import lifecycle_of
                lc = lifecycle_of(f"fx-expert-g{warm_tag}")
                if lc is not None and lc.get("lifecycle") in ("cut", "archived"):
                    print(f"[loop] warm source g{warm_tag} is {lc['lifecycle']} "
                          f"— falling back to no warm start")
                    warm_tag = None
            except Exception:
                pass  # registry unavailable: fail open on warm only
        gseed = seed + 1009 * gen  # distinct generations must differ
        print(f"\n[loop] === generation {tag}: hp={name} seed={gseed} "
              f"warm={warm_tag or 'no'} ===")
        try:
            g = fxtrain.run_generation(tag, hp, warm_tag=warm_tag,
                                       seed=gseed, panel=panel)
            res = fxgate.evaluate(tag)
        except Exception as e:
            print(f"[loop] generation {tag} FAILED: {type(e).__name__}: {e}")
            with HISTORY.open("a") as f:
                f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                    "tag": tag, "hp": name, "error": str(e)}) + "\n")
            state["generation"] = gen + 1
            _save_state(state)
            continue

        m = res["model"]
        ic = g["aggregate"]["ic_mean"]
        # 2026-09-12: no backtest ranking decides anything. Eligibility is a
        # coherence check; registering means "accrue in shadow", and promotion
        # is the forward ledger's job (ADR-0009 §3-4).
        eligible = res["gate"]["verdict"] == "ELIGIBLE"
        registered = False
        if eligible and do_register:
            registered = _register_expert(tag, m["pf"], ic)
            if registered:
                state["experts_registered"].append(f"fx-expert-g{tag}")
        # warm-candidate: best positive-IC checkpoint so far, gate or not —
        # gives later generations something to build on (search heuristic)
        if ic is not None and ic > 0 and (state.get("warm") is None or ic > state["warm"]["ic"]):
            state["warm"] = {"tag": tag, "ic": ic}
        if eligible and ic is not None and (
                state.get("best") is None or ic > (state["best"].get("ic") or -9)):
            state["best"] = {"tag": tag, "pf": m["pf"], "ic": ic,
                             "params": g["params"],
                             "basis": "ic — warm-start heuristic, not evidence"}
        b = state["bandit"].setdefault(name, {"runs": 0, "ic_sum": 0.0, "pf_sum": 0.0})
        b.setdefault("pf_sum", 0.0)  # pre-existing state from the IC-only bandit
        b["runs"] += 1
        b["ic_sum"] += g["aggregate"]["ic_mean"] or 0.0
        b["pf_sum"] += (m["pf"] if m["pf"] is not None and m["pf"] != float("inf")
                        else 0.0)
        with HISTORY.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(), "tag": tag, "hp": name,
                "params": g["params"], "ic_mean": g["aggregate"]["ic_mean"],
                "fold_ics": [f.get("ic_oos") for f in g["folds"]],
                "folds_positive": g["aggregate"]["folds_positive"],
                "pf": m["pf"], "sharpe": m["sharpe"], "maxdd": m["maxdd"],
                "n_pairdays": m["n_pairdays"], "gate": res["gate"]["verdict"],
                "gate_reasons": res["gate"]["reasons"],
                "eligible": bool(eligible), "promoted": False,
                "registered": registered, "warm_from": g["warm_from"],
                "secs": round(time.time() - t0, 1)}) + "\n")
        state["generation"] = gen + 1
        _save_state(state)
        print(f"[loop] gen {tag}: {res['gate']['verdict']}"
              f"{' (registered for shadow accrual)' if registered else ''} "
              f"({time.time() - t0:.0f}s)")

    print("\n[loop] ==== state after run ====")
    print(json.dumps({k: state[k] for k in ("generation", "best")}, indent=1))
    for name, b in state["bandit"].items():
        if b["runs"]:
            print(f"  hp {name}: mean net PF {b.get('pf_sum', 0.0) / b['runs']:.4f}, "
                  f"mean OOS IC {b['ic_sum'] / b['runs']:.5f} over {b['runs']} run(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=1)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--hp-queue", default="",
                    help="comma-separated config names to run first (in order) "
                         "before the bandit resumes")
    a = ap.parse_args()
    main(a.generations, a.refresh, a.seed, not a.no_register,
         [h for h in a.hp_queue.split(",") if h])
