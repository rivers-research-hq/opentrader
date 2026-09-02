"""The agent's discovery tech-tree — what the arena run has learned.

Persistent state in data/arena/tech_tree.json. Each node unlocks when its
condition is first met in an iteration report; once discovered it stays
discovered. The viewer renders it like a game tech tree gaining experience.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"

NODES = [
    {"id": "born", "label": "Arena born", "parent": None},
    {"id": "takes", "label": "Takes in the ring", "parent": "born"},
    {"id": "beats-field", "label": "Beats the field", "parent": "takes"},
    {"id": "beats-always-take", "label": "Beats always-take", "parent": "beats-field"},
    {"id": "beats-random", "label": "Beats random", "parent": "beats-field"},
    {"id": "beats-citadel", "label": "Beats Citadel", "parent": "beats-field"},
    {"id": "beats-citron", "label": "Beats Citron", "parent": "beats-field"},
    {"id": "beats-ahl", "label": "Beats AHL", "parent": "beats-field"},
    {"id": "beats-rule", "label": "Beats rule-config", "parent": "beats-field"},
    {"id": "top-field", "label": "Top of the field", "parent": "beats-field"},
    {"id": "war-profit", "label": "War book profitable", "parent": "takes"},
    {"id": "war-beats-rule", "label": "War beats rule-config", "parent": "war-profit"},
    {"id": "gate-bear", "label": "Gate: 2022 bear window", "parent": "born"},
    {"id": "gate-bull", "label": "Gate: 2026 window", "parent": "gate-bear"},
    {"id": "gate-pass", "label": "GATE PASSED - autonomy bar", "parent": "gate-bull"},
    {"id": "qlora", "label": "QLoRA distilled", "parent": "takes"},
    {"id": "mot-weight", "label": "Momentum earns MoT weight", "parent": "qlora"},
]


def _conditions(report, adapter_path):
    st = report["battle"]["standings"]
    a = st.get("agent", {})
    z = {n: s["arena_score"] for n, s in st.items()}
    z_agent = z.get("agent", 0.0)
    others = {n: v for n, v in z.items() if n != "agent"}
    margins = [r["margin"] for r in report["gate"]["results"]]
    war = report["war"]
    a_ret = war.get("agent", {}).get("net_return", 0.0)
    r_ret = war.get("rule-config", {}).get("net_return", 0.0)
    return {
        "born": True,
        "takes": a.get("takes", 0) > 0,
        "beats-field": z_agent > 0,
        "beats-always-take": z_agent > others.get("always-take", 0.0),
        "beats-random": z_agent > others.get("random", 0.0),
        "beats-citadel": z_agent > others.get("citadel", 0.0),
        "beats-citron": z_agent > others.get("citron", 0.0),
        "beats-ahl": z_agent > others.get("ahl", 0.0),
        "beats-rule": z_agent > others.get("rule-config", 0.0),
        "top-field": bool(others) and z_agent >= max(others.values()),
        "war-profit": a_ret > 0,
        "war-beats-rule": a_ret > r_ret,
        "gate-bear": len(margins) > 0 and margins[0] >= 0.01,
        "gate-bull": len(margins) > 1 and margins[1] >= 0.01,
        "gate-pass": report["gate"]["pass"],
        "qlora": adapter_path.exists(),
        "mot-weight": (OUT / "momentum_gate.json").exists(),
    }


def update(
    report,
    iteration,
    adapter_path=PROJECT / "data/gpu_scheduler/adapters/momentum-agent/summary.json",
):
    path = OUT / "tech_tree.json"
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {"discovered": {}, "first_seen": {}, "iterations": [], "nodes": NODES}
    )
    conds = _conditions(report, adapter_path)
    for node in NODES:
        nid = node["id"]
        if nid in state["discovered"]:
            continue
        if conds.get(nid):
            state["discovered"][nid] = iteration
            state["first_seen"][nid] = conds.get(nid, False)
    state["iterations"] = sorted(set(state["iterations"] + [iteration]))
    state["nodes"] = NODES
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1))
    return state


def snapshot(report, iteration):
    state = update(report, iteration)
    return {
        "nodes": NODES,
        "discovered": state["discovered"],
        "iterations": state["iterations"],
    }
