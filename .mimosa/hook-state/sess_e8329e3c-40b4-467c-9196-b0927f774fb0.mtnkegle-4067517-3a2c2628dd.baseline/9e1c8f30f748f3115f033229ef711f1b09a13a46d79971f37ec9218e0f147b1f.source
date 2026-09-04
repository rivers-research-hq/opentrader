#!/usr/bin/env python3
"""Adversarial breaking tests — throw degenerate inputs at the Phase 1-4 build.

The point is to FIND weaknesses, not to pass. Each test runs in isolation; a
CRASH is a finding (unhandled exception). A PASS on an edge case is also a
finding (robustness). Run with the rocm venv:
  /home/mrc/rocm_venv/bin/python3 tests/break_scenarios.py
"""
from __future__ import annotations

import sys
import traceback
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

warnings.filterwarnings("ignore")

RESULTS = []
REGISTRY = []


def t(name):
    def deco(fn):
        def run():
            try:
                out = fn()
                return name, "PASS", (str(out) if out else "")
            except Exception:
                return name, "CRASH", traceback.format_exc(limit=2).strip().splitlines()[-1]
        REGISTRY.append(run)
        return run
    return deco


# --------------------------------------------------------------------------
# scenarios/parametric — degenerate sizes, determinism, SPY presence
# --------------------------------------------------------------------------
@t("parametric n_bars=1")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=1, seed=1))
    return f"{len(d)} syms, rows={len(d['AAPL'])}, finite={np.isfinite(d['AAPL']['close'].to_numpy()).all()}"


@t("parametric n_bars=2")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=2, seed=1))
    return f"rows={len(d['AAPL'])}"


@t("parametric n_bars=5000 (long horizon)")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=5000, seed=1))
    return f"rows={len(d['AAPL'])}, closes finite={np.isfinite(d['AAPL']['close']).all()}"


@t("parametric vol_mult=100 (extreme)")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=200, vol_mult=100.0, seed=1))
    c = d["AAPL"]["close"].to_numpy()
    return f"min close={c.min():.3g} (<=0 is a bug), finite={np.isfinite(c).all()}"


@t("parametric determinism (same seed twice)")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    a = generate(ScenarioSpec(n_bars=100, seed=42))["AAPL"]["close"].to_numpy()
    b = generate(ScenarioSpec(n_bars=100, seed=42))["AAPL"]["close"].to_numpy()
    return f"identical={np.array_equal(a, b)}"


@t("parametric symbols without SPY (world has no regime marker)")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=100, symbols=["AAPL", "MSFT"], seed=1))
    return f"SPY present: {'SPY' in d} (world without SPY breaks the war align)"


@t("inject_event on 3-bar world")
def _():
    from scenarios.parametric import generate, inject_event
    from scenarios.spec import ScenarioSpec
    from scenarios.tail_library import get_event
    d = generate(ScenarioSpec(n_bars=3, seed=1))
    out = inject_event(d, get_event("flash_crash"), seed=1)
    return f"rows={len(out['AAPL'])}, finite={np.isfinite(out['AAPL']['close']).all()}"


@t("inject_event leaves volume finite")
def _():
    from scenarios.parametric import generate, inject_event
    from scenarios.spec import ScenarioSpec
    from scenarios.tail_library import get_event
    d = generate(ScenarioSpec(n_bars=500, seed=1))
    out = inject_event(d, get_event("us_debt_ceiling"), seed=1)
    return f"vol finite={np.isfinite(out['AAPL']['volume']).all()}"


# --------------------------------------------------------------------------
# scenarios/generator + evaluate
# --------------------------------------------------------------------------
@t("generator generate(0) worlds")
def _():
    from scenarios import MarketScenarioGenerator
    w = MarketScenarioGenerator().generate(0)
    return f"n={len(w)}"


@t("generator event on empty list")
def _():
    from scenarios import MarketScenarioGenerator
    w = MarketScenarioGenerator().generate(0, events=["us_debt_ceiling"])
    return f"n={len(w)}"


@t("evaluate.gate with EMPTY worlds")
def _():
    import pickle
    from scenarios.evaluate import gate
    real = pickle.load(open("data/setup_search/ohlcv_5y.pkl", "rb"))
    return gate([], real)


@t("evaluate.compare with all-NaN world")
def _():
    import pickle
    from scenarios.evaluate import compare
    from scenarios.spec import ScenarioSpec, World
    import pandas as pd
    real = pickle.load(open("data/setup_search/ohlcv_5y.pkl", "rb"))
    idx = real["AAPL"].index
    bad = {s: pd.DataFrame(np.nan, index=idx, columns=["open", "high", "low", "close", "volume"])
           for s in real}
    return compare([World(spec=ScenarioSpec(), data=bad)], real)


# --------------------------------------------------------------------------
# scenarios/neural
# --------------------------------------------------------------------------
@t("neural generate_world n_bars=1 (torch path)")
def _():
    from scenarios.neural import NeuralMarketGenerator
    from scenarios.spec import ScenarioSpec
    g = NeuralMarketGenerator(device="cpu")
    g._trained = True  # shape test only: bypass training
    d = g.generate_world(ScenarioSpec(n_bars=1, seed=1))
    return f"syms={len(d)}, rows={len(d['AAPL'])}"


@t("neural save/load roundtrip")
def _():
    import tempfile, os
    from scenarios.neural import NeuralMarketGenerator
    g = NeuralMarketGenerator(device="cpu")
    fd, path = tempfile.mkstemp(suffix=".pt")
    os.close(fd)
    g.save(path)
    g2 = NeuralMarketGenerator(device="cpu")
    g2.load(path)
    os.unlink(path)
    return f"trained={g2._trained}"


@t("neural train on zero windows")
def _():
    from scenarios.neural import NeuralMarketGenerator
    from scenarios.neural import _make_windows
    try:
        _make_windows(np.zeros((10, 17)), window=256)
        return "no crash"
    except Exception:
        return "make_windows raises on too-short data"

# --------------------------------------------------------------------------
# arena/grpo — reward degeneracy
# --------------------------------------------------------------------------
@t("grpo all-equal rewards (zero advantage std)")
def _():
    from arena import agent as agent_mod
    from arena import grpo as grpo_mod
    import torch
    torch.manual_seed(0)
    m = agent_mod.ArenaMLP(5)
    mean = np.zeros(5); std = np.ones(5)
    ds = [{"x": np.random.rand(5).astype(np.float32), "action": 1, "reward": 0.5, "group": "g"}
          for _ in range(20)]
    loss, adv = grpo_mod.grpo_update(m, 0.0, mean, std, ds)
    return f"loss={loss:.4f} adv={adv:.4f} (zero-std advantage should not NaN)"


@t("grpo NaN reward")
def _():
    from arena import agent as agent_mod
    from arena import grpo as grpo_mod
    import torch
    torch.manual_seed(0)
    m = agent_mod.ArenaMLP(5)
    mean = np.zeros(5); std = np.ones(5)
    ds = [{"x": np.random.rand(5).astype(np.float32), "action": 1, "reward": np.nan, "group": "g"}
          for _ in range(20)]
    loss, adv = grpo_mod.grpo_update(m, 0.0, mean, std, ds)
    return f"loss={loss:.4f} (NaN reward should be guarded, not poison the update)"


@t("grpo inf reward")
def _():
    from arena import agent as agent_mod
    from arena import grpo as grpo_mod
    import torch
    torch.manual_seed(0)
    m = agent_mod.ArenaMLP(5)
    mean = np.zeros(5); std = np.ones(5)
    ds = [{"x": np.random.rand(5).astype(np.float32), "action": 1, "reward": np.inf, "group": "g"}
          for _ in range(20)]
    loss, adv = grpo_mod.grpo_update(m, 0.0, mean, std, ds)
    return f"loss={loss:.4f}"


@t("grpo single decision")
def _():
    from arena import agent as agent_mod
    from arena import grpo as grpo_mod
    import torch
    torch.manual_seed(0)
    m = agent_mod.ArenaMLP(5)
    mean = np.zeros(5); std = np.ones(5)
    ds = [{"x": np.random.rand(5).astype(np.float32), "action": 1, "reward": 0.1, "group": "g"}]
    loss, adv = grpo_mod.grpo_update(m, 0.0, mean, std, ds)
    return f"loss={loss:.4f}"


# --------------------------------------------------------------------------
# arena/war — degenerate worlds
# --------------------------------------------------------------------------
@t("multiverse_war with EMPTY worlds")
def _():
    from arena.war import run_multiverse_war
    from arena import opponents as opp_mod
    from setup_search.core import clamp_config
    cfg = clamp_config({})
    field = opp_mod.default_field(cfg, seed=7)
    def ag(state): return (False, 0.0)
    out = run_multiverse_war([], field, ag, cfg)
    return f"n_worlds={out['n_worlds']} pass={out['pass']} mean={out.get('mean_net_return')}"


@t("multiverse_war world missing SPY")
def _():
    from arena.war import run_multiverse_war
    from arena import opponents as opp_mod
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec, World
    from setup_search.core import clamp_config
    cfg = clamp_config({})
    field = opp_mod.default_field(cfg, seed=7)
    def ag(state): return (False, 0.0)
    data = generate(ScenarioSpec(n_bars=200, symbols=["AAPL", "MSFT"], seed=1))
    out = run_multiverse_war([World(spec=ScenarioSpec(), data=data)], field, ag, cfg)
    return f"world_0 error={out['world_0'].get('error')}"


@t("multiverse_war 1-bar world")
def _():
    from arena.war import run_multiverse_war
    from arena import opponents as opp_mod
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec, World
    from setup_search.core import clamp_config
    cfg = clamp_config({})
    field = opp_mod.default_field(cfg, seed=7)
    def ag(state): return (False, 0.0)
    data = generate(ScenarioSpec(n_bars=1, seed=1))
    out = run_multiverse_war([World(spec=ScenarioSpec(), data=data)], field, ag, cfg)
    return f"world_0 error={out['world_0'].get('error')}"


# --------------------------------------------------------------------------
# mot/mixture router + roster
# --------------------------------------------------------------------------
@t("router.record NaN impact")
def _():
    from mot.mixture import RegimeRouter
    r = RegimeRouter()
    r.record("up", "exp", float("nan"))
    return f"mean_impact={r.mean_impact('up', 'exp')} (NaN should be rejected)"


@t("router.pick on empty")
def _():
    from mot.mixture import RegimeRouter
    r = RegimeRouter()
    return f"pick={r.pick('up')} (should be rule floor)"


@t("router.step reset on failure (tuple-key contract)")
def _():
    from mot.mixture import RegimeRouter
    r = RegimeRouter()
    r.record("up", "exp", 0.1)
    r.step({("up", "exp"): 0})
    return f"weights={r.weights}"


@t("roster.build_expert unknown id")
def _():
    from mot.roster import build_expert
    return f"result={build_expert('does-not-exist')}"


@t("roster.train_expert unknown id")
def _():
    from mot.roster import train_expert
    try:
        train_expert("does-not-exist")
        return "no error raised"
    except KeyError as e:
        return f"KeyError (correct): {e}"


# --------------------------------------------------------------------------
# arena/agent — empty/degenerate
# --------------------------------------------------------------------------
@t("predict_batch on empty rows")
def _():
    from arena import agent as agent_mod
    import torch
    m = agent_mod.ArenaMLP(5)
    art = {"model": m, "mean": np.zeros(5), "std": np.ones(5)}
    out = agent_mod.predict_batch(art, [])
    return f"shape={out.shape}"


# --------------------------------------------------------------------------
# arena/train — the hardcoded TESTS windows vs a 1y archive
# --------------------------------------------------------------------------
@t("run_iteration period=1y (TESTS windows hardcoded to 5y bars)")
def _():
    from arena.train import run_iteration
    rep = run_iteration(period="1y", war_period="1y", round_size=15, n_battles=1,
                        field_seed=7, eta=0.5, epochs=2, use_previous=False, grpo_steps=0)
    return f"iter={rep['iteration']} gate_pass={rep['gate']['pass']}"


# --------------------------------------------------------------------------
# second wave — invariants + the newly hardened paths
# --------------------------------------------------------------------------
@t("parametric symbols w/o SPY now enforces SPY marker")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=100, symbols=["AAPL", "MSFT"], seed=1))
    return f"SPY present: {'SPY' in d}"


@t("router.record NaN now rejected")
def _():
    from mot.mixture import RegimeRouter
    r = RegimeRouter()
    r.record("up", "exp", float("nan"))
    return f"mean_impact={r.mean_impact('up', 'exp')} (None = rejected)"


@t("FUZZ: 50 seeds, all closes positive+finite, OHLCV sane")
def _():
    import numpy as np
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    bad = []
    for seed in range(50):
        d = generate(ScenarioSpec(n_bars=300, seed=seed))
        for s, df in d.items():
            c = df["close"].to_numpy()
            if not np.isfinite(c).all() or (c <= 0).any():
                bad.append((seed, s))
            if not (df["high"].to_numpy() >= df["low"].to_numpy()).all():
                bad.append((seed, s, "high<low"))
    return f"violations={bad[:3]} (expect none)"


@t("generate symbols=[] uses default universe")
def _():
    from scenarios.parametric import generate
    from scenarios.spec import ScenarioSpec
    d = generate(ScenarioSpec(n_bars=50, symbols=[], seed=1))
    return f"syms={len(d)} (expect 17)"


@t("generator with unknown event id (skipped, no crash)")
def _():
    from scenarios import MarketScenarioGenerator
    w = MarketScenarioGenerator().generate(2, events=["not-a-real-event"])
    return f"n={len(w)} spec.event={w[0].spec.event}"


@t("neural generate_world in crisis regime")
def _():
    from scenarios.neural import NeuralMarketGenerator
    from scenarios.spec import ScenarioSpec
    g = NeuralMarketGenerator(device="cpu")
    g._trained = True
    d = g.generate_world(ScenarioSpec(n_bars=200, regime="crisis", event="us_debt_ceiling"))
    c = d["SPY"]["close"].to_numpy()
    return f"syms={len(d)} draws {round((c[-1]/c[0]-1)*100,1)}% over 200 bars"


@t("multiverse_war with all-NaN world (per-world isolation)")
def _():
    from arena.war import run_multiverse_war
    from arena import opponents as opp_mod
    from scenarios.spec import ScenarioSpec, World
    from setup_search.core import clamp_config
    import pandas as pd
    import numpy as np
    cfg = clamp_config({})
    field = opp_mod.default_field(cfg, seed=7)
    def ag(state): return (False, 0.0)
    idx = pd.bdate_range(end="2026-07-31", periods=300)
    data = {s: pd.DataFrame(np.nan, index=idx, columns=["open","high","low","close","volume"])
            for s in ["SPY","AAPL","MSFT","NVDA"]}
    out = run_multiverse_war([World(spec=ScenarioSpec(), data=data)], field, ag, cfg)
    return f"world_0 error recorded: {bool(out['world_0'].get('error'))}, n_ruined={out['n_ruined']}"


@t("run_backtest full engine on crisis world w/ regime filter")
def _():
    import numpy as np
    from scenarios.parametric import generate_with_event
    from scenarios.spec import ScenarioSpec
    from scenarios.tail_library import get_event
    from setup_search.data import align, REGIME_SYM
    from setup_search.engine import _features, run_backtest
    from setup_search.core import clamp_config
    d = generate_with_event(ScenarioSpec(n_bars=500, seed=3), get_event("yen_unwind"))
    al = align(d, [s for s in d if s != REGIME_SYM])
    closes, highs, lows, vols = al
    cfg = clamp_config({"regime_filter": 1, "regime_window": 200, "buy_thresh": 0.0})
    res = run_backtest(al, cfg)
    return f"net_return={res['net_return']:.3f} n_trades={res['n_trades']}"


@t("crisis worlds ALWAYS produce the named tail (debt crisis drawdown)")
def _():
    import numpy as np
    from scenarios.parametric import generate_with_event
    from scenarios.spec import ScenarioSpec
    from scenarios.tail_library import get_event
    d = generate_with_event(ScenarioSpec(n_bars=500, seed=7), get_event("us_debt_ceiling"))
    c = d["SPY"]["close"].to_numpy()
    peak = np.maximum.accumulate(c)
    dd = (c - peak) / peak
    return f"max SPY drawdown in debt-crisis world: {dd.min()*100:.1f}% (expect clearly negative)"


if __name__ == "__main__":
    for run in REGISTRY:
        name, status, detail = run()
        RESULTS.append((name, status, detail))
    for name, status, detail in RESULTS:
        print(f"[{status:5s}] {name}")
        if status == "CRASH":
            print(f"         {detail}")
    print(f"\n=== {len([r for r in RESULTS if r[1]=='CRASH'])} crashes / {len(RESULTS)} tests ===")
