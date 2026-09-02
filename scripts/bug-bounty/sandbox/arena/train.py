"""One arena iteration: battle -> fit -> war -> relabel -> gate.

Iteration 1 has no agent: it fits the base value head (plain forward-return
targets — the closed map's baseline that fails the gate). Later iterations
train on the war-relabeled targets (r-tilde) produced by the previous
iteration's war, per 'Arena reward + war-relabeling protocol'.
"""

import json
from pathlib import Path

from setup_search.core import clamp_config

from arena import agent as agent_mod
from arena import battle as battle_mod
from arena import candidates as cand_mod
from arena import opponents as opp_mod
from arena import tech as tech_mod
from arena import view as view_mod
from arena import war as war_mod

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"


def run_iteration(
    period="5y",
    war_period="5y",
    round_size=25,
    n_battles=8,
    field_seed=7,
    eta=1.0,
    epochs=400,
    use_previous=False,
    grpo_steps=2,
    expert_id="momentum",
    augment_worlds=3,
    augment_fullcross=20000,
    worlds_dir="",
    fit_seed=23,
):
    rows, cfg = _collect_for(expert_id, period)
    extra_rows = _multiverse_augment(expert_id, cfg, augment_worlds, worlds_dir) if augment_worlds > 0 else []
    extra_rows += _fullcross_augment(expert_id, cfg, augment_fullcross) if augment_fullcross > 0 else []
    field = opp_mod.default_field(cfg, seed=field_seed)
    macro_ctx = _build_macro_ctx(war_period) if expert_id == "macro" else None
    data_source = _data_source_for(expert_id)

    agent_path = _checkpoint_for(expert_id)
    if use_previous and agent_path.exists():
        art = agent_mod.load(agent_path)
        if art is None:
            prev_report = agent_mod.load_report(agent_path)
            iteration = int(prev_report.get("iteration", 0)) + 1
            art = agent_mod.fit(rows, None, epochs=epochs, extra_rows=extra_rows or None, seed=fit_seed)
            print(
                f"[arena] checkpoint incompatible — refit fresh for iteration {iteration}",
                flush=True,
            )
        else:
            iteration = int(art["report"].get("iteration", 0)) + 1
    else:
        art = agent_mod.fit(rows, None, epochs=epochs, extra_rows=extra_rows or None, seed=fit_seed)
        art["report"]["iteration"] = 0
        iteration = 1
    print(
        f"[arena] iteration {iteration}: {len(rows)} candidates, {len(field)} opponents",
        flush=True,
    )

    agent_fn = agent_mod.make_agent(art)
    battles = []
    for i in range(n_battles):
        vals = agent_mod.predict_batch(art, [r["x"] for r in rows])
        evals = {
            (r["bar"], r["sym"]): (1 if v >= art["theta"] else 0, float(v))
            for r, v in zip(rows, vals)
        }
        battles.append(
            battle_mod.run_battle(rows, field, None, round_size, agent_evals=evals)
        )
        print(f"[arena]   battle pass {i + 1}/{n_battles} done", flush=True)
    agg = _aggregate_battles(battles)

    z_targets = {(k[0], k[1]): v["z"] for k, v in battles[-1]["arena_targets"].items()}
    relabels = _load_relabels()
    if relabels:
        for r in relabels:
            key = (r["bar"], r["sym"])
            z = z_targets.get(key)
            if z is not None:
                z_targets[key] = z + eta * r["delta"]
            else:
                z_targets[key] = r["tilde"]
        print(
            f"[arena]   targets: {len(z_targets)} battle-z rows + {len(relabels)} war-relabel overlays",
            flush=True,
        )
    else:
        print(
            f"[arena]   targets: {len(z_targets)} battle-z rows (no war relabels yet)",
            flush=True,
        )

    bear = war_mod.run_bear_war(
        rows,
        field,
        agent_mod.make_agent(art),
        cfg,
        bar_lo=0,
        bar_hi=250,
        buy_thresh=0.15,
        macro_ctx=macro_ctx,
        data_source=data_source,
    )
    print(
        f"[arena]   bear war done: {bear['n_base_trades']} down-regime trades",
        flush=True,
    )
    bear_by_key = {(r["bar"], r["sym"]): r["tilde"] for r in bear["relabels"]}
    extra_rows = [r for r in rows if (r["bar"], r["sym"]) in bear_by_key]
    extra_targets = [bear_by_key[(r["bar"], r["sym"])] for r in extra_rows]

    art = agent_mod.fit(
        rows,
        None,
        epochs=epochs,
        extra_rows=extra_rows,
        extra_targets=extra_targets,
        seed=fit_seed,
    )
    print(
        f"[arena]   value head fit done (raw fwd + {len(extra_rows)} bear relabels)",
        flush=True,
    )
    art["report"]["iteration"] = iteration
    agent_mod.save(art, path=_checkpoint_for(expert_id))

    war = war_mod.run_war(
        rows, field, agent_mod.make_agent(art), cfg, period=war_period, eta=eta,
        macro_ctx=macro_ctx, data_source=data_source,
    )
    combined = war["relabels"] + bear["relabels"]
    print(
        f"[arena]   war done: {war['base_n_trades']} base trades, {len(combined)} relabels",
        flush=True,
    )
    _atomic_write(OUT / "relabels.json", combined)

    router_info = _update_regime_router(war)

    grpo_info = _run_grpo_refine(rows, war, bear, art, steps=grpo_steps)
    if grpo_info:
        print(
            f"[arena]   GRPO refine: {grpo_info['n_decisions']} decisions, "
            f"loss={grpo_info['loss']:.4f}",
            flush=True,
        )
        agent_mod.recompute_gate(art, rows)
        _write_momentum_gate(art)
        agent_mod.save(art, path=_checkpoint_for(expert_id))

    mv_report = _run_multiverse_gate(rows, field, art, cfg, war_period, macro_ctx=macro_ctx)
    if mv_report:
        print(
            f"[arena]   multiverse gate: {mv_report['n_ruined']}/{mv_report['n_worlds']} worlds ruined "
            f"(pass={mv_report['pass']})",
            flush=True,
        )

    report = {
        "iteration": iteration,
        "n_candidates": len(rows),
        "field": [b.name for b in field],
        "battle": agg,
        "gate": art["report"],
        "war": {
            name: {k: v for k, v in book.items() if k != "trades"}
            for name, book in war["books"].items()
        },
        "war_regime": war["regime_decomp"],
        "war_base": {
            "net_return": war["base_net_return"],
            "n_trades": war["base_n_trades"],
        },
        "multiverse": mv_report,
        "grpo": grpo_info,
        "router": router_info,
        "n_relabels": len(combined),
        "n_bear_relabels": len(bear["relabels"]),
    }
    report["tech"] = tech_mod.snapshot(report, iteration)
    view_mod.write_snapshot(report)
    return report


def _update_regime_router(war, state_path=None):
    """Feed the fidelity war's per-regime impacts into a persisted RegimeRouter
    (closes seam e: the MoT rule-floor prior finally receives real data instead
    of the standalone demo). record() accrues sum/n per (regime, expert);
    pick() can then select a validated expert off the rule floor."""
    try:
        from mot.mixture import RegimeRouter

        state_path = state_path or PROJECT / "data" / "mot_router_state.json"
        router = RegimeRouter()
        if state_path.exists():
            import json as _json
            d = _json.loads(state_path.read_text())
            router.track = d.get("track", {})
            router.weights = d.get("weights", {})
        for name, decomp in war.get("regime_decomp", {}).items():
            for reg, stats in decomp.items():
                n = stats.get("n", 0)
                if n >= router.min_evidence:
                    router.record("up" if reg == "up" else "down", name, stats.get("mean_pnl_pct", 0.0))
                    # the war's rule bot is named 'rule-config'; the router's
                    # floor is 'rule'. record the floor's impact too, or pick()
                    # has no baseline to compare against.
                    if name == "rule-config":
                        router.record("up" if reg == "up" else "down", "rule", stats.get("mean_pnl_pct", 0.0))
        import json as _json
        state_path.write_text(_json.dumps(
            {"track": router.track, "weights": router.weights}, indent=1))
        picks = {reg: router.pick(reg) for reg in ("up", "down")}
        return {"picks": picks, "n_experts_tracked": len(
            {e for d in router.track.values() for e in d})}
    except Exception as e:
        print(f"[arena]   router update skipped ({e})", flush=True)
        return None


def _atomic_write(path, obj):
    """Write JSON via tmp-file + os.replace so a concurrent reader never sees a
    partial file (the previous write_text could interleave with a reader)."""
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1, default=str)
        os.replace(tmp, str(path))
    except BaseException:
        os.unlink(tmp)
        raise


def _load_relabels():
    """Guarded read of the war-relabel overlay file: corrupt or partial state
    must degrade to 'no relabels' (fresh fit), never crash the iteration."""
    try:
        if (OUT / "relabels.json").exists():
            return json.loads((OUT / "relabels.json").read_text())
    except Exception as e:
        print(f"[arena]   relabels.json unreadable ({e}); treating as none", flush=True)
    return None



def _fullcross_augment(expert_id, cfg, n_candidates):
    """MULTI-DATASET TRAINING from the 35M-row HuggingFace stock dataset:
    32 years x ~11k symbols of daily OHLCV in the SAME feature space as the
    validated rule. Candidates are sampled and appended to the REAL training
    set via fit(extra_rows=...); the gate stays on the real 5y archive.
    Uses the cached build (data/setup_search/fullcross.pkl) when present."""
    if expert_id != "momentum":
        return []
    from arena.candidates_fullcross import CACHE
    if not CACHE.exists():
        print("[arena]   fullcross augmentation skipped (build not cached yet; "
              "run arena/candidates_fullcross.py once)", flush=True)
        return []
    try:
        from arena.candidates_fullcross import collect as fullcross_collect
        # 25 liquid symbols x ~6.7k bars each ~= 60k candidates in ~3min; the
        # 6-position cap means breadth beyond this adds little per iteration
        fc_rows, _ = fullcross_collect(sample=n_candidates, n_symbols=25)
        print(f"[arena]   fullcross augmentation: +{len(fc_rows)} candidates "
              f"(35M-row HF dataset)", flush=True)
        return fc_rows
    except Exception as e:
        print(f"[arena]   fullcross augmentation skipped ({e})", flush=True)
        return []


def _multiverse_augment(expert_id, cfg, n_worlds, worlds_dir=""):
    """MULTI-DATASET TRAINING: generate n_worlds market realities (neural
    generator if trained, else parametric) and build arena candidate rows
    from them, appended to the REAL training set via fit(extra_rows=...).

    The gate windows, val split, war relabels and GRPO decisions all consume
    the REAL rows only (synthetic bars are offset to 2000+ so they never
    collide) — the held-out discrimination benchmark stays real-data-only,
    while the model trains on real + synthetic distributions."""
    if expert_id == "macro":
        return []  # world rows are 11-dim; macro (18-dim) would crash the fit
    # world rows are 11-dim, so every 11-dim expert (momentum, ftmo,
    # international, us) can consume them as training augmentation
    try:
        from arena.candidates import collect_from_data
        from scenarios import MarketScenarioGenerator
        from scenarios.spec import ScenarioSpec

        if worlds_dir:
            # Battery fast path: pre-extracted row caches (scale_run --extract).
            from pathlib import Path as _Path
            import numpy as _np
            wdir = _Path(worlds_dir)
            row_files = sorted(wdir.glob("rows_*.jsonl"))
            if row_files:
                import json as _json
                extra = []
                for rf in row_files[:n_worlds]:
                    for line in rf.read_text().splitlines():
                        d = _json.loads(line)
                        extra.append({"x": _np.array(d["x"], dtype=_np.float32),
                                      "fwd": d["fwd"], "bar": d["bar"]})
                print(f"[arena]   multiverse augmentation (battery): +{len(extra)} "
                      f"synthetic candidates ({len(row_files[:n_worlds])} worlds)", flush=True)
                return extra

        gen = MarketScenarioGenerator()
        extra = []
        for i in range(n_worlds):
            w = gen.generate(1, base_spec=ScenarioSpec(seed=100 + i, n_bars=500))[0]
            w_rows, _ = collect_from_data(w.data, cfg, bar_offset=2000 + i * 1000)
            extra += w_rows
        print(f"[arena]   multiverse augmentation: +{len(extra)} synthetic candidates "
              f"({n_worlds} worlds)", flush=True)
        return extra
    except Exception as e:
        print(f"[arena]   multiverse augmentation skipped ({e})", flush=True)
        return []


def _collect_for(expert_id, period):
    if expert_id == "macro":
        from arena import candidates_macro
        return candidates_macro.collect(period)
    if expert_id == "international":
        from arena import candidates_international
        return candidates_international.collect(period)
    if expert_id == "ftmo":
        from setup_search.ftmo_universe import collect as ftmo_collect
        return ftmo_collect(period)
    return cand_mod.collect(period)


def _data_source_for(expert_id):
    """Archive loader the WAR referee should replay. Momentum/macro replay the
    US archive (default); the international expert replays its own universe;
    ftmo replays the FTMO-US universe (SPY = DXY regime anchor)."""
    if expert_id == "international":
        from arena import candidates_international
        return candidates_international.load_international
    if expert_id == "ftmo":
        from setup_search.ftmo_universe import load_ftmo, DXY_AS_SPY
        return lambda period="5y", **kw: DXY_AS_SPY(load_ftmo())
    return None


def _checkpoint_for(expert_id="momentum"):
    try:
        from mot.roster import SPECIALIZATIONS
        ck = SPECIALIZATIONS.get(expert_id, {}).checkpoint
        if ck:
            return Path(ck)
    except Exception:
        pass
    return OUT / "arena_value_head.pt"


def _write_momentum_gate(art):
    """Closes seam e: skill s15 / tech 'mot-weight' check
    data/arena/momentum_gate.json, which nothing ever wrote. Write it when the
    (post-GRPO) held-out discrimination gate passes, so the curriculum can
    actually graduate."""
    try:
        passed = bool(art.get("report", {}).get("pass"))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "momentum_gate.json").write_text(
            json.dumps({"pass": passed, "report": art["report"].get("results", []),
                        "written": "arena"}, indent=1)
        )
    except Exception as e:
        print(f"[arena]   momentum_gate write skipped ({e})", flush=True)


def _grpo_decisions(rows, relabels, group_label, action=1):
    by_key = {(r["bar"], r["sym"]): r for r in rows}
    ds = []
    for rl in relabels:
        row = by_key.get((rl["bar"], rl["sym"]))
        if row is None:
            continue
        ds.append({"x": row["x"], "action": action, "reward": rl["pnl_pct"], "group": group_label})
    return ds


def _run_grpo_refine(rows, war, bear, art, steps=2, min_decisions=8):
    """Refine the fitted value head with real GRPO (seam b): the war's realized
    pnl_pct is the reward, the regime field (bull/bear) is the GRPO group, and
    the advantage is the group-relative z-score of (reward - V(s)). Silent if
    too few decisions or the module is unavailable."""
    try:
        from arena import grpo as grpo_mod

        decisions = _grpo_decisions(rows, war["relabels"], "bull")
        decisions += _grpo_decisions(rows, bear["relabels"], "bear")
        if len(decisions) < min_decisions:
            print(f"[arena]   GRPO skip: only {len(decisions)} decisions (< {min_decisions})", flush=True)
            return None
        grpo_mod.fit_grpo(art, decisions, steps=steps)
        return {
            "steps": steps,
            "n_decisions": len(decisions),
            "loss": art["report"].get("grpo", {}).get("loss"),
            "mean_abs_advantage": art["report"].get("grpo", {}).get("mean_abs_advantage"),
        }
    except Exception as e:
        print(f"[arena]   GRPO refine skipped ({e})", flush=True)
        return None


def _build_macro_ctx(period="5y"):
    """Precompute the macro expert's per-symbol feature arrays for the war
    referee, from the SAME archive the fidelity war replays (period must match
    war_period). None if FRED/VIX are unavailable."""
    try:
        from arena.war import build_macro_ctx
        from setup_search.data import load_ohlcv, align, REGIME_SYM
        from setup_search.engine import _features
        import json as _json
        data = load_ohlcv(period)
        al = align(data, [s for s in data if s != REGIME_SYM])
        closes, highs, lows, vols = al
        cfg = clamp_config(_json.loads(
            (PROJECT / "data/setup_search/best.json").read_text())["config"])
        feat = _features(closes, highs, lows, vols, cfg)
        return build_macro_ctx(closes, feat)
    except Exception as e:
        print(f"[arena]   macro ctx unavailable ({e}); war uses 11-dim states", flush=True)
        return None


def _run_multiverse_gate(rows, field, art, cfg, war_period="5y", n_base=2, n_per_event=1,
                         macro_ctx=None):
    """Second gate: run the fitted agent through generated worlds (everyday +
    crisis multiverse). Fails silently (returns None) if scenarios/ can't load,
    so the arena loop never breaks on a generator problem."""
    try:
        from scenarios import MarketScenarioGenerator, crisis_worlds
        from scenarios.spec import ScenarioSpec
        from arena.war import run_multiverse_war

        gen = MarketScenarioGenerator()
        base = gen.generate(n_base, base_spec=ScenarioSpec(seed=11))
        worlds = base + crisis_worlds(n_per_event=n_per_event, base_spec=ScenarioSpec(seed=11))
        return run_multiverse_war(
            worlds, field, agent_mod.make_agent(art), cfg, period=war_period,
            macro_ctx=macro_ctx,
        )
    except Exception as e:
        print(f"[arena]   multiverse gate skipped ({e})", flush=True)
        return None


def _aggregate_battles(battles):
    standings = {}
    names = list(battles[0]["standings"].keys())
    for n in names:
        row = battles[0]["standings"][n]
        agg = {k: sum(b["standings"][n][k] for b in battles) for k in row}
        agg["take_mean"] = agg["take_fwd_sum"] / agg["takes"] if agg["takes"] else 0.0
        agg["arena_score"] = agg["take_z_sum"] / agg["takes"] if agg["takes"] else 0.0
        del agg["take_fwd_sum"], agg["take_z_sum"]
        standings[n] = agg
    h2h = {}
    for n in battles[0]["h2h"]:
        wins = sum(b["h2h"][n]["wins"] for b in battles)
        losses = sum(b["h2h"][n]["losses"] for b in battles)
        h2h[n] = {"wins": wins, "losses": losses}
    rounds = []
    for bi, b in enumerate(battles):
        for r in b["rounds"]:
            r2 = dict(r)
            r2["battle"] = bi
            rounds.append(r2)
    return {"standings": standings, "h2h": h2h, "rounds": rounds}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--use-previous", action="store_true")
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--n-battles", type=int, default=8)
    ap.add_argument("--eta", type=float, default=1.0)
    ap.add_argument("--grpo-steps", type=int, default=2)
    ap.add_argument("--augment-worlds", type=int, default=3,
                    help="Multi-dataset training: N generated worlds appended to the real candidates")
    ap.add_argument("--augment-fullcross", type=int, default=20000,
                    help="Multi-dataset training: sample N candidates from the 35M-row HF stock dataset")
    ap.add_argument("--fit-seed", type=int, default=23,
                    help="fit RNG seed (protocol: one seed per run)")
    ap.add_argument("--worlds-dir", type=str, default="",
                    help="multiverse battery dir (data/multiverse/worlds_TAG): "
                         "use its extracted row caches as augmentation instead "
                         "of on-the-fly generation (audit 2026-08-11 re-port)")
    args = ap.parse_args()
    for i in range(args.iterations):
        rep = run_iteration(
            epochs=args.epochs,
            n_battles=args.n_battles,
            eta=args.eta,
            use_previous=(i > 0) or args.use_previous,
            grpo_steps=args.grpo_steps,
            augment_worlds=args.augment_worlds,
            augment_fullcross=args.augment_fullcross,
            worlds_dir=args.worlds_dir,
            fit_seed=args.fit_seed,
        )
        print(
            f"iteration {rep['iteration']}: gate pass={rep['gate']['pass']} "
            f"margins={[r['margin'] for r in rep['gate']['results']]}"
        )
