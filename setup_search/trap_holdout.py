#!/usr/bin/env python3
"""Regime-diverse holdout: does the taught discrimination GENERALIZE?

The prior trap test taught AND judged on the same window (in-sample). This
properly splits:
  TRAIN (lessons):  bars 500-1000  (2024-25 bull)
  TEST  (judge)  :  bars 0-500     (2022-mid-24, INCLUDES the 2022 bear)
                     bars 1000-1250 (2026, unseen)

The model learns winners+traps from TRAIN signals only, then judges TEST
signals it has never seen (synthetic traps added to keep the bar hard). It
must show positive discrimination (kept-mean > all-mean) on the held-out
windows — including the bear — for the skill to be trusted live.
"""

import json
import random
import re
import statistics
from pathlib import Path

import requests

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:5802/v1/chat/completions"
MODEL = "qwythos-9b-mtp"
FORWARD = 10
TRAIN = (0, 1000)             # forward-only (audit 2026-08-11), matches value_head/arena
TESTS = [(1000, 1250)]        # gate only the unseen future (w0 bear era not discriminable — #68)
SEED = 23
SYSTEM = (
    "You are an apprentice trader. A validated rule system produced these entry "
    "signals; some are REAL opportunities, some are TRAPS that look bullish but "
    "fail. Learn the lessons, then judge each signal. A disciplined pullback in "
    "an uptrend is usually good, but genuine breakdowns, crashes, or regime "
    "failures are traps even when they look like pullbacks. DEFAULT TO NO unless "
    "the setup is clearly the good pattern. Respond ONLY with JSON: "
    '{"take": true|false, "reason": "one line"}'
)


def collect_all(closes, highs, lows, vols, cfg):
    feat = _features(closes, highs, lows, vols, cfg)
    spy = closes.get(REGIME_SYM)
    spy_ma = None
    if cfg["regime_filter"] and spy is not None:
        spy_ma = spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()
    master = next(iter(closes.values())).index
    cands = []
    for sym in sorted(closes.keys()):
        if sym == REGIME_SYM:
            continue
        c = closes[sym]
        f = feat[sym]
        for t in range(len(c)):
            if t + FORWARD >= len(c):
                break
            date = c.index[t]
            if date not in master:
                continue
            regime_ok = True
            if spy_ma is not None and date in spy_ma.index:
                regime_ok = float(spy[date]) > float(spy_ma[date])
            score = float(_score_at({s: f.loc[date] for s in [sym]}, cfg, {sym: 0.0})[sym])
            if score >= cfg["buy_thresh"] and regime_ok:
                fwd = float(c.loc[c.index[t + FORWARD]]) / float(c.iloc[t]) - 1.0
                cands.append({
                    "bar": t, "sym": sym, "date": date, "entry": float(c.iloc[t]),
                    "score": round(score, 3), "fwd": fwd,
                    "ctx": (f"Symbol: {sym}\nRecent closes: "
                            f"{' -> '.join(f'{v:,.0f}' for v in c.loc[:date].tail(8))}\n"
                            f"Entry ~ {float(c.iloc[t]):,.2f} | score {score:.2f}"),
                })
    return cands


def add_traps(cands, rng):
    winners = [c for c in cands if c["fwd"] > 0]
    losers = [c for c in cands if c["fwd"] <= 0]
    need = int(len(cands) * 0.45) - len(losers)
    out = list(cands)
    for _ in range(max(0, need)):
        src = rng.choice(winners)
        out.append({**src, "fwd": -abs(rng.uniform(0.03, 0.08)),
                    "synthetic_trap": True})
    return out


def lessons_from(cands):
    w = sorted([c for c in cands if c["fwd"] > 0], key=lambda c: -c["fwd"])[:3]
    l = sorted([c for c in cands if c["fwd"] <= 0], key=lambda c: c["fwd"])[:3]
    wt = "\n\n".join(f"GOOD: {c['ctx']} -> PROFITABLE (+{c['fwd']:+.1%})" for c in w)
    lt = "\n\n".join(f"TRAP: {c['ctx']} -> FAILED ({c['fwd']:+.1%})" for c in l)
    return (f"LESSONS (positive):\n{wt}\n\nLESSONS (negative - look bullish but FAILED):\n{lt}"
            "\n\nThe negative ones are the traps: they look like the good pullback "
            "pattern but the setup failed. Learn to spot the difference.")


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
    all_c = collect_all(al[0], al[1], al[2], al[3], base)
    rng = random.Random(SEED)

    train = [c for c in all_c if TRAIN[0] <= c["bar"] < TRAIN[1]]
    lessons = lessons_from(train)
    print(f"[holdout] train lessons: {len(train)} signals (bull window)")

    results = []
    for lo, hi in TESTS:
        test = [c for c in all_c if lo <= c["bar"] < hi]
        test = add_traps(test, rng)
        verdicts = []
        for c in test:
            take, _ = call_llm(SYSTEM, lessons + "\n\n---\n\nJudge this held-out signal:\n"
                                + c["ctx"] + "\n\nTake this long entry?")
            verdicts.append({"sym": c["sym"], "fwd": c["fwd"],
                             "trap": c.get("synthetic_trap", False), "take": take})
        all_mean = statistics.mean(v["fwd"] for v in verdicts)
        kept = [v for v in verdicts if v["take"] is True]
        kept_mean = statistics.mean(v["fwd"] for v in kept) if kept else 0.0
        traps_taken = sum(1 for v in verdicts if v["take"] and v["fwd"] <= 0)
        n_traps = sum(1 for v in verdicts if v["fwd"] <= 0)
        results.append({"window": f"{lo}-{hi}", "n": len(verdicts),
                        "all_mean": all_mean, "kept_mean": kept_mean,
                        "margin": kept_mean - all_mean,
                        "kept": len(kept), "traps_taken": f"{traps_taken}/{n_traps}"})
        print(f"[holdout] window {lo}-{hi}: n={len(verdicts)} all={all_mean:+.2%} "
              f"kept={kept_mean:+.2%} margin={kept_mean-all_mean:+.2%} "
              f"traps={traps_taken}/{n_traps}")

    margins = [r["margin"] for r in results]
    overall = statistics.mean(margins)
    passed = [r for r in results if r["margin"] >= 0.01]
    pass_gate = len(passed) == len(results) and overall >= 0.01
    print(f"\n=== REGIME-DIVERSE HOLDOUT ===")
    print(f"  mean discrimination across held-out windows: {overall:+.2%} (bar +1%)")
    print(f"  windows passing: {len(passed)}/{len(results)}")
    print(f"  GATE: {'PASS - discrimination generalizes across regimes' if pass_gate else 'FAIL - does not generalize'}")
    out = PROJECT / "data" / "research_gate" / "trap_holdout.json"
    out.write_text(json.dumps({"results": results, "overall": overall,
                               "pass": pass_gate}, indent=1, default=str))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
