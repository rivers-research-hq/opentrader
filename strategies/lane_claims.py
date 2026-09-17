#!/usr/bin/env python3
"""lane_claims — conviction auction for the trained FX lanes (2026-09-09).

Human directive: lanes must not overlap; each pair goes to the lane with the
highest conviction for it. One netted OANDA account holds one net position
per instrument, so non-overlapping assignment is also what makes multi-lane
ownership safe on a single account.

Mechanism: at each lane run, the lane writes its per-pair conviction scores
(|model score| per pair) to data/fx_expert/claims_scores_<tag>.json. The
assignment (deterministic, recomputed by every lane from the same inputs):
each pair -> argmax conviction across lanes with a fresh score file (<26h).
Ties break in promoted order (g151 first). Claims persist in claims.json
until the next rebalance recomputes them. Non-owners are locked out.
"""

import json
import time
from pathlib import Path

WARDEN_DIR = Path(__file__).resolve().parent.parent / "data" / "fx_expert"
LANE_ORDER = ["fxexp-g151", "fxexp-g138", "fxexp-g137"]  # legacy; kept for compatibility, replaced by _lane_order() below


def _lane_order() -> list[str]:
    """Dynamic lane priority from lifecycle: most recently promoted first."""
    from strategies.expert_lifecycle import active_lanes, lifecycle_of
    lane_tags = []
    for eid in active_lanes():
        if not eid.startswith("fx-expert-"):
            continue
        tag = "fxexp-" + eid.replace("fx-expert-", "")
        lc = lifecycle_of(eid)
        changed = lc.get("lifecycle_changed", "") if lc else ""
        lane_tags.append((tag, changed))
    lane_tags.sort(key=lambda x: x[1], reverse=True)  # most recent first
    return [t[0] for t in lane_tags]
FRESH_S = 26 * 3600


def assign(all_scores, now=None):
    """all_scores: {tag: (scores, ts)} or {tag: {pair: score}}. Returns
    claims {pair: {"lane": tag, "score": s}} — deterministic argmax."""
    now = now or time.time()
    fresh = {}
    for tag, v in all_scores.items():
        scores, ts = v if isinstance(v, tuple) else (v, now)
        if now - ts <= FRESH_S and scores:
            fresh[tag] = (scores, ts)
    claims = {}
    for pair in sorted({p for scores, _ in fresh.values() for p in scores}):
        best_tag, best_score = None, None
        for tag in _lane_order():
            if tag not in fresh:
                continue
            s = fresh[tag][0].get(pair)
            if s is None:
                continue
            if best_score is None or abs(s) > abs(best_score):
                best_tag, best_score = tag, s
        if best_tag is not None:
            claims[pair] = {"lane": best_tag, "score": round(float(best_score), 4)}
    return claims


def write_scores(tag, scores):
    path = WARDEN_DIR / f"claims_scores_{tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": time.time(), "scores": scores}, indent=1))


def load_scores():
    from strategies.expert_lifecycle import active_lanes
    active = {f"fxexp-{eid.replace('fx-expert-', '')}" for eid in active_lanes()}
    out = {}
    for tag in _lane_order():
        if tag not in active:
            continue  # cut/inactive lanes don't claim
        p = WARDEN_DIR / f"claims_scores_{tag}.json"
        if p.exists():
            d = json.loads(p.read_text())
            out[tag] = (d.get("scores", {}), float(d.get("ts", 0)))
    return out


def claims_path():
    return WARDEN_DIR / "claims.json"


def current_claims():
    if claims_path().exists():
        return json.loads(claims_path().read_text()).get("claims", {})
    return {}


def recompute():
    claims = assign(load_scores())
    claims_path().write_text(json.dumps(
        {"claims": claims, "recomputed": time.time()}, indent=1))
    return claims


def owner_of(pair, claims=None):
    claims = claims if claims is not None else current_claims()
    return (claims.get(pair) or {}).get("lane")
