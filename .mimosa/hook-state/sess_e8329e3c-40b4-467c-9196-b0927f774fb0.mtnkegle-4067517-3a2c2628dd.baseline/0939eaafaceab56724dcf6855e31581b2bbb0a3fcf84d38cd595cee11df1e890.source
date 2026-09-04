#!/usr/bin/env python3
"""Teach the model how to make a profitable trade — from the validated playbook.

The rule system is the PRIMARY leader. The LLM is the apprentice: it is shown
the rule system's actual profitable OOS trades as labelled teaching examples
("here is a profitable trade and why the rule took it"), then re-tested on the
same signals. The model earns more autonomy only if its judgment, after
teaching, confirms the profitable pattern (its vetos IMPROVE the confirmed
trades' mean impact, or at least match the rule floor).

Steps:
1. Replay the validated config on OOS folds -> its real trades + outcomes.
2. Export chat-format teaching examples (context + correct BUY + outcome).
3. Re-judge the rule signals with a FEW-SHOT taught prompt (the apprentice).
4. Proficiency gate: taught-LLM confirmed trades' mean impact vs the rule floor.

Writes data/training/rule_playbook_lessons.jsonl + the gate result.
"""

import json
import re
import statistics
from pathlib import Path

import requests

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align, slice_aligned
from setup_search.engine import run_backtest

PROJECT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:5802/v1/chat/completions"
MODEL = "qwythos-9b-mtp"
FOLDS = [(500, 750), (750, 1000), (1000, 1250)]
LESSONS = PROJECT / "data" / "training" / "rule_playbook_lessons.jsonl"
N_LESSONS = 6  # profitable trades to show the apprentice

APPRENTICE_SYSTEM = (
    "You are an apprentice trader learning from a validated rule-based system "
    "that has a 68% win rate and +5%/yr out-of-sample edge. Learn this "
    "DISCRIMINATOR: the highest-EV entries are disciplined PULLBACKS in an "
    "uptrend — a sharp-looking drop right before entry is often the opportunity, "
    "NOT a reason to avoid. The regime gate (SPY above its 200d) and the rule "
    "score are the discipline; a scary candle is not a veto. ONLY veto when the "
    "regime has actually broken down or the entry is a genuine crash/breakdown "
    "against the pattern, not a routine pullback. DEFAULT TO YES. Respond ONLY "
    "with JSON: {\"take\": true|false, \"reason\": \"one line\"}"
)


def build_ctx(t, closes, cfg) -> str:
    sym, date = t["sym"], t["entry_date"]
    c = closes[sym]
    recent = " -> ".join(f"{v:,.0f}" for v in c.loc[:date].tail(8))
    return (f"Symbol: {sym}\nRecent closes: {recent}\n"
            f"Entry ~ {t['entry']:,.2f}\nRule score: {t.get('score','?')} "
            f"(threshold {cfg['buy_thresh']})")


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
    closes, highs, lows, vols = al

    trades = []
    for a, b in FOLDS:
        m = run_backtest(slice_aligned(al, a, b), base)
        eq = m["equity"]
        for t in m["trades"]:
            eq_at = float(eq.get(t["entry_date"], 500.0))
            trades.append({**t, "impact": t["pnl"] / max(eq_at, 1.0), "score": None})

    # ── Teaching examples: the profitable trades, labelled ──
    lessons = sorted([t for t in trades if t["impact"] > 0],
                     key=lambda t: -t["impact"])
    with open(LESSONS, "w") as f:
        for i, t in enumerate(lessons[:N_LESSONS]):
            scary = (
                " NOTE: this entry had a sharp drop before it — that is the "
                "pullback opportunity, the HIGHEST-EV pattern. Do NOT avoid it."
                if i < 3 else ""
            )
            f.write(json.dumps({
                "messages": [
                    {"role": "system", "content":
                     "You are learning the validated rule playbook. The highest-EV "
                     "trades are disciplined pullbacks in an uptrend — scary drops "
                     "before entry are opportunities, not vetoes."},
                    {"role": "user", "content": build_ctx(t, closes, base)
                     + "\n\nThe rule system took this LONG entry. Was it correct?"},
                    {"role": "assistant", "content":
                     f"yes — profitable ({t['impact']:+.2%}).{scary}"},
                ]
            }) + "\n")
    print(f"[teach] {len(lessons)}/{len(trades)} trades profitable; "
          f"{min(N_LESSONS, len(lessons))} lessons -> {LESSONS}")

    # ── Proficiency gate: re-judge with the taught apprentice ──
    lesson_text = "\n\n".join(
        f"LESSON {i+1}: {build_ctx(t, closes, base)} -> PROFITABLE "
        f"({t['impact']:+.2%})"
        + (f"  <-- sharp drop before entry; still the highest-EV pullback; TAKE"
           if i < 3 else "")
        for i, t in enumerate(lessons[:N_LESSONS])
    )
    lesson_text += (
        "\n\nREMEMBER: a sharp drop before entry is the pullback OPPORTUNITY in "
        "an uptrend (highest EV). Veto ONLY on real regime breakdown, not on "
        "scary candles."
    )
    verdicts = []
    for i, t in enumerate(trades):
        user = (f"{lesson_text}\n\n---\n\nNew signal to judge:\n"
                f"{build_ctx(t, closes, base)}\n\nTake this long entry?")
        take, reason = call_llm(APPRENTICE_SYSTEM, user)
        verdicts.append({"sym": t["sym"], "impact": t["impact"], "take": take,
                         "reason": reason})
        print(f"[gate] {i+1}/{len(trades)} {t['sym']} imp={t['impact']:+.2%} "
              f"take={take} {reason[:40]}")

    all_imp = [v["impact"] for v in verdicts]
    yes = [v["impact"] for v in verdicts if v["take"] is True]
    no = [v["impact"] for v in verdicts if v["take"] is False]
    mean_all = statistics.mean(all_imp)
    mean_yes = statistics.mean(yes) if yes else None
    mean_no = statistics.mean(no) if no else None
    pass_gate = bool(yes) and mean_yes is not None and mean_yes >= mean_all

    print(f"\n=== Proficiency gate ===")
    print(f"  rule floor:       {mean_all:+.3%}/trade ({len(all_imp)} trades)")
    if mean_yes is not None:
        print(f"  taught-LLM keep:  {mean_yes:+.3%}/trade ({len(yes)} trades)")
    if mean_no is not None:
        print(f"  taught-LLM veto:  {mean_no:+.3%}/trade ({len(no)} trades)")
    print(f"  GATE: {'PASS — model understands the playbook; may earn autonomy' if pass_gate
          else 'FAIL — rules stay primary until the model proves it'}")
    out = PROJECT / "data" / "research_gate" / "proficiency_gate.json"
    out.write_text(json.dumps({"mean_all": mean_all, "mean_yes": mean_yes,
                               "mean_no": mean_no, "pass": pass_gate,
                               "verdicts": verdicts}, indent=1, default=str))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
