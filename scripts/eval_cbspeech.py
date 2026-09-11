#!/usr/bin/env python3
"""T7 — CB-speech eval harness (GLM plan §6, gates 1-2).

Evaluates a fine-tuned Warden model against the base model on holdout
(2025-26) speeches:
  gate 1 (offline holdout): directional hit-rate of the implied bias vs the
    +5d outcome, JSON contract compliance, grounding (no computed numbers).
  gate 2 (policy replay): feed each doc's expectation through the Warden's
    score rule (HARSHNESS/PROBATE/ESCALATE) and report score_pct drift.

The model under test is the llama-server on --port (default :5802). To compare
base vs tuned, point at each and diff.

Usage: .venv/bin/python3 scripts/eval_cbspeech.py \
         --holdout /home/mrc/opentrader-data/feeds/cbspeeches/corpus_labeled.jsonl \
         [--port 5802] [--year-ge 2025]
"""

import argparse
import json
import re
import urllib.request

HARSHNESS = 1.0  # must match fx_warden.py


def _model(port, base):
    return f"http://127.0.0.1:{port}/v1/chat/completions"


def _call(llm, system, user, max_tokens=500):
    body = json.dumps({"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}],
                       "max_tokens": max_tokens, "temperature": 0.2}).encode()
    req = urllib.request.Request(llm, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


SYSTEM = ("You are the Warden: a bounded monitor for an FX practice account. "
          "Given a central-bank speech and a stress snapshot, set the EXPECTED "
          "weekly P&L (account %, e.g. 0.1 = +0.1%) for the speech's currency. "
          "Return STRICT JSON only: "
          '{"expected_pnl_pct": <float>, "direction": "long_bias|short_bias|flat", '
          '"rationale": "<one sentence>"}. CITE ONLY the numbers given; never '
          "compute or invent a percentage.")


def _parse(out):
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _grounded(out, doc):
    """gate 1c: the model must not invent a % not present in the doc/stress."""
    claims = re.findall(r"-?\d+\.?\d*\s*%", str(out))
    allowed = {str(doc.get(k)) for k in ("ret_1d", "ret_5d") if doc.get(k) is not None}
    return all(any(str(round(float(c.replace("%", "")), 6)).startswith(a[:6])
                     for a in allowed) if allowed else True for c in claims)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--port", type=int, default=5802)
    ap.add_argument("--year-ge", type=int, default=2025)
    ap.add_argument("--year-lt", type=int, default=None,
                    help="optional upper bound (exclusive) on doc year, e.g. 2025 for a 2023-24 val window")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    docs = [json.loads(l) for l in open(a.holdout) if l.strip()]
    docs = [d for d in docs if str(d.get("date", ""))[:4] >= str(a.year_ge)
            and (a.year_lt is None or str(d.get("date", ""))[:4] < str(a.year_lt))
            and d.get("ret_5d") is not None]
    if a.limit:
        docs = docs[:a.limit]

    llm = _model(a.port, False)
    hits = json_ok = grounded = 0
    score_base = score_tuned = 0.0
    for d in docs:
        user = (f"bank: {d.get('bank')} | date: {d.get('date')} | "
                f"speech: {(d.get('title') or '')[:200]} | text: {(d.get('text') or '')[:800]} | "
                f"stress: { {k: d.get(k) for k in d if k.startswith('stress_')} }")
        out = _call(llm, SYSTEM, user)
        p = _parse(out)
        if p is None:
            continue
        json_ok += 1
        grounded += 1 if _grounded(out, d) else 0
        exp = float(p.get("expected_pnl_pct", 0.0) or 0.0)
        actual = d.get("ret_5d", 0.0)
        # directional hit: sign(expectation) matches sign(5d outcome)
        if (exp > 0 and actual > 0) or (exp < 0 and actual < 0) or (exp == 0 and abs(actual) < 0.001):
            hits += 1
        # gate-2 proxy: score rule on the (expectation, actual) pair
        miss = 100.0 * actual - exp  # both in % terms
        score_tuned += miss if miss >= 0 else miss - HARSHNESS * abs(exp)

    n = json_ok
    if n == 0:
        print("[eval] no parseable outputs — model unavailable or malformed")
        return
    print(f"holdout docs (>= {a.year_ge}): {len(docs)}; parseable: {n}")
    print(f"gate1 JSON contract compliance: {json_ok}/{len(docs)} = {json_ok/len(docs):.2%}")
    print(f"gate1 grounding (no invented %): {grounded}/{n} = {grounded/n:.2%}")
    print(f"gate1 directional hit-rate (sign vs +5d): {hits}/{n} = {hits/n:.2%}")
    print(f"gate2 policy-replay score sum (this model): {score_tuned:+.3f}")


if __name__ == "__main__":
    main()
