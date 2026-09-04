#!/usr/bin/env python3
"""Synthetic trap test: the higher bar the model must clear.

Collects EVERY signal that passes the rule screen on the OOS folds (not just
the trades the rule took), with realized forward returns. Real screen-passers
include bullish-looking setups that FAILED (the traps). If the real mix is too
bullish, synthetic traps are added: bullish contexts (sharp pullback in an
uptrend, high rule score) with a forced negative outcome — designed to trap a
model that rubber-stamps "looks bullish = take."

The model (taught with positive AND negative lessons) judges each signal.
Bar: its kept-mean must be ABOVE the all-candidates mean by a real margin —
a model that takes everything (or takes the traps) FAILS.

Writes data/research_gate/trap_test.json.
"""

import json
import random
import re
import statistics
from pathlib import Path

import requests

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align, slice_aligned
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:5802/v1/chat/completions"
MODEL = "qwythos-9b-mtp"
FOLDS = [(500, 750), (750, 1000), (1000, 1250)]
FORWARD = 10  # bars forward for realized outcome
TARGET_LOSER_FRAC = 0.40  # mix toward ~40% traps so rubber-stamping fails
SEED = 17

SYSTEM = (
    "You are an apprentice trader. A validated rule system produced these entry "
    "signals; some are REAL opportunities, some are TRAPS that look bullish but "
    "fail. Learn from the lessons, then for each signal decide whether to take "
    "the long entry. A disciplined pullback in an uptrend is usually good, but "
    "genuine breakdowns, crashes, or regime failures are traps even when they "
    "look like pullbacks. DEFAULT TO NO unless the setup is clearly the good "
    "pattern. Respond ONLY with JSON: {\"take\": true|false, \"reason\": \"one line\"}"
)


def collect_candidates(closes, highs, lows, vols, cfg):
    """All screen-passing signals + realized forward returns on the OOS folds."""
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if cfg["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()
    cands = []
    syms = sorted(closes.keys())
    for sym in syms:
        c = closes[sym]
        f = feat[sym]
        for t in range(len(c)):
            date = c.index[t]
            if t + FORWARD >= len(c):
                break
            if sym == REGIME_SYM:
                continue
            if float(f.iloc[t]["close"]) <= 0:
                continue
            regime_ok = True
            if spy_ma is not None and date in spy_ma.index:
                regime_ok = float(spy[date]) > float(spy_ma[date])
            score = float(_score_at({s: f.loc[date] for s in [sym]}, cfg,
                                    {sym: 0.0})[sym])
            if score >= cfg["buy_thresh"] and regime_ok:
                fwd = float(c.loc[c.index[t + FORWARD]]) / float(c.iloc[t]) - 1.0
                cands.append({
                    "sym": sym, "date": date, "entry": float(c.iloc[t]),
                    "score": round(score, 3), "fwd": fwd,
                    "ctx": (f"Symbol: {sym}\nRecent closes: "
                            f"{' -> '.join(f'{v:,.0f}' for v in c.loc[:date].tail(8))}\n"
                            f"Entry ~ {float(c.iloc[t]):,.2f} | score {score:.2f} "
                            f"(threshold {cfg['buy_thresh']}) | regime: {'up' if regime_ok else 'down'}"),
                })
    return cands


def add_synthetic_traps(cands, rng):
    """Add bullish-looking traps with forced negative outcomes to balance the mix."""
    winners = [c for c in cands if c["fwd"] > 0]
    losers = [c for c in cands if c["fwd"] <= 0]
    need = int(len(cands) / (1 - TARGET_LOSER_FRAC) * TARGET_LOSER_FRAC) - len(losers)
    traps = []
    for i in range(max(0, need)):
        src = rng.choice(winners)
        traps.append({
            "sym": src["sym"], "date": src["date"], "entry": src["entry"],
            "score": src["score"], "fwd": -abs(rng.uniform(0.03, 0.08)),
            "ctx": src["ctx"],
            "synthetic_trap": True,
        })
    return cands + traps


def build_lessons(cands):
    winners = sorted([c for c in cands if c["fwd"] > 0], key=lambda c: -c["fwd"])
    losers = sorted([c for c in cands if c["fwd"] <= 0], key=lambda c: c["fwd"])
    w = "\n\n".join(f"GOOD: {c['ctx']} -> PROFITABLE (+{c['fwd']:+.1%})"
                    for c in winners[:3])
    l = "\n\n".join(f"TRAP: {c['ctx']} -> FAILED ({c['fwd']:+.1%})"
                    for c in losers[:3])
    return (f"LESSONS (positive examples):\n{w}\n\n"
            f"LESSONS (negative examples - these LOOK bullish but FAILED):\n{l}\n\n"
            "The negative examples are the TRAPS: they look like the good pullback "
            "pattern but the setup failed. Learn to spot the difference. A trap often "
            "has a genuine breakdown under the surface, not just a pullback.")


def call_llm(system, user):
    payload = {"model": MODEL,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.0, "max_tokens": 120, "stream": False}
    r = requests.post(URL, json=payload, timeout=120)
    text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        d = json.loads(m.group(0))
        return bool(d.get("take")), d.get("reason", "")
    except Exception:
        return None, text[:80]


def main():
    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, [s for s in data if s != REGIME_SYM])
    cands = []
    for a, b in FOLDS:
        sub = slice_aligned(al, a, b)
        cands += collect_candidates(sub[0], sub[1], sub[2], sub[3], base)
    rng = random.Random(SEED)
    cands = add_synthetic_traps(cands, rng)

    winners = [c for c in cands if c["fwd"] > 0]
    losers = [c for c in cands if c["fwd"] <= 0]
    real = sum(1 for c in cands if not c.get("synthetic_trap"))
    print(f"[trap] {len(cands)} signals ({real} real + {len(cands)-real} synthetic traps)")
    print(f"[trap] winners: {len(winners)} ({len(winners)/len(cands):.0%}), "
          f"losers/traps: {len(losers)} ({len(losers)/len(cands):.0%})")

    lessons = build_lessons(cands)
    all_mean = statistics.mean(c["fwd"] for c in cands)
    print(f"[trap] all-candidates mean forward: {all_mean:+.2%}  <- the rubber-stamp bar")

    verdicts = []
    for i, c in enumerate(cands):
        take, reason = call_llm(SYSTEM, lessons + "\n\n---\n\nJudge this signal:\n"
                                + c["ctx"] + "\n\nTake this long entry?")
        verdicts.append({**{k: c.get(k, False) for k in ("sym", "date", "fwd", "synthetic_trap")},
                         "take": take, "reason": reason})
        mark = "TRAP" if c.get("synthetic_trap") else ("lose" if c["fwd"] <= 0 else "win ")
        print(f"[trap] {i+1}/{len(cands)} {c['sym']} fwd={c['fwd']:+.1%} [{mark}] take={take}")

    kept = [v for v in verdicts if v["take"] is True]
    kept_mean = statistics.mean(v["fwd"] for v in kept) if kept else 0.0
    # discrimination: kept mean above all-mean by a real margin (>= +1%/fwd)
    margin = kept_mean - all_mean
    pass_gate = margin >= 0.01
    # also require the model didn't just take everything
    took_all = len(kept) / len(verdicts) > 0.95
    traps_taken = sum(1 for v in verdicts if v["take"] and v["fwd"] <= 0)
    print(f"\n=== TRAP TEST ===")
    print(f"  all-mean:        {all_mean:+.2%} ({len(verdicts)} signals)")
    print(f"  kept-mean:       {kept_mean:+.2%} ({len(kept)} kept)")
    print(f"  discrimination:  {margin:+.2%} (bar: +1.0%)")
    print(f"  traps taken:     {traps_taken}/{len(losers)}  (rubber-stamp: {took_all})")
    print(f"  GATE: {'PASS - real discrimination' if pass_gate and not took_all else 'FAIL'}"
          f"{' (rubber-stamp)' if took_all else ''}")
    out = PROJECT / "data" / "research_gate" / "trap_test.json"
    out.write_text(json.dumps({"n": len(verdicts), "all_mean": all_mean,
                               "kept_mean": kept_mean, "margin": margin,
                               "traps_taken": traps_taken, "pass": pass_gate and not took_all,
                               "verdicts": verdicts}, indent=1, default=str))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
