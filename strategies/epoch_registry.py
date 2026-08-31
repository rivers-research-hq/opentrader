#!/usr/bin/env python3
"""epoch_registry — ADR-0009 expert promotion seam (built 2026-08-31).

Separate epoch-expert registry, keyed by (epoch, expert_id). Shadow-first,
compete-not-displace (ADR-0009 §3): registration grants *eligibility* only;
weight and order flow are earned exclusively through forward accrual on the
expert's own ledger, and the shadow -> live-order-flow boundary requires
human signoff (ADR-0009 §4).

Status semantics (three-state, commit bea03d3):
    accruing — evidence window still open (default on registration)
    pass     — promotion bar met AND human signed off
    fail     — active violation (decayed edge, integrity break); reserved

Seeds (ADR-0009 §2): a candidate promoted through an arena gate carries
seed = {"kind": "gate_margin", "margin": ..., "n": 5}. Experts registered
as live incumbents or shadow challengers carry seed = null — no fabricated
margins; their track records are the accrual ledgers they name.

Single writer: this module. Atomic writes (tmp + rename). Every mutation
is appended to data/epoch_registry_log.jsonl.

Usage:
    python3 -m strategies.epoch_registry            # summary table
    python3 -m strategies.epoch_registry --json     # raw registry
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
REGISTRY = PROJECT / "data" / "epoch_registry.json"
LOG = PROJECT / "data" / "epoch_registry_log.jsonl"

STATUSES = ("accruing", "pass", "fail")


def _now():
    return datetime.now(timezone.utc).isoformat()


def load():
    if not REGISTRY.exists():
        return {"experts": []}
    return json.loads(REGISTRY.read_text())


def _save(reg):
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, indent=2) + "\n")
    os.replace(tmp, REGISTRY)


def _log(event):
    event = {"ts": _now(), **event}
    with LOG.open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def register(expert_id, epoch=1, kind="challenger", family=None, venue=None,
             universe=None, source=None, accrual_ledger=None, promotion_bar=None,
             notes=None, registered_by="agent"):
    reg = load()
    if any(e["expert_id"] == expert_id and e["epoch"] == epoch for e in reg["experts"]):
        raise SystemExit(f"[registry] {expert_id} already registered in epoch {epoch}")
    if kind not in ("incumbent", "challenger"):
        raise SystemExit(f"[registry] kind must be incumbent|challenger, got {kind!r}")
    entry = {
        "epoch": epoch,
        "expert_id": expert_id,
        "kind": kind,
        "family": family,
        "venue": venue,
        "universe": universe,
        "status": "accruing",
        "registered": _now(),
        "registered_by": registered_by,
        "source": source,
        "seed": None,
        "accrual": {"ledger": accrual_ledger, "closed_trades": None, "last_checked": None},
        "promotion_bar": promotion_bar,
        "notes": notes,
    }
    reg["experts"].append(entry)
    _save(reg)
    _log({"event": "register", "expert_id": expert_id, "epoch": epoch,
          "kind": kind, "status": "accruing", "registered_by": registered_by})
    print(f"[registry] registered {expert_id} (epoch {epoch}, {kind}, accruing)")
    return entry


def set_status(expert_id, status, reason, by="agent"):
    assert status in STATUSES, f"status must be one of {STATUSES}"
    reg = load()
    for e in reg["experts"]:
        if e["expert_id"] == expert_id:
            old = e["status"]
            e["status"] = status
            _save(reg)
            _log({"event": "status", "expert_id": expert_id, "from": old,
                  "to": status, "reason": reason, "by": by})
            print(f"[registry] {expert_id}: {old} -> {status} ({reason})")
            return
    raise SystemExit(f"[registry] unknown expert {expert_id}")


def refresh_accrual(expert_id):
    """Count closed round trips in the expert's accrual ledger (best-effort:
    counts close-reason fills; server-side SL/TP exits reconcile separately
    against the venue — heuristic, labeled as such)."""
    reg = load()
    for e in reg["experts"]:
        if e["expert_id"] != expert_id:
            continue
        led = e["accrual"].get("ledger")
        n = None
        if led and (PROJECT / led).exists():
            close_reasons = ("out-of-target", "max-hold", "stop", "target",
                             "mr-fade-exit-stop", "mr-fade-exit-target", "mr-fade-exit-hold")
            n = 0
            for line in (PROJECT / led).read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    f = json.loads(line)
                except Exception:
                    continue
                if str(f.get("reason", "")).startswith(close_reasons) or f.get("reason") in close_reasons:
                    n += 1
        e["accrual"]["closed_trades"] = n
        e["accrual"]["last_checked"] = _now()
        _save(reg)
        print(f"[registry] {expert_id}: accrual closed_trades={n} (ledger {led})")
        return
    raise SystemExit(f"[registry] unknown expert {expert_id}")


def annotate(expert_id, field, value, by="agent"):
    """Update a descriptive field on an entry (universe, notes, promotion_bar)
    with a logged event. Status changes go through set_status, not this."""
    reg = load()
    for e in reg["experts"]:
        if e["expert_id"] == expert_id:
            old = e.get(field)
            e[field] = value
            _save(reg)
            _log({"event": "annotate", "expert_id": expert_id, "field": field,
                  "from": old, "to": value, "by": by})
            print(f"[registry] {expert_id}.{field}: {old!r} -> {value!r}")
            return
    raise SystemExit(f"[registry] unknown expert {expert_id}")


def summary():
    reg = load()
    if not reg["experts"]:
        print("[registry] empty")
        return
    print(f"epoch registry — {len(reg['experts'])} expert(s)\n")
    hdr = f"{'epoch':>5}  {'expert_id':<20} {'kind':<11} {'status':<9} {'closed':>6}  accrual ledger"
    print(hdr)
    print("-" * len(hdr))
    for e in reg["experts"]:
        a = e["accrual"] or {}
        print(f"{e['epoch']:>5}  {e['expert_id']:<20} {e['kind']:<11} {e['status']:<9} "
              f"{str(a.get('closed_trades')):>6}  {a.get('ledger')}")
    print("\nlog: data/epoch_registry_log.jsonl")


if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(load(), indent=2))
    else:
        summary()
