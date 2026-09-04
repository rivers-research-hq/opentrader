#!/usr/bin/env python3
"""Eval probe: does the model agree with the evidence gate's judgment?

Samples a balanced set of features from feature_verdicts.json, asks the LLM
(qwythos on GPU1, the successor's reasoning stand-in) to classify each rule as
viable / needs_metric / nonsense, and compares to the gate-derived label.
Produces an agreement score + confusion matrix — the research-judgment
benchmark the lifecycle uses when Ptolemy trains.

Usage: python3 -m setup_search.research_probe [--samples-per-class N]
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parent.parent
VERDICTS = PROJECT / "data" / "research" / "feature_verdicts.json"
URL = "http://127.0.0.1:5802/v1/chat/completions"
MODEL = "qwythos-9b-mtp"

SYSTEM = (
    "You are a research-judgment assistant for a trading AI. Given a trading rule "
    "extracted from a finance paper, classify it as exactly one of: viable "
    "(testable, plausible), needs_metric (plausible but requires a metric not yet "
    "computable), or nonsense (undefined/hallucinated metric). Be skeptical of "
    "undefined metrics. Respond ONLY with a JSON object: "
    '{"label": "viable|needs_metric|nonsense", "reason": "one line"}.'
)


def classify(model_client, rule, paper, ftype):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
             f"Paper: {paper}\nRule: {rule}\nType: {ftype}\n\nClassify the rule."},
        ],
        "temperature": 0.0,
        "max_tokens": 120,
        "stream": False,
    }
    resp = model_client.post(URL, json=payload, timeout=120)
    text = resp.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None, text[:80]
    try:
        d = json.loads(m.group(0))
        return d.get("label"), d.get("reason", "")
    except Exception:
        return None, text[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples-per-class", type=int, default=6)
    args = ap.parse_args()

    verdicts = json.loads(VERDICTS.read_text())["verdicts"]
    by_label = {}
    for v in verdicts:
        by_label.setdefault(v["label"], []).append(v)
    sample = []
    rng = random.Random(7)
    for label, items in by_label.items():
        rng.shuffle(items)
        sample.extend(items[: args.samples_per_class])
    rng.shuffle(sample)

    client = requests.Session()
    conf = {"viable": {"viable": 0, "needs_metric": 0, "nonsense": 0},
            "needs_metric": {"viable": 0, "needs_metric": 0, "nonsense": 0},
            "nonsense": {"viable": 0, "needs_metric": 0, "nonsense": 0}}
    agree = 0
    rows = []
    for v in sample:
        pred, reason = classify(client, v["rule"], v["paper"], v["type"])
        actual = v["label"]
        if pred in conf:
            conf[actual][pred] += 1
            if pred == actual:
                agree += 1
        rows.append({"rule": v["rule"][:90], "actual": actual, "pred": pred,
                     "reason": (reason or "")[:80]})

    total = len(sample)
    print(f"[probe] {total} features sampled ({args.samples_per_class}/class)\n")
    print(f"[probe] agreement: {agree}/{total} = {agree/total:.0%}\n")
    print("confusion (actual -> predicted):")
    print(f"  {'actual':<12} {'viable':>8} {'needs_metric':>13} {'nonsense':>8}")
    for a in conf:
        c = conf[a]
        print(f"  {a:<12} {c['viable']:>8} {c['needs_metric']:>13} {c['nonsense']:>8}")
    print("\nper-example:")
    for r in rows:
        mark = "OK " if r["pred"] == r["actual"] else "XX "
        print(f"  {mark}[{r['actual']:>12}->{str(r['pred']):<12}] {r['rule']}")


if __name__ == "__main__":
    main()
