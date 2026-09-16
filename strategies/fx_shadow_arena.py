"""Bounded, paper-only arena for FX candidate policies.

The arena evaluates candidates against one immutable daily feature panel.  A
candidate sees only the feature row and point-in-time metadata; ``fwd1`` (the
next-period outcome) is kept out of its input and is attached only after the
vote is produced.  This module never imports an exchange or an order writer.

Candidate contract::

    def policy(row: Mapping[str, object]) -> Mapping[str, object]:
        return {"action": "BUY"|"SELL"|"HOLD", "conviction": 0..1}

The output is an explicitly paper-labelled JSON document.  It is safe to use
on live data because it has no execution path.
"""

from __future__ import annotations

import argparse
import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np


ACTIONS = frozenset({"BUY", "SELL", "HOLD"})
Policy = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class Candidate:
    name: str
    policy: Policy


def _as_action(value: object) -> str:
    action = str(value or "HOLD").upper()
    if action not in ACTIONS:
        raise ValueError(f"invalid action {action!r}; expected BUY, SELL, or HOLD")
    return action


def _vote(policy: Policy, row: Mapping[str, object]) -> dict:
    raw = dict(policy(row))
    action = _as_action(raw.get("action"))
    conviction = float(raw.get("conviction", raw.get("score", 0.0)))
    if not np.isfinite(conviction) or not 0.0 <= conviction <= 1.0:
        raise ValueError("conviction must be finite and between 0 and 1")
    return {"action": action, "conviction": conviction}


def _summary(scored: Sequence[dict]) -> dict:
    if not scored:
        return {"n": 0, "mean_outcome": None, "accuracy": None,
                "total_return": 0.0, "buy": 0, "sell": 0, "hold": 0}
    return {
        "n": len(scored),
        "mean_outcome": round(float(np.mean([x["outcome"] for x in scored])), 8),
        "accuracy": round(float(np.mean([x["correct"] for x in scored])), 6),
        "total_return": round(float(sum(x["strategy_return"] for x in scored)), 8),
        "buy": sum(x["action"] == "BUY" for x in scored),
        "sell": sum(x["action"] == "SELL" for x in scored),
        "hold": sum(x["action"] == "HOLD" for x in scored),
    }


def run_arena(panel: Mapping[str, np.ndarray], candidates: Sequence[Candidate],
              *, hold_band_pct: float = 0.05) -> dict:
    """Run all candidates on the same panel and return votes, scores, ranking.

    ``panel`` must contain ``features``, ``feature_names``, ``date``,
    ``pair_idx`` and ``fwd1``.  Labels are read only after each policy returns.
    Rows whose label is not finite are skipped.  No input row exposes labels,
    preventing accidental lookahead in candidate code.
    """
    required = {"features", "feature_names", "date", "pair_idx", "fwd1"}
    missing = required.difference(panel)
    if missing:
        raise ValueError(f"panel missing keys: {sorted(missing)}")
    X = np.asarray(panel["features"])
    dates, pairs, fwd = (np.asarray(panel[k]) for k in ("date", "pair_idx", "fwd1"))
    names = [str(x) for x in np.asarray(panel["feature_names"]).tolist()]
    if X.ndim != 2 or X.shape[1] != len(names):
        raise ValueError("features must be a 2-D array matching feature_names")
    if not (len(X) == len(dates) == len(pairs) == len(fwd)):
        raise ValueError("panel arrays must have equal row counts")

    scored_by_name = {c.name: [] for c in candidates}
    votes = []
    for i in range(len(X)):
        if not np.isfinite(fwd[i]):
            continue
        # Copy values into a plain mapping; candidates cannot mutate the panel.
        row = {"features": dict(zip(names, X[i].astype(float))),
               "date": int(dates[i]), "pair_idx": int(pairs[i])}
        row["feature_names"] = tuple(names)
        for candidate in candidates:
            vote = _vote(candidate.policy, row)
            ret = float(fwd[i])
            action = vote["action"]
            signed = ret if action == "BUY" else -ret if action == "SELL" else 0.0
            correct = (ret > 0 if action == "BUY" else ret < 0
                       if action == "SELL" else abs(ret * 100) <= hold_band_pct)
            result = {"candidate": candidate.name, "date": int(dates[i]),
                      "pair_idx": int(pairs[i]), **vote,
                      "next_return": ret, "strategy_return": signed,
                      "correct": bool(correct),
                      "outcome": (vote["conviction"] if correct else -vote["conviction"])}
            scored_by_name[candidate.name].append(result)
            votes.append(result)
    ranking = sorted(({"candidate": n, **_summary(rows)}
                      for n, rows in scored_by_name.items()),
                     key=lambda x: (x["total_return"], x["mean_outcome"] or -np.inf),
                     reverse=True)
    return {"paper_only": True, "n_rows": len(X), "n_votes": len(votes),
            "votes": votes, "ranking": ranking}


def write_result(result: Mapping[str, object], path: Path) -> None:
    """Write only an arena result; refuse known execution/state destinations."""
    path = Path(path)
    forbidden = {"fx_ledger.jsonl", "fx_state.json", "epoch_registry.json"}
    if path.name in forbidden or "oanda" in path.name.lower():
        raise ValueError(f"refusing potentially live output path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def load_policy(spec: str) -> Candidate:
    module_name, sep, function_name = spec.partition(":")
    if not sep:
        raise ValueError("candidate must be MODULE:FUNCTION")
    fn = getattr(importlib.import_module(module_name), function_name)
    if not callable(fn):
        raise ValueError(f"candidate is not callable: {spec}")
    return Candidate(spec, fn)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run paper-only FX shadow arena")
    ap.add_argument("--panel", required=True, help=".npz causal feature panel")
    ap.add_argument("--candidate", action="append", required=True,
                    help="candidate MODULE:FUNCTION (repeatable)")
    ap.add_argument("--out", required=True, help="paper result JSON path")
    args = ap.parse_args(argv)
    with np.load(args.panel, allow_pickle=False) as z:
        panel = {k: z[k] for k in z.files}
    result = run_arena(panel, [load_policy(x) for x in args.candidate])
    write_result(result, Path(args.out))
    print(json.dumps({"paper_only": True, "n_votes": result["n_votes"],
                      "ranking": result["ranking"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
