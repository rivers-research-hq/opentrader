"""Build the Architect training dataset (retrain 2026-08-11).

Matches the CURRENT runtime render_weakness_report format exactly:
  - single-window forward-only gate: "gate margins 1000-1250=+x.xx%"
  - the known_ids constraint block (same text as arch_review builds)
  - WAR lines carry trade counts "(Nt)"
  - current SEED_SKILLS ids (s12-future-autonomy, no s04)

Output: data/arena/architect_dataset.jsonl — {prompt, decision}
"""

import json
import random
from pathlib import Path

from arena.architect import SEED_SKILLS, PRELUDE, SKILL_SCHEMA_KEYS

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"

SKILL_BY_ID = {s["id"]: s for s in SEED_SKILLS}

CONSTRAINT = (
    "\nPrerequisites MUST be ids from the existing skill list"
    " (e.g. {ids6}, ...). Never invent ids.\n"
)


def _weak_metrics(skill):
    pb = skill.get("pass_bar", {})
    objective = skill.get("objective")
    if objective == "discrimination":
        return {"gate0": pb.get("min_margin", 0.01) - 0.006}
    if objective == "arena_z":
        return {
            "z": 0.08,
            "field": {
                "rule-config": 0.666,
                "ahl": -0.113,
                "citadel": 0.161,
                "citron": -0.411,
                "always-take": 0.0,
                "random": 0.004,
            },
        }
    if objective == "war_vs":
        return {"agent_ret": 0.025, "opp_ret": 0.12}
    if objective == "h2h_and_war":
        return {
            "h2h": {"citron": {"wins": 5, "losses": 9}},
            "war": {"agent": 0.02, "citron": 0.05},
        }
    if objective == "war_vs_multi":
        return {"war": {"agent": 0.03, "citadel": 0.04, "ahl": 0.09, "citron": 0.05}}
    if objective == "gate_margins":
        return {}  # gate line shows the failing margin via healthy=False
    if objective == "gate_pass":
        return {}  # gate line shows the failing margin via healthy=False
    if objective == "adapter":
        return {"adapter": False}
    if objective == "deployment":
        return {"adapter": True, "validation": False}
    return {}


def _report(skill, weak, tech_lit, rng, healthy=False):
    j = lambda v, f: round(rng.uniform(v * (1 - f), v * (1 + f)), 5) if v else v
    # audit 2026-08-11: the gate margin MUST be consistent with the decision —
    # skill reports show a failing gate (weakness), noop reports a passing one
    if healthy:
        margin0 = j(0.0125, 0.15)   # comfortably above the +1% bar
    else:
        margin0 = j(0.0045, 0.4)    # clearly below the +1% bar
    margin0 = weak.get("gate0", margin0)
    z = weak.get("z", j(0.66, 0.1))
    field = weak.get(
        "field",
        {
            "rule-config": j(0.666, 0.05),
            "ahl": j(-0.113, 0.3),
            "citadel": j(0.161, 0.2),
            "citron": j(-0.411, 0.15),
            "random": j(0.004, 0.8),
        },
    )
    h2h = weak.get(
        "h2h",
        {
            "citron": {"wins": int(j(128, 0.2)), "losses": int(j(41, 0.2))},
            "ahl": {"wins": int(j(60, 0.3)), "losses": int(j(80, 0.2))},
            "rule-config": {"wins": int(j(90, 0.2)), "losses": int(j(120, 0.2))},
        },
    )
    war = weak.get(
        "war",
        {
            "agent": j(0.0715, 0.2),
            "rule-config": j(0.1856, 0.1),
            "citadel": j(0.0385, 0.2),
            "ahl": j(0.0122, 0.3),
            "citron": 0.0,
        },
    )
    # compact report: matches the trimmed runtime render (audit 2026-08-11)
    # so train/serve formats align and everything fits the 512-token ceiling
    lines = [
        f"ITERATION {rng.randint(22, 30)} | gate margins 1000-1250={margin0:+.2%} | pass={margin0 >= 0.01}",
        f"TECH TREE {rng.randint(10, 14)}/{len(SEED_SKILLS)} lit | missing: {', '.join(n for n in ['beats-rule', 'top-field', 'war-beats-rule', 'mot-weight'] if n not in tech_lit)}",
        f"BATTLE agent takes={rng.randint(4000, 9000)} take_mean=+{j(1.9, 0.2):.2f}% arena_z={z:+.3f}",
        "BATTLE field " + " | ".join(f"{n}={v:+.3f}" for n, v in sorted(field.items())),
        "H2H "
        + " | ".join(
            f"vs {n} {h['wins']}W/{h['losses']}L" for n, h in sorted(h2h.items())
        ),
        "WAR "
        + " | ".join(
            f"{n} {v:+.2%} ({rng.randint(5, 400)}t)" for n, v in sorted(war.items())
        ),
        f"REGIME agent up +{j(2.7, 0.3):.2f}% ({rng.randint(40, 90)}) down +0.00% (0)",
        f"BEAR RELABELS trained={rng.randint(30, 60)}",
    ]
    return "\n".join(lines)


def build(seed=11, variants=12, n_noop=16):
    rng = random.Random(seed)
    rows = []
    known_ids = sorted(SKILL_BY_ID.keys())
    constraint = CONSTRAINT.format(ids6=", ".join(known_ids[:6]))
    for skill in SEED_SKILLS:
        tech_lit = [
            s["id"] for s in SEED_SKILLS if s["id"] in skill.get("prerequisites", [])
        ]
        tech_lit += [
            "takes",
            "beats-field",
            "war-book-profit",
            "gate-future",
        ]
        target = json.dumps({k: skill[k] for k in skill})
        for _ in range(variants):
            report = _report(skill, _weak_metrics(skill), tech_lit, rng, healthy=False)
            rows.append(
                {
                    "prompt": PRELUDE
                    + constraint
                    + report
                    + "\n\nNext skill proposal (JSON):",
                    "decision": target,
                }
            )
    for _ in range(n_noop):
        report = _report({}, {}, list(SKILL_BY_ID), rng, healthy=True)
        rows.append(
            {
                "prompt": PRELUDE
                + constraint
                + report
                + "\n\nNext skill proposal (JSON):",
                "decision": json.dumps(
                    {
                        "noop": True,
                        "rationale": rng.choice(
                            [
                                "All measured objectives are above their pass bars.",
                                "The gate holds and the war book is profitable; no new skill is warranted.",
                                "Current skills cover every lit tech node; proposing more would overfit.",
                            ]
                        ),
                    }
                ),
            }
        )
    rng.shuffle(rows)
    path = OUT / "architect_dataset.jsonl"
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"[architect-dataset] {len(rows)} examples -> {path}")
    return path


if __name__ == "__main__":
    build()
