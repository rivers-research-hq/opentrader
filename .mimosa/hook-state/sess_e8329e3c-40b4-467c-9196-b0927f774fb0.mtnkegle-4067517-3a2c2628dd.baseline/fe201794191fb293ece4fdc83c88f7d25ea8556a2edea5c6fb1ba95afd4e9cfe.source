#!/usr/bin/env python3
"""Prototype: MoT with 3 live LLM agents in shadow (wayfinder #55).

Wires the 3 fleet models as Experts (stand-ins for the future fine-tuned
agents) through the RegimeRouter, evaluates them in SHADOW on a sample of the
rule screen's candidates, records per-regime per-trade impact, and shows the
router's picks with the rule floor default. No trading changes.
"""

import json
import random
import re
import statistics
import sys
from pathlib import Path

import requests

from mot.mixture import RegimeRouter
from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
AGENTS = [("qwythos", "http://127.0.0.1:5802"),
          ("hermes", "http://127.0.0.1:5804"),
          ("qwen", "http://127.0.0.1:5805")]
SAMPLE = 18
FORWARD = 10
GEN_MIN = -0.5

SYSTEM = ("You are a trading agent. Given a stock entry signal, decide whether "
          "to take the long entry: take or skip. Respond JSON {\"take\": bool}.")


def judge(host, ctx):
    try:
        r = requests.post(f"{host}/v1/chat/completions",
                          json={"model": "x",
                                "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": ctx}],
                                "max_tokens": 40, "temperature": 0},
                          timeout=60)
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\"take\"\s*:\s*(true|false)", text.lower())
        return m.group(1) == "true" if m else False
    except Exception:
        return False


def main():
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, list(data.keys()))
    spy = al[0].get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean()
    feat = _features(al[0], al[1], al[2], al[3], base)
    w = base
    cands = []
    for sym in sorted(al[0].keys()):
        if sym == REGIME_SYM:
            continue
        c, f = al[0][sym], feat[sym]
        score = (w["w_mom"] * f["mom"] + w["w_rev"] * f["rev"] + w["w_rsi"] * f["rsi"]
                 + w["w_brk"] * f["brk"] + w["w_z"] * f["z"])
        fwd = (c.shift(-FORWARD) / c - 1.0).values
        for t in range(len(c) - FORWARD):
            s = score.iloc[t]
            if s != s or s < GEN_MIN:
                continue
            d = c.index[t]
            regime = "bull" if spy[d] > spy_ma200[d] else "bear"
            recent = " -> ".join(f"{v:,.0f}" for v in c.iloc[t - 8:t].tail(6))
            cands.append({"sym": sym, "ctx": f"{sym} closes: {recent} score={s:.2f}",
                          "fwd": float(fwd[t]), "regime": regime})
    rng = random.Random(7)
    rng.shuffle(cands)
    sample = cands[:SAMPLE]
    print(f"[shadow] {len(sample)} candidates across {set(c['regime'] for c in sample)}", flush=True)

    router = RegimeRouter(rule_floor="rule")
    for c in sample:
        for name, host in AGENTS:
            take = judge(host, c["ctx"])
            impact = c["fwd"] if take else 0.0
            router.record(c["regime"], name, impact)
        router.record(c["regime"], "rule", c["fwd"])  # rule takes all screen-passers
        print(f"  {c['sym']:6s} {c['regime']:4s} fwd={c['fwd']:+.1%}", flush=True)

    print("\n=== per-regime mean impact by agent ===")
    for regime in ("bull", "bear"):
        print(f"  {regime}:", end=" ")
        for name, _ in AGENTS:
            imp = router.mean_impact(regime, name)
            if imp is not None:
                print(f"{name}={imp:+.2%}", end=" ")
        r_imp = router.mean_impact(regime, "rule")
        print(f"rule={r_imp:+.2%} -> router picks {router.pick(regime)}")
    out = PROJECT / "data" / "research_gate" / "mot_3agent_shadow.json"
    out.write_text(json.dumps({"sample": SAMPLE, "agents": [a[0] for a in AGENTS],
                               "n_by_regime": {"bull": sum(1 for c in sample if c['regime']=='bull'),
                                               "bear": sum(1 for c in sample if c['regime']=='bear')}},
                              indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
