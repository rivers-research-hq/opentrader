"""expert_lifecycle — the registry state machine (v2).

Turns the epoch registry from a passive record into the operating contract:
each expert moves through a lifecycle, and the lifecycle state controls what
every component (lane, trail check, warden, auction, mid-train) does with
that expert. transition() is the ONLY way to change state — it validates,
logs, and triggers side effects.

States and what they permit:
  candidate   — gate passed, not deployed. Cannot trade.
  registered  — human approved deployment. Paper only (ADR-0009 shadow).
  accruing    — full live trading at full notional.
  probation   — live trading at reduced notional (notional_cap < 1.0).
                Set by warden escalation. Recoverable.
  cut         — terminal: lane stops, positions close, claims released,
                records quarantined. Human-gated.
  archived    — terminal: records feed the mid-train corpus (filtered by
                cut_reason). No further action.

Usage:
    from strategies.expert_lifecycle import transition, lifecycle_of
    transition("fxexp-g151", "probation", reason="warden escalation",
               actor="warden", notional_cap=0.5)
    state = lifecycle_of("fxexp-g151")  # -> {"lifecycle": "probation", ...}
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
REGISTRY = PROJECT / "data" / "epoch_registry.json"
LOG = PROJECT / "data" / "epoch_registry_log.jsonl"
CLAIMS = PROJECT / "data" / "fx_expert" / "claims.json"

STATES = ["candidate", "registered", "accruing", "probation", "cut", "archived"]
TRANSITIONS = {
    "candidate":  ["registered"],
    "registered": ["accruing"],
    "accruing":   ["probation", "cut"],
    "probation":  ["accruing", "cut"],
    "cut":        ["archived"],
    "archived":   [],
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _log(event):
    event = {"ts": _now(), **event}
    with LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _load_registry():
    if not REGISTRY.exists():
        return {"experts": []}
    return json.loads(REGISTRY.read_text())


def _save_registry(reg):
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2) + "\n")
    os.replace(tmp, REGISTRY)


def lifecycle_of(expert_id: str) -> dict | None:
    """Returns the expert's entry (lifecycle + metadata) or None."""
    reg = _load_registry()
    for e in reg["experts"]:
        if e["expert_id"] == expert_id:
            return e
    return None


def all_lifecycles() -> dict[str, str]:
    """Returns {expert_id: lifecycle} for all registered experts."""
    return {e["expert_id"]: e.get("lifecycle", "candidate")
            for e in _load_registry()["experts"]}


def active_lanes() -> list[str]:
    """Expert IDs allowed to trade: accruing + probation."""
    lc = all_lifecycles()
    return [eid for eid, state in lc.items() if state in ("accruing", "probation")]


def notional_cap(expert_id: str) -> float:
    """Notional multiplier (0.0-1.0) for this expert. Probation carries a cap."""
    e = lifecycle_of(expert_id)
    if e is None:
        return 0.0
    return float(e.get("notional_cap", 1.0))


def transition(expert_id: str, new_state: str, reason: str, actor: str = "system",
               notional_cap: float | None = None, cut_reason: str | None = None) -> dict:
    """Change an expert's lifecycle state. Validates, logs, triggers side
    effects. Returns the updated entry. Raises on invalid transitions."""
    if new_state not in STATES:
        raise ValueError(f"unknown lifecycle state: {new_state}")
    reg = _load_registry()
    entry = None
    for e in reg["experts"]:
        if e["expert_id"] == expert_id:
            entry = e
            break
    if entry is None:
        raise ValueError(f"expert {expert_id} not found in registry")

    old = entry.get("lifecycle", "candidate")
    if new_state not in TRANSITIONS.get(old, []):
        raise ValueError(f"invalid transition: {old} -> {new_state}")

    entry["lifecycle"] = new_state
    entry["lifecycle_changed"] = _now()
    entry["lifecycle_reason"] = reason
    if notional_cap is not None:
        entry["notional_cap"] = notional_cap
    if cut_reason is not None:
        entry["cut_reason"] = cut_reason

    _save_registry(reg)
    _log({"event": "lifecycle", "expert_id": expert_id,
          "from": old, "to": new_state, "reason": reason, "actor": actor})

    # side effects
    if new_state == "cut":
        _release_claims(expert_id)
    if new_state == "archived":
        pass  # records.jsonl filtering happens at mid-train read time

    print(f"[lifecycle] {expert_id}: {old} -> {new_state} ({reason}, by {actor})")
    return entry


def _lane_tags(expert_id: str) -> set[str]:
    """Registry IDs use 'fx-expert-<tag>'; lane/auction tags use
    'fxexp-<tag>'. A cut must release claims under EITHER spelling —
    a mismatch here silently leaves claims assigned (caught 2026-09-09)."""
    tags = {expert_id}
    if expert_id.startswith("fx-expert-"):
        tags.add("fxexp-" + expert_id[len("fx-expert-"):])
    elif expert_id.startswith("fxexp-"):
        tags.add("fx-expert-" + expert_id[len("fxexp-"):])
    return tags


def _release_claims(expert_id: str):
    """Remove a cut expert's claims so the auction can reassign."""
    if not CLAIMS.exists():
        return
    claims = json.loads(CLAIMS.read_text())
    tags = _lane_tags(expert_id)
    released = [p for p, v in claims.get("claims", {}).items()
                if v.get("lane") in tags]
    for p in released:
        del claims["claims"][p]
    if not released:
        # Nothing matched — either the lane held no claims, or claims.json
        # uses a tag spelling we don't recognise. Say so rather than
        # silently succeeding.
        sample = next(iter(claims.get("claims", {}).values()), None)
        print(f"[lifecycle] WARNING: cut {expert_id} released 0 claims; "
              f"lane spellings seen in claims.json: {sample}")
    claims["recomputed"] = _now()
    CLAIMS.write_text(json.dumps(claims, indent=1))
    if released:
        print(f"[lifecycle] released {len(released)} claims from {expert_id}: {released}")


def migrate_existing():
    """Backfill lifecycle on pre-v2 registry entries. Existing entries get
    their current status mapped: accruing -> accruing, fail -> cut."""
    reg = _load_registry()
    changed = 0
    for e in reg["experts"]:
        if "lifecycle" not in e:
            status = e.get("status", "accruing")
            e["lifecycle"] = "cut" if status == "fail" else "accruing"
            e["notional_cap"] = 1.0
            changed += 1
    if changed:
        _save_registry(reg)
        print(f"[lifecycle] migrated {changed} entries to v2 schema")
    return changed


if __name__ == "__main__":
    migrate_existing()
    lc = all_lifecycles()
    for eid, state in sorted(lc.items()):
        print(f"  {eid:24s} {state}")
