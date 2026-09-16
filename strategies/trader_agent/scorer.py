"""Score paper votes against next-period close-to-close returns."""
import json
from pathlib import Path


def score_vote(vote: dict, next_return_pct: float, hold_band_pct: float = 0.05) -> dict:
    """Score one vote. Conviction scales outcome; HOLD wins inside the band."""
    action, c = vote.get("action", "HOLD"), float(vote.get("conviction", 0))
    if action == "BUY": correct = next_return_pct > 0
    elif action == "SELL": correct = next_return_pct < 0
    else: correct = abs(next_return_pct) <= hold_band_pct
    outcome = c if correct else -c
    return {**vote, "next_return_pct": next_return_pct,
            "correct": correct, "outcome": round(outcome, 6)}


def summarize(scored: list[dict]) -> dict:
    if not scored: return {"n": 0, "mean_outcome": None, "accuracy": None}
    return {"n": len(scored),
            "mean_outcome": round(sum(x["outcome"] for x in scored) / len(scored), 6),
            "accuracy": round(sum(x["correct"] for x in scored) / len(scored), 4),
            "buy": sum(x["action"] == "BUY" for x in scored),
            "sell": sum(x["action"] == "SELL" for x in scored),
            "hold": sum(x["action"] == "HOLD" for x in scored)}
