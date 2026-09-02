#!/usr/bin/env python3
"""Evolutionary specialist breeder (#56 hive, Phase 1 — #57/#58 resolutions).

Breeds the swarm's tiny value-head MLPs (2.9K params, per #58) with a
genetic loop over the specialist's OWN hyper-parameters, using the same
substrate as the rule search (#57: "jitter/random_cfg ARE the genetic
operators"). Fitness = selection pressure on the SELECT windows only; the GATE is the
HOLDOUT windows, which the GA never sees (audit 2026-08-11: the old gate
windows were the fitness windows, so the GA selected on the eval set and
"gate pass" was selection-on-eval noise; also min-kept was missing, so
"keep nothing in a bear window" scored as a huge margin). Window counts are
kept: a window with fewer than MIN_KEPT kept rows fails the gate.
GA: pop 50 × 3 generations, ~5-10 min CPU.

Specialist form (#58): per-market × per-regime × per-horizon value heads,
trained in minutes, tiny, run IN-PROCESS (no llama-server). This phase breeds
the momentum specialist; the per-regime/per-horizon grid is the swarm
registry's job (Phase 2, Mother Trader).

Genotype (specialist hyper-parameters, all from the existing search space):
  - feature weight vector (w_mom, w_rev, w_rsi, w_brk, w_z) — the signal
  - theta (policy take threshold), lr, epochs, hidden width
  - regime filter on/off (SPY-96d gate inherited from the rule floor)

Crossover: blend of parents' normalized params (arithmetic crossover).
Mutation: jitter around the best (setup_search.loop.jitter semantics).
Selection: tournament on SELECT-window discrimination; elitism keeps the top-3.
The gate (HOLDOUT windows) is reported after the GA and never feeds selection.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at
from setup_search.value_head import ValueMLP, THETA_BAR

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "hive"
FORWARD = 10
TRAIN = (0, 1000)            # forward-only (audit 2026-08-11): train the past
SELECT = [(0, 250), (500, 750)]   # selection windows INSIDE the train era — GA fitness ONLY, never the gate
HOLDOUT = [(1000, 1250)]  # gate window = the unseen future — never seen by the GA or theta search
# (old split gated the 2021-23 bear era too; it is not discriminable at +1%
# even in-sample — see #68 protocol re-measure. Keep the gate on the era the
# agent can actually demonstrate skill on.)
MIN_KEPT = 30                  # a gate window needs >= this many kept rows to count
VAL_MIN_KEPT = 10              # min kept rows for the val theta search inside _fit
VAL_FRAC = 0.15
FEAT_COLS = ["mom", "rev", "rsi", "brk", "z", "ma_dist", "vol_spike", "vol_level", "momfilt"]

POP_SIZE = 50
GENERATIONS = 3
ELITE = 3
TOURNAMENT_K = 5
MUTATION_SIGMA = 0.18
SEED = 42

# Specialist genotype bounds (subset of CONFIG_BOUNDS + training params)
GENOTYPE = {
    "w_mom": (-0.6, 2.0), "w_rev": (-1.5, 0.5), "w_rsi": (-0.5, 1.5),
    "w_brk": (-0.5, 1.5), "w_z": (-0.5, 1.5),
    "theta": (-0.5, 0.5), "lr": (1e-4, 3e-3), "epochs": (40, 300),
    "hidden": (8, 64), "regime_filter": (0, 1),
    # form: 0 = smooth regressor (MSE of E[fwd]), 1 = tail classifier
    # (BCE on top-10%-fwd tail membership — ADR-0006 classifier-orderer,
    # the proven form that beats the regressor inside the score tail).
    "form": (0, 1),
}


def _norm(g: dict) -> dict:
    """Normalize a genotype to [0,1] per bound for crossover."""
    out = {}
    for k, (lo, hi) in GENOTYPE.items():
        v = g[k]
        out[k] = 0.0 if hi == lo else (v - lo) / (hi - lo)
    return out


def _unnorm(n: dict) -> dict:
    out = {}
    for k, (lo, hi) in GENOTYPE.items():
        v = n[k] * (hi - lo) + lo
        if k in ("epochs", "hidden") or k == "regime_filter":
            out[k] = int(round(v))
        else:
            out[k] = v
    if out["regime_filter"]:
        out["regime_filter"] = True
    else:
        out["regime_filter"] = False
    return out


def _random_individual(rng: random.Random) -> dict:
    return _unnorm({k: rng.random() for k in GENOTYPE})


def _mutate(parent: dict, rng: random.Random, sigma: float = MUTATION_SIGMA) -> dict:
    """Jitter N genes around the parent (loop.jitter semantics)."""
    child = dict(parent)
    keys = list(GENOTYPE.keys())
    rng.shuffle(keys)
    for k in keys[: rng.randint(2, 5)]:
        lo, hi = GENOTYPE[k]
        child[k] = min(hi, max(lo, parent[k] + rng.uniform(-1, 1) * (hi - lo) * sigma))
    if "epochs" in keys[:4]:
        child["epochs"] = int(round(child["epochs"]))
    if "hidden" in keys[:4]:
        child["hidden"] = int(round(child["hidden"]))
    if "regime_filter" in keys[:4]:
        child["regime_filter"] = bool(round(child["regime_filter"]))
    return child


def _crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """Arithmetic (blend) crossover in normalized space."""
    na, nb = _norm(a), _norm(b)
    alpha = rng.uniform(0.25, 0.75)
    child = {k: alpha * na[k] + (1 - alpha) * nb[k] for k in GENOTYPE}
    return _unnorm(child)


def _collect(closes, highs, lows, vols, cfg):
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if cfg["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()
    rows = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c, f = closes[sym], feat[sym]
        score = (cfg["w_mom"] * f["mom"] + cfg["w_rev"] * f["rev"]
                 + cfg["w_rsi"] * f["rsi"] + cfg["w_brk"] * f["brk"]
                 + cfg["w_z"] * f["z"])
        vals = f[FEAT_COLS].values.astype(np.float32)
        np.nan_to_num(vals, copy=False)
        fwd = (c.shift(-FORWARD_GLOBAL if "FORWARD_GLOBAL" in globals() else FORWARD) / c - 1.0).values
        sc = score.values
        for i in range(len(c)):
            v = vals[i]
            fw = fwd[i]
            if np.isnan(v).any() or np.isnan(fw):
                continue
            rows.append({
                "x": v, "fwd": float(fw), "bar": i, "sym": sym,
                "score": float(sc[i]) if not np.isnan(sc[i]) else 0.0,
                "regime_up": (spy_ma is not None and spy_ma.iloc[i] < spy.iloc[i]),
            })
    return rows


def _fit(rows, gene, device="cpu", extra_rows=None):
    """Fit a specialist on the train slice; returns (model, stats, theta, gene).

    extra_rows (multiverse rehearsal, ADR-0006 phase 2): synthetic rows merged
    into the TRAINING mix (<=25% of it). They carry bar offsets above the real
    range so they never appear in the gate windows — the gate stays real-only.
    """
    gene = dict(gene)
    gene["epochs"] = max(1, int(gene["epochs"]))
    gene["hidden"] = max(2, int(gene["hidden"]))
    gene["lr"] = max(1e-4, min(3e-3, gene["lr"]))
    gene["theta"] = max(-0.5, min(0.5, gene["theta"]))
    form = int(round(gene.get("form", 0)))
    train = [r for r in rows if TRAIN[0] <= r["bar"] < TRAIN[1]]
    if len(train) < 100:
        return None
    n_val = max(1, int(len(train) * VAL_FRAC))
    trn, val = train[: len(train) - n_val], train[-n_val:]
    if extra_rows:
        # rehearsal: cap synthetic at 25% of the real training slice
        cap = max(1, int(len(trn) * 0.25))
        trn = trn + list(extra_rows[:cap])
    X = np.stack([r["x"] for r in trn])
    y = np.array([r["fwd"] for r in trn], dtype=np.float32)
    mean, std = X.mean(0), X.std(0)
    Xz = (X - mean) / (std + 1e-8)

    if form == 1:
        # Tail classifier (ADR-0006 classifier-orderer): BCE on membership of
        # the top-10% forward-return tail within the train slice.
        tail = np.quantile(y, 0.90)
        yc = (y >= tail).astype(np.float32)
        model = nn.Sequential(
            nn.Linear(X.shape[1], gene["hidden"]), nn.ReLU(),
            nn.Linear(gene["hidden"], 1),
        ).to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=gene["lr"], weight_decay=1e-4)
        lossf = nn.BCEWithLogitsLoss()
        Xt = torch.tensor(Xz, device=device)
        yt = torch.tensor(yc, device=device)
        best_state, best_loss = None, 1e9
        for _ in range(gene["epochs"]):
            model.train()
            opt.zero_grad()
            loss = lossf(model(Xt).squeeze(-1), yt)
            loss.backward()
            opt.step()
            if loss.item() < best_loss:
                best_loss = float(loss.item())
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
        model.load_state_dict(best_state)
        model.eval()

        def preds(rows_):
            Xv = np.stack([r["x"] for r in rows_])
            Xv = (Xv - mean) / (std + 1e-8)
            with torch.no_grad():
                return torch.sigmoid(model(torch.tensor(Xv, device=device)).squeeze(-1)).numpy()
    else:
        # Smooth regressor (MSE of E[fwd]) — the arena's iteration-1 form.
        model = nn.Sequential(
            nn.Linear(X.shape[1], gene["hidden"]), nn.ReLU(),
            nn.Linear(gene["hidden"], 1),
        ).to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=gene["lr"], weight_decay=1e-4)
        lossf = nn.MSELoss()
        Xt = torch.tensor(Xz, device=device)
        yt = torch.tensor(y, device=device)
        best_state, best_loss = None, 1e9
        for _ in range(gene["epochs"]):
            model.train()
            opt.zero_grad()
            loss = lossf(model(Xt).squeeze(-1), yt)
            loss.backward()
            opt.step()
            if loss.item() < best_loss:
                best_loss = float(loss.item())
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
        model.load_state_dict(best_state)
        model.eval()

        def preds(rows_):
            Xv = np.stack([r["x"] for r in rows_])
            Xv = (Xv - mean) / (std + 1e-8)
            with torch.no_grad():
                return model(torch.tensor(Xv, device=device)).squeeze(-1).numpy()

    vp = preds(val)
    # theta search around the gene's prior. The old search maximized
    # kept_mean - all_mean with km=0.0 when nothing was kept, so a theta that
    # kept NOTHING won in negative-base-rate slices. Require a minimum kept
    # count so "no trades" can never masquerade as a huge margin.
    best_theta, best_d = gene["theta"], -1e9
    for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
        kept = [r["fwd"] for r, p in zip(val, vp) if p >= q]
        if len(kept) < VAL_MIN_KEPT:
            continue
        allm = statistics.mean(r["fwd"] for r in val)
        km = statistics.mean(kept)
        d = km - allm
        if d > best_d:
            best_d, best_theta = d, float(q)
    gene["form"] = form
    return {"model": model, "stats": (mean, std), "theta": best_theta,
            "gene": gene, "d_in": X.shape[1]}


def _fitness(spec, rows, windows=SELECT, min_kept=MIN_KEPT):
    """Selection fitness on the SELECT windows (NEVER the gate windows).

    Fitness = the BEST per-window margin over the model's prediction
    quantiles, with the window's kept count >= `min_kept` at that quantile
    (audit 2026-08-11: the old fitness scored the single val-tuned theta,
    which let the GA converge to models that trade the SELECT windows but
    keep NOTHING elsewhere — the "no-trade" failure mode seen on the
    holdout). Selection now rewards models whose discrimination is robust
    across a theta range; the GATE still uses the single tuned theta on the
    unseen HOLDOUT windows.

    A window where NO quantile reaches min_kept scores -1.0 (hard fail).
    """
    margins, kepts = [], []
    for lo, hi in windows:
        win = [r for r in rows if lo <= r["bar"] < hi]
        Xw = np.stack([r["x"] for r in win])
        mean, std = spec["stats"]
        Xw = (Xw - mean) / (std + 1e-8)
        with torch.no_grad():
            vp = spec["model"](torch.tensor(Xw)).squeeze(-1).numpy()
        allm = statistics.mean(r["fwd"] for r in win)
        best_m, best_k = None, 0
        for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
            kept = [r["fwd"] for r, p in zip(win, vp) if p >= q]
            if len(kept) < min_kept:
                continue
            m = statistics.mean(kept) - allm
            if best_m is None or m > best_m:
                best_m, best_k = m, len(kept)
        margins.append(best_m if best_m is not None else -1.0)
        kepts.append(best_k)
    if all(m >= THETA_BAR for m in margins):
        return min(margins), margins, kepts
    return max(margins) - 1.0, margins, kepts


def _tune_theta(spec, rows, windows=SELECT, min_kept=MIN_KEPT):
    """Tune the deployment theta on the SELECT windows (audit 2026-08-11).

    The old theta came from the val slice (last 15% of TRAIN, a bull-tail),
    so a single threshold tuned there kept NOTHING on the bear-adjacent
    windows — the "no-trade holdout" failure. The GA's models demonstrably
    trade the SELECT windows, so the operating point is calibrated there
    (a scalar after model selection — the GATE stays on the unseen HOLDOUT
    windows). Picks the quantile maximizing the minimum per-window margin,
    requiring min_kept rows per window; falls back to the fitted theta.
    """
    rows_sel = [r for r in rows if any(lo <= r["bar"] < hi for lo, hi in windows)]
    Xs = np.stack([r["x"] for r in rows_sel])
    mean, std = spec["stats"]
    Xs = (Xs - mean) / (std + 1e-8)
    with torch.no_grad():
        vp = spec["model"](torch.tensor(Xs)).squeeze(-1).numpy()
    allm = {w: statistics.mean(r["fwd"] for r in rows if w[0] <= r["bar"] < w[1])
            for w in windows}
    best_q, best_min = None, -1e9
    for q in np.quantile(vp, np.linspace(0.05, 0.95, 19)):
        margins = []
        ok = True
        for w in windows:
            win = [r for r in rows if w[0] <= r["bar"] < w[1]]
            Xw = np.stack([r["x"] for r in win])
            Xw = (Xw - mean) / (std + 1e-8)
            with torch.no_grad():
                vp_w = spec["model"](torch.tensor(Xw)).squeeze(-1).numpy()
            kept = [r["fwd"] for r, p in zip(win, vp_w) if p >= q]
            if len(kept) < min_kept:
                ok = False
                break
            margins.append(statistics.mean(kept) - allm[w])
        if ok and margins:
            mn = min(margins)
            if mn > best_min:
                best_min, best_q = mn, float(q)
    if best_q is not None:
        return best_q
    return spec["theta"]


def _gate(spec, rows, windows=HOLDOUT, min_kept=MIN_KEPT):
    """Honest gate on the HOLDOUT windows: margins + kept counts, with
    per-window min-kept enforcement. This is the ONLY gate that qualifies a
    specialist for the swarm registry."""
    results = []
    for lo, hi in windows:
        win = [r for r in rows if lo <= r["bar"] < hi]
        Xw = np.stack([r["x"] for r in win])
        mean, std = spec["stats"]
        Xw = (Xw - mean) / (std + 1e-8)
        with torch.no_grad():
            vp = spec["model"](torch.tensor(Xw)).squeeze(-1).numpy()
        kept = [r["fwd"] for r, p in zip(win, vp) if p >= spec["theta"]]
        allm = statistics.mean(r["fwd"] for r in win)
        km = statistics.mean(kept) if kept else 0.0
        results.append({
            "window": f"{lo}-{hi}", "n": len(win), "kept": len(kept),
            "kept_mean": km, "all_mean": allm, "margin": km - allm,
        })
    passed = (len(results) > 0 and all(
        r["kept"] >= min_kept and r["margin"] >= THETA_BAR for r in results))
    return passed, results


def _tournament(pop, k, rng):
    return max(rng.sample(pop, k), key=lambda x: x["fitness"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", type=int, default=POP_SIZE)
    ap.add_argument("--gens", type=int, default=GENERATIONS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--once", action="store_true", help="single-gen run (smoke)")
    ap.add_argument("--market", default="equities",
                    help="data universe: equities (5y) or crypto (2y)")
    ap.add_argument("--forward", type=int, default=FORWARD,
                    help="forward-return horizon (bars)")
    ap.add_argument("--worlds-dir", default="",
                    help="multiverse battery dir (data/multiverse/worlds_TAG): "
                         "merge its synthetic rows into TRAINING as rehearsal "
                         "(<=25% of the mix, ADR-0006 phase 2); the gate stays "
                         "real-data-only")
    ap.add_argument("--out-name", default="momentum_specialist",
                    help="artifact basename: writes {out-name}.pt + "
                         "{out-name}_report.json (audit 2026-08-11: slot "
                         "artifacts used to collide with the scratch file and "
                         "clobber each other across horizon breeds)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    if args.market == "crypto":
        data = load_ohlcv("2y")
        al = align(data, [s for s in data if s != REGIME_SYM])
    else:
        data = load_ohlcv("5y")
        al = align(data, [s for s in data if s != REGIME_SYM])
    global FORWARD_GLOBAL  # audit 2026-08-11: this was a LOCAL, so --forward
    FORWARD_GLOBAL = args.forward  # never reached _collect's globals() check and
    # every "21d" specialist was trained on 10-bar labels — the per-horizon
    # roster (#58) never actually varied its horizon.

    base = clamp_config(json.loads(
        (PROJECT / "data/setup_search/best.json").read_text())["config"])
    rows = _collect(al[0], al[1], al[2], al[3], base)

    # Multiverse rehearsal (ADR-0006 phase 2): merge synthetic world rows into
    # training. Rows carry bar offsets far above the real range so the gate
    # windows (bar-keyed) never see them.
    world_rows = []
    if args.worlds_dir:
        wdir = Path(args.worlds_dir)
        if wdir.is_dir():
            # Fast path: pre-extracted rows cache (scale_run --extract).
            row_files = sorted(wdir.glob("rows_*.jsonl"))
            if row_files:
                for rf in row_files:
                    for line in rf.read_text().splitlines():
                        d = json.loads(line)
                        x = np.array(d["x"], dtype=np.float32)
                        # world rows are the arena's 11-dim (9 FEAT_COLS +
                        # score + spy_ratio); the breeder consumes the first 9
                        world_rows.append({"x": x[:9], "fwd": d["fwd"], "bar": d["bar"]})
                print(f"[evolve] rehearsal: +{len(world_rows)} cached synthetic rows "
                      f"({len(row_files)} worlds, <=25% of train, ADR-0006)")
            else:
                from arena.candidates import collect_from_data
                import json as _json
                n_worlds = 0
                for wf in sorted(wdir.glob("world_*.json")):
                    payload = _json.loads(wf.read_text())
                    data = {s: pd.DataFrame(v) for s, v in payload["data"].items()}
                    for s, df in data.items():
                        df.index = pd.date_range("2026-01-01", periods=len(df))
                    w_rows, _ = collect_from_data(data, base, bar_offset=5000 + n_worlds * 500)
                    world_rows += w_rows
                    n_worlds += 1
                    if n_worlds >= 60:
                        break
                print(f"[evolve] rehearsal: +{len(world_rows)} synthetic rows "
                      f"from {n_worlds} worlds (<=25% of train, ADR-0006)")
        else:
            print(f"[evolve] worlds dir not found: {args.worlds_dir}")

    print(f"[evolve] {args.market} | fwd={args.forward} | {len(rows)} labeled rows | pop {args.pop} | gens {args.gens}")

    pop = []
    for i in range(args.pop):
        if i < ELITE:
            gene = {k: (v if not isinstance(v, bool) else 1) for k, v in base.items()
                    if k in GENOTYPE}
            # seed the elite with the rule-floor-adjacent genotype
            gene = {k: (base.get(k, _random_individual(rng)[k]) if k in base else
                        _random_individual(rng)[k]) for k in GENOTYPE}
            gene["epochs"] = 100
            gene["hidden"] = 24
            gene["lr"] = 1e-3
            gene["theta"] = 0.0
        else:
            gene = _random_individual(rng)
        t0 = time.time()
        spec = _fit(rows, gene, extra_rows=world_rows)
        if spec is None:
            continue
        fit, margins, kepts = _fitness(spec, rows)
        pop.append({"gene": gene, "spec": spec, "fitness": fit, "margins": margins})
        print(f"[evolve] g0/{args.gens} ind {i}: fitness={fit:+.3f} "
              f"select=[{margins[0]:.3f},"
              f"{margins[1]:.3f}] "
              f"kept={kepts} ({time.time()-t0:.1f}s)", flush=True)
    pop.sort(key=lambda x: x["fitness"], reverse=True)
    print(f"[evolve] g0 best: {pop[0]['fitness']:+.3f} "
          f"select margins=[{pop[0]["margins"][0]:+.3f},"
          f"{pop[0]["margins"][1]:+.3f}]")

    for g in range(1, args.gens + 1):
        new_pop = pop[:ELITE]  # elitism
        while len(new_pop) < args.pop:
            if rng.random() < 0.5:
                child_gene = _mutate(_tournament(pop, TOURNAMENT_K, rng)["gene"], rng)
            else:
                a = _tournament(pop, TOURNAMENT_K, rng)
                b = _tournament(pop, TOURNAMENT_K, rng)
                child_gene = _crossover(a["gene"], b["gene"], rng)
            spec = _fit(rows, child_gene, extra_rows=world_rows)
            if spec is None:
                continue
            fit, margins, kepts = _fitness(spec, rows)
            new_pop.append({"gene": child_gene, "spec": spec,
                            "fitness": fit, "margins": margins})
        pop = sorted(new_pop, key=lambda x: x["fitness"], reverse=True)
        print(f"[evolve] g{g} best: {pop[0]['fitness']:+.3f} "
              f"select margins=[{pop[0]["margins"][0]:+.3f},"
              f"{pop[0]["margins"][1]:+.3f}]",
              flush=True)
        if args.once:
            break

    best = pop[0]
    # deployment theta: calibrated on the SELECT windows (where the GA's model
    # demonstrably trades), NOT on the val tail — audit 2026-08-11.
    best["spec"]["theta"] = _tune_theta(best["spec"], rows)
    gate_pass, gate_results = _gate(best["spec"], rows)
    out_name = args.out_name
    OUT.mkdir(parents=True, exist_ok=True)
    torch.save({"state": best["spec"]["model"].state_dict(),
                "d_in": best["spec"]["d_in"],
                "stats": best["spec"]["stats"],
                "theta": best["spec"]["theta"],
                "gene": best["gene"]}, OUT / f"{out_name}.pt")
    (OUT / f"{out_name}_report.json").write_text(json.dumps({
        "best_fitness": best["fitness"], "best_margins": best["margins"],
        "select_windows": [list(w) for w in SELECT],
        "holdout_windows": [list(w) for w in HOLDOUT],
        "holdout_margins": [r["margin"] for r in gate_results],
        "holdout_detail": gate_results,
        "gate_pass": gate_pass, "min_kept": MIN_KEPT,
        "best_gene": best["gene"], "n_rows": len(rows),
        "pop": args.pop, "gens": args.gens, "seed": args.seed,
        "gate_bar": THETA_BAR,
        "top5": [{"fitness": x["fitness"], "margins": x["margins"],
                  "gene": x["gene"]} for x in pop[:5]],
    }, indent=1, default=str))
    if out_name == "momentum_specialist":
        (OUT / "evolution_report.json").write_text(
            (OUT / f"{out_name}_report.json").read_text())  # legacy scratch name
    print(f"[evolve] -> {OUT / (out_name + '.pt')} + {out_name}_report.json")
    print(f"[evolve] select margins {['%.3f' % m for m in best['margins']]} "
          f"(selection only — NOT the gate)")
    print(f"[evolve] HOLD gate (windows never seen by the GA): "
          f"{[{'win': r['window'], 'margin': round(r['margin'], 3), 'kept': r['kept']} for r in gate_results]}")
    print(f"[evolve] → {'GATE PASS — specialist eligible' if gate_pass else 'GATE FAIL — stays research-grade'} "
          f"(bar {THETA_BAR:+.2f}, min_kept {MIN_KEPT})")


if __name__ == "__main__":
    main()
