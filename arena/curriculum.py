"""The curriculum engine: skill states, grading, carrot/stick, progression.

State lives in data/arena/curriculum.json. Skills come from the taxonomy
(arena.architect.SEED_SKILLS) plus Architect proposals. Grading reads the
latest arena report (data/arena/arena_state.json) plus a recomputed
discrimination for the unseen bear sub-window. Carrot: mastered skills grant
+1 battle pass/iteration (cap 16), +25% QLoRA dataset budget (cap 1200),
+1% shadow risk per 3 masteries (cap 10%). Stick: 2 failures -> remedial
(drop one tier, relax pass bar 20%, retrain flag, gating). Progression:
weakness-driven, graduated when all tier-5 skills are mastered.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"
REPORT = OUT / "arena_state.json"

CARROT = {
    "battle_passes_per_mastery": 1,
    "battle_passes_base": 8,
    "battle_passes_cap": 16,
    "qlora_budget_per_mastery": 0.25,
    "qlora_budget_base": 400,
    "qlora_budget_cap": 1200,
    "shadow_risk_every_n": 3,
    "shadow_risk_step": 0.01,
    "shadow_risk_cap": 0.10,
}
STICK = {
    "failures_for_remedial": 2,
    "remedial_tier_drop": 1,
    "remedial_pass_bar_relax": 0.2,
    "war_vs_field_before_tier": 3,
}


def _empty_state(skills):
    return {
        "skills": {
            s["id"]: {
                "tier": s["tier"],
                "status": "locked",
                "failures": 0,
                "consecutive": 0,
                "mastered_at": None,
                "prerequisites": s.get("prerequisites", []),
            }
            for s in skills
        },
        "iterations_seen": [],
        "mastered": [],
        "graduate": False,
        "last_error": None,
        "updated_at": None,
    }


def load_state(skills=None):
    from arena.architect import SEED_SKILLS

    skills = skills or SEED_SKILLS
    path = OUT / "curriculum.json"
    if path.exists():
        state = json.loads(path.read_text())
        for s in skills:
            state["skills"].setdefault(
                s["id"],
                {
                    "tier": s["tier"],
                    "status": "locked",
                    "failures": 0,
                    "consecutive": 0,
                    "mastered_at": None,
                    "prerequisites": s.get("prerequisites", []),
                },
            )
        return state
    return _empty_state(skills)


def _save(state):
    OUT.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (OUT / "curriculum.json").write_text(json.dumps(state, indent=1, default=str))


def _metric_for(skill, report):
    obj = skill.get("objective")
    pb = skill.get("pass_bar", {})
    b = report.get("battle", {})
    st = b.get("standings", {})
    a = st.get("agent", {})
    z = a.get("arena_score", 0.0)
    z_of = {n: s.get("arena_score", 0.0) for n, s in st.items()}
    h2h = b.get("h2h", {})
    war = report.get("war", {})
    w_agent = war.get("agent", {}).get("net_return", 0.0)
    w_of = {n: v.get("net_return", 0.0) for n, v in war.items()}
    margins = {
        r["window"]: r["margin"] for r in report.get("gate", {}).get("results", [])
    }
    if obj == "battle_takes":
        return a.get("takes", 0) >= pb.get("min_takes", 1)
    if obj == "arena_z":
        if "beats" in pb:
            return z > z_of.get(pb["beats"], 0.0)
        return z >= pb.get("min_z", 0.0)
    if obj == "war_net_return":
        return w_agent > pb.get("min_return", 0.0)
    if obj == "war_vs":
        return w_agent > w_of.get(pb.get("beats"), 0.0)
    if obj == "h2h_and_war":
        h = h2h.get(pb.get("h2h_wins_gt_losses", ""), {"wins": 0, "losses": 0})
        return h["wins"] > h["losses"] and w_agent > w_of.get(
            pb.get("war_beats", ""), 0.0
        )
    if obj == "war_vs_multi":
        return all(w_agent > w_of.get(n, 0.0) for n in pb.get("beats", []))
    if obj == "discrimination":
        w = pb.get("window", "")
        m = margins.get(w, 0.0)
        return m >= pb.get("min_margin", 0.01)
    if obj == "gate_margins":
        wins = pb.get("windows", [])
        return all(margins.get(w, 0.0) >= pb.get("min_margin", 0.01) for w in wins)
    if obj == "gate_pass":
        return bool(report.get("gate", {}).get("pass"))
    if obj == "adapter":
        ok = (
            PROJECT / "data/gpu_scheduler/adapters/momentum-agent/summary.json"
        ).exists()
        return ok and bool(pb.get("adapter_exists", True))
    if obj == "deployment":
        return (OUT / "momentum_gate.json").exists()
    return False


def grade(state, report):
    from arena.architect import SEED_SKILLS

    by_id = {s["id"]: s for s in SEED_SKILLS}
    for sid, sk in state["skills"].items():
        if sk["status"] in ("mastered", "remedial"):
            continue
        skill = by_id.get(sid)
        if not skill:
            continue
        if not _prereqs_lit(state, sid):
            continue
        sk["status"] = "attemptable"
        passed = _metric_for(skill, report)
        if passed:
            sk["consecutive"] += 1
            need = skill.get("pass_bar", {}).get("consecutive", 1)
            if sk["consecutive"] >= need:
                sk["status"] = "mastered"
                sk["mastered_at"] = report.get("iteration")
                sk["failures"] = 0
                if sid not in state["mastered"]:
                    state["mastered"].append(sid)
        else:
            sk["consecutive"] = 0
            sk["failures"] += 1
            if sk["failures"] >= STICK["failures_for_remedial"]:
                sk["status"] = "remedial"
                sk["retrain_flag"] = True
    state["mastered"] = sorted(set(state["mastered"]))
    state["iterations_seen"] = sorted(
        set(state["iterations_seen"] + [report.get("iteration")])
    )
    t5 = [
        sk for sid, sk in state["skills"].items() if by_id.get(sid, {}).get("tier") == 5
    ]
    state["graduate"] = bool(t5) and all(sk["status"] == "mastered" for sk in t5)
    _apply_carrot(state)
    _save(state)
    return state


def _prereqs_lit(state, sid):
    sk = state["skills"].get(sid, {})
    return all(
        state["skills"].get(p, {}).get("status") == "mastered"
        for p in sk.get("prerequisites", [])
    )


def _apply_carrot(state):
    n = len(state["mastered"])
    state["carrot"] = {
        "battle_passes": min(
            CARROT["battle_passes_base"] + CARROT["battle_passes_per_mastery"] * n,
            CARROT["battle_passes_cap"],
        ),
        "qlora_budget": int(
            min(
                CARROT["qlora_budget_base"]
                * (1 + CARROT["qlora_budget_per_mastery"] * n),
                CARROT["qlora_budget_cap"],
            )
        ),
        "shadow_risk": min(
            (n // CARROT["shadow_risk_every_n"]) * CARROT["shadow_risk_step"],
            CARROT["shadow_risk_cap"],
        ),
        "mastered_count": n,
    }


def next_skill(state):
    candidates = [
        sid for sid, sk in state["skills"].items() if sk["status"] == "attemptable"
    ]
    if not candidates:
        return None
    from arena.architect import SEED_SKILLS

    by_id = {s["id"]: s for s in SEED_SKILLS}
    return min(candidates, key=lambda sid: by_id.get(sid, {}).get("tier", 99))


def queue_proposal(proposal):
    """Add an Architect proposal to the curriculum. Prerequisites must be
    known skill ids; tier = max(prereq tiers) + 1 (floored at 1)."""
    from arena.architect import SEED_SKILLS

    state = load_state(SEED_SKILLS)
    known = set(state["skills"].keys())
    prereqs = proposal.get("prerequisites", []) or []
    if not all(p in known for p in prereqs):
        print(
            f"[curriculum] proposal {proposal.get('id')} rejected: unknown prerequisites "
            f"{[p for p in prereqs if p not in known]}"
        )
        return False
    if proposal.get("id") in known:
        print(f"[curriculum] proposal {proposal.get('id')} rejected: duplicate id")
        return False
    tier = max((state["skills"][p].get("tier", 1) for p in prereqs), default=0) + 1
    state["skills"][proposal["id"]] = {
        "tier": tier,
        "status": "locked",
        "failures": 0,
        "consecutive": 0,
        "mastered_at": None,
        "prerequisites": prereqs,
        "proposed": True,
        "name": proposal.get("name"),
        "pass_bar": proposal.get("pass_bar"),
        "metric_source": proposal.get("metric_source"),
    }
    _save(state)
    print(
        f"[curriculum] queued proposal {proposal['id']} (tier {tier}): {proposal.get('name')}"
    )
    return True


def run_grade_step():
    from arena.architect import SEED_SKILLS

    state = load_state(SEED_SKILLS)
    if not REPORT.exists():
        state["last_error"] = "no arena_state.json yet"
        _save(state)
        return state
    report = json.loads(REPORT.read_text())
    state = grade(state, report)
    nxt = next_skill(state)
    print(
        f"[curriculum] mastered={len(state['mastered'])}/{len(state['skills'])} "
        f"graduate={state['graduate']} next={nxt}"
    )
    print(f"[curriculum] carrot={state.get('carrot')}")
    for sid, sk in state["skills"].items():
        if sk["status"] != "locked":
            print(
                f"  {sk['status']:10s} {sid} failures={sk['failures']} conc={sk['consecutive']}"
            )
    return state


if __name__ == "__main__":
    run_grade_step()
