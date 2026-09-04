#!/usr/bin/env python3
"""Export the research corpus + evidence-gate verdicts as training data.

The 0-promoted gate result is not waste — it is a LABELED research-judgment
dataset. This exporter turns papers + the 129 backlog features + the gate's
verdicts into:

- data/training/research_judgment_data.jsonl  — chat-format fine-tuning examples
  ("judge this rule"; the assistant response is the evidence gate's grounded
  verdict), so the successor model learns the gate's judgment.
- data/training/research_corpus.jsonl          — the 94-paper library in a
  training-friendly format (title/summary/categories).
- data/research/feature_verdicts.json          — per-feature verdict table
  (viable / needs_metric / nonsense) + metrics, for RAG and curriculum use.

Verdict mapping (gate-derived, the training label):
  encodable + promoted       -> viable
  encodable + rejected       -> viable (real rule; just didn't add marginal value)
  entry-signal / drawdown    -> viable (needs a different hook)
  exotic GARCH/sentiment/etc -> needs_metric (plausible, metric not in engine)
  exotic undefined metrics    -> nonsense (spectral/entropy/hallucinated)
  unmapped                   -> needs_metric
"""

import json
from pathlib import Path

from setup_search.feature_eval import parse_feature

PROJECT = Path(__file__).resolve().parent.parent
BACKLOG = PROJECT / "data" / "feature_backlog.json"
LIBRARY = PROJECT / "data" / "arxiv_library.json"
EVAL_REPORT = PROJECT / "data" / "research_gate" / "feature_eval_report.json"
TRAIN_DIR = PROJECT / "data" / "training"
OUT_JUDGMENT = TRAIN_DIR / "research_judgment_data.jsonl"
OUT_CORPUS = TRAIN_DIR / "research_corpus.jsonl"
OUT_VERDICTS = PROJECT / "data" / "research" / "feature_verdicts.json"

REAL_BUT_NO_METRIC = {"garch", "sentiment", "news", "covariance", "correlation",
                      "var", "cvar", "stochastic", "point process",
                      "optimal stopping", "macro", "fundamental", "earnings",
                      "inflation", "yield", "stress test"}
NONSENSE_METRICS = {"spectral", "entropy", "precision_audit", "filter_rejection",
                    "path_signature", "market information", "uncertainty",
                    "fractal", "wavelet", "signature", "attention", "transformer",
                    "embedding", "llm", "gpt"}


def verdict_label(c: dict, eval_by_id: dict) -> tuple:
    """Return (label, detail) for a classified feature."""
    if c["encodable"]:
        e = eval_by_id.get(c["id"])
        if e and e.get("promote"):
            return "viable", f"gate: promoted ({e.get('gate')})"
        return "viable", f"gate: testable but no marginal value ({c.get('gate')})"
    reason = c["reason"]
    if "entry-signal" in reason or "drawdown" in reason:
        return "viable", reason
    if "exotic metric" in reason:
        metric = reason.split("(")[-1].rstrip(")")
        if metric in REAL_BUT_NO_METRIC:
            return "needs_metric", f"plausible; requires {metric} metric"
        return "nonsense", f"undefined/hallucinated metric ({metric})"
    return "needs_metric", reason


def main():
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    backlog = json.loads(BACKLOG.read_text())["features"]
    library = json.loads(LIBRARY.read_text())["papers"]
    try:
        report = json.loads(EVAL_REPORT.read_text())
    except Exception:
        report = {}
    eval_by_id = {r["id"]: r for r in report.get("results", [])}

    verdicts = []
    n = {"viable": 0, "needs_metric": 0, "nonsense": 0}
    with open(OUT_JUDGMENT, "w") as fj, open(OUT_CORPUS, "w") as fc:
        for p in library:
            fc.write(json.dumps({
                "kind": "paper", "arxiv_id": p.get("id"),
                "title": p.get("title"), "summary": p.get("summary"),
                "categories": p.get("categories"), "published": p.get("published"),
            }) + "\n")

        for f in backlog:
            c = parse_feature(f)
            c["id"] = f.get("title", "?")
            c["rule"] = (f.get("rule", "") or "")
            label, detail = verdict_label(c, eval_by_id)
            n[label] += 1
            verdicts.append({
                "title": c["id"], "rule": c["rule"], "type": f.get("type", ""),
                "paper": f.get("paper_source", ""), "label": label, "detail": detail,
                "gate": c.get("gate"), "params": c.get("params"),
                "fields": f.get("fields", []), "multi_source": f.get("multi_source", False),
            })
            fj.write(json.dumps({"messages": [
                {"role": "system", "content":
                 "You are a research-judgment assistant for a trading AI. Given a "
                 "trading rule extracted from a finance paper, judge it as viable "
                 "(testable, plausible), needs_metric (plausible but requires a "
                 "metric not yet computable), or nonsense (undefined/hallucinated "
                 "metric). Be skeptical of undefined metrics."},
                {"role": "user", "content":
                 f"Paper: {f.get('paper_source', 'unknown')}\nRule: {c['rule']}\n"
                 f"Type: {f.get('type', '?')}\n\nClassify the rule."},
                {"role": "assistant", "content": f"{label}: {detail}"},
            ]}) + "\n")

    (OUT_VERDICTS).write_text(json.dumps({"verdicts": verdicts}, indent=1))
    print(f"[export] papers: {len(library)}, features: {len(verdicts)}")
    print(f"[export] labels: {n}")
    print(f"[export] -> {OUT_JUDGMENT}\n[export] -> {OUT_CORPUS}\n[export] -> {OUT_VERDICTS}")


if __name__ == "__main__":
    main()
