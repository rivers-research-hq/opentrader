#!/usr/bin/env python3
"""Rule+LLM A/B: does the LLM's judgment add value on the rule config's signals?

Replays the validated rule config on the OOS folds, collects its real trades,
then asks the LLM (qwythos) to confirm/reject each entry given a technical +
regime context. Compares:
  pure-rule      : mean portfolio impact of all OOS trades
  rule+LLM       : mean impact of the trades the LLM confirms
  LLM-veto value : mean impact of the trades the LLM rejects (what the veto
                   would have avoided)
This is the honest measurement of whether weaponizing the playbook with the
LLM adds alpha, degrades it, or is neutral.
"""

import json
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

SYSTEM = (
    "You are a conservative trader reviewing an entry signal produced by a "
    "validated rule-based system. Given the symbol, recent closes, the rule's "
    "technical score, and the market regime, decide whether to take this long "
    "entry. Be disciplined: reject entries that look overbought, extended, or "
    "against the regime. Respond ONLY with a JSON object: "
    '{"take": true|false, "reason": "one line"}'
)


def build_context(t, closes, spy, cfg) -> str:
    sym, date = t["sym"], t["entry_date"]
    c = closes[sym]
    recent = " -> ".join(f"{v:,.0f}" for v in c.loc[:date].tail(8))
    ma50 = c.loc[:date].tail(50).mean()
    spy_trend = "n/a"
    if spy is not None and date in spy.index:
        spy_trend = "up" if spy[date] > spy.loc[:date].tail(200).mean() else "down"
    return (
        f"Symbol: {sym}\nRegime (SPY vs 200d): {spy_trend}\n"
        f"Recent closes: {recent}\n"
        f"50d mean: {ma50:,.0f} | entry ~ {t['entry']:,.2f}\n"
        f"Rule score: {t.get('score', '?')} (threshold {cfg['buy_thresh']})"
    )


def judge(t, closes, spy, cfg):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": build_context(t, closes, spy, cfg)
             + "\n\nTake this long entry? Respond with JSON."},
        ],
        "temperature": 0.0,
        "max_tokens": 120,
        "stream": False,
    }
    r = requests.post(URL, json=payload, timeout=120)
    text = r.json()["choices"][0]["message"]["content"]
    import re
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
    spy = closes.get(REGIME_SYM)

    trades = []
    for a, b in FOLDS:
        m = run_backtest(slice_aligned(al, a, b), base)
        eq = m["equity"]
        for t in m["trades"]:
            eq_at = float(eq.get(t["entry_date"], 500.0))
            trades.append({**t, "impact": t["pnl"] / max(eq_at, 1.0),
                           "score": None})
    print(f"[ab] {len(trades)} OOS trades")

    verdicts = []
    for i, t in enumerate(trades):
        take, reason = judge(t, closes, spy, base)
        verdicts.append({"sym": t["sym"], "date": str(t["entry_date"]),
                         "impact": t["impact"], "pnl_pct": t["pnl_pct"],
                         "take": take, "reason": reason})
        print(f"[ab] {i+1}/{len(trades)} {t['sym']} @ {t['entry_date']} "
              f"imp={t['impact']:+.2%} take={take} {reason[:40]}")

    all_imp = [v["impact"] for v in verdicts]
    yes = [v["impact"] for v in verdicts if v["take"] is True]
    no = [v["impact"] for v in verdicts if v["take"] is False]
    print(f"\n=== A/B result ===")
    print(f"  pure-rule ({len(all_imp)} trades):    mean impact {statistics.mean(all_imp):+.3%}")
    if yes:
        print(f"  rule+LLM  ({len(yes)} confirmed):    mean impact {statistics.mean(yes):+.3%}")
    if no:
        print(f"  LLM-veto  ({len(no)} rejected):      mean impact {statistics.mean(no):+.3%}  <- what the veto avoids")
    gain = (statistics.mean(yes) - statistics.mean(all_imp)) if yes else 0.0
    print(f"\n  LLM adds: {gain:+.3%} per trade {'(positive)' if gain > 0 else '(negative/neutral)'}")

    out = PROJECT / "data" / "research_gate" / "rule_llm_ab.json"
    out.write_text(json.dumps({"n": len(verdicts), "mean_all": statistics.mean(all_imp),
                               "mean_yes": statistics.mean(yes) if yes else None,
                               "mean_no": statistics.mean(no) if no else None,
                               "verdicts": verdicts}, indent=1, default=str))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
