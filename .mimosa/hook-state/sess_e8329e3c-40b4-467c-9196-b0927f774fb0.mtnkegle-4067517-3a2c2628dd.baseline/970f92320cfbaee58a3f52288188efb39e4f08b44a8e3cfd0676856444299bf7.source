#!/usr/bin/env python3
"""LLM Scientist on GPU1 (qwythos-9b-mtp @ :5802) — reviews backtest feedback
and proposes the next candidate setups as JSON configs."""

import json
import re
import time
from typing import Dict, List, Optional

import requests

from setup_search.core import CONFIG_BOUNDS, DEFAULT_CONFIG

SCIENTIST_URL = "http://127.0.0.1:5802/v1/chat/completions"
SCIENTIST_MODEL = "qwythos-9b-mtp"
REQUEST_TIMEOUT = 120

_BOUNDS_TEXT = "\n".join(
    f"  {k}: range {lo}..{hi}" for k, (lo, hi) in sorted(CONFIG_BOUNDS.items())
)


def _build_prompt(history, best, objective_note) -> str:
    top = ""
    if best:
        top = (
            "CURRENT BEST (ACTIVE — this is the target to beat):\n"
            f"  config={json.dumps(best['config'])}\n"
            f"  metrics={best['summary']}  score={best['score']}\n"
        )
    recents = history[-12:]
    rec_text = ""
    if recents:
        rec_text = "RECENT RESULTS (config, score, summary):\n" + "\n".join(
            f"  [{r['iter']}] score={r['score']} {r['summary']}"
            for r in recents
        )
    return f"""You are a quantitative trading setup scientist. You are helping search
for the best long-only stock trading configuration for a $500 account with a
$0.35 fixed fee per side. Trades are simulated on daily bars over ~2 years
(501 bars, 16 symbols).

OBJECTIVE (higher is better):
{objective_note}

HARD RULES:
- A config producing FEWER THAN 8 TRADES is REJECTED and counts for nothing.
  Do NOT raise buy_thresh above ~1.0, do NOT set min_notional above ~$50, and
  do NOT set risk_pct below ~0.02. Zero-trade configs are wasted proposals.
- NEW BEST configs must also be POSITIVE on the most RECENT ~25% of the data
  (the validation window). Configs that only make money in the old part of the
  sample are overfit and get rejected. Prefer configs that trade moderately
  (15-150 trades), keep fees under ~10% of equity, and use the regime filter
  on — those generalized out-of-sample in our walk-forward test.
- The current best is ACTIVE (it trades); propose configs with comparable or
  higher activity (roughly 15-200 trades over the 2y span).
- Keep every value inside its stated range.

You tune this config (all values MUST stay inside the stated ranges):
{_BOUNDS_TEXT}

{top}
{rec_text}

Diagnose what the recent scores suggest (too much churn? fee bleed? too few
trades? bad drawdown? weak momentum timing?) and propose THREE new candidate
configs that are likely to score higher while REMAINING ACTIVE (>= 8 trades).
Mix exploitation (targeted mutations around the best) with exploration (novel
weight/threshold combos). Integer-valued params must be integers.

Respond with ONLY a JSON array of 3 objects, each:
[{{"reasoning": "1-2 sentences", "config": {{"...": ...}}}}]
"""


def _extract_json(text: str) -> Optional[List[Dict]]:
    text = text.strip()
    m = re.search(r"\[[\s\S]*\]", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, list):
                return obj
        except json.JSONDecodeError:
            pass
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def propose_configs(
    history: List[Dict],
    best: Optional[Dict],
    objective_note: str,
    max_retries: int = 2,
) -> List[Dict]:
    prompt = _build_prompt(history, best, objective_note)
    payload = {
        "model": SCIENTIST_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 1500,
        "stream": False,
    }
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                SCIENTIST_URL, json=payload, timeout=REQUEST_TIMEOUT
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            items = _extract_json(content)
            if items:
                out = []
                for it in items:
                    cfg = it.get("config") if isinstance(it, dict) else None
                    if isinstance(cfg, dict) and cfg:
                        out.append(
                            {"reasoning": it.get("reasoning", ""), "config": cfg}
                        )
                if out:
                    return out
        except Exception as e:
            print(f"[scientist] call error (attempt {attempt}): {e}")
            time.sleep(5)
    return []
