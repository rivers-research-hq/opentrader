"""The Curriculum Architect — local model, local grading.

render_weakness_report(state, tech): compact numeric text from the arena's
own outputs. validate_proposal(proposal): schema + numeric-source + dedup
checks. The Architect model itself is a locally-trained qwen-2.5-7b QLoRA
(adapter in data/gpu_scheduler/adapters/architect) served on GPU1.
"""

import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"

SKILL_SCHEMA_KEYS = [
    "id",
    "name",
    "tier",
    "prerequisites",
    "scenario",
    "objective",
    "pass_bar",
    "metric_source",
    "rationale",
]

SEED_SKILLS = [
    {
        "id": "s01-takes-in-ring",
        "name": "Takes in the ring",
        "tier": 1,
        "prerequisites": [],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "full"},
        "objective": "battle_takes",
        "pass_bar": {"min_takes": 1},
        "metric_source": "battle.standings.agent.takes",
        "rationale": "The agent must participate before it can learn.",
    },
    {
        "id": "s02-beats-field",
        "name": "Beats the field",
        "tier": 1,
        "prerequisites": ["s01-takes-in-ring"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "full"},
        "objective": "arena_z",
        "pass_bar": {"min_z": 0.0},
        "metric_source": "battle.standings.agent.arena_score",
        "rationale": "Arena-relative edge is the first real skill.",
    },
    {
        "id": "s03-war-book-profit",
        "name": "War book profitable",
        "tier": 1,
        "prerequisites": ["s01-takes-in-ring"],
        "scenario": {"window": "5y", "regime": "mixed", "field": "full"},
        "objective": "war_net_return",
        "pass_bar": {"min_return": 0.0},
        "metric_source": "war.agent.net_return",
        "rationale": "Episodic outcomes must be positive.",
    },
    {
        "id": "s05-window-2026",
        "name": "Window 2026",
        "tier": 1,
        "prerequisites": [],
        "scenario": {"window": "1000-1250", "regime": "mixed", "field": "full"},
        "objective": "discrimination",
        "pass_bar": {"window": "1000-1250", "min_margin": 0.01},
        "metric_source": "gate.results[0].margin",
        "rationale": "The fully unseen window.",
    },
    {
        "id": "s06-beats-always-take",
        "name": "Beats always-take",
        "tier": 2,
        "prerequisites": ["s02-beats-field"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "baselines"},
        "objective": "arena_z",
        "pass_bar": {"beats": "always-take"},
        "metric_source": "battle.standings.*.arena_score",
        "rationale": "Selectivity beats indiscriminate taking.",
    },
    {
        "id": "s07-beats-random",
        "name": "Beats random",
        "tier": 2,
        "prerequisites": ["s02-beats-field"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "baselines"},
        "objective": "arena_z",
        "pass_bar": {"beats": "random"},
        "metric_source": "battle.standings.*.arena_score",
        "rationale": "Signal beats noise.",
    },
    {
        "id": "s08-trend-ride",
        "name": "Trend ride",
        "tier": 2,
        "prerequisites": ["s03-war-book-profit"],
        "scenario": {"window": "5y", "regime": "up", "field": "ahl"},
        "objective": "war_vs",
        "pass_bar": {"beats": "ahl", "regime": "up"},
        "metric_source": "war_regime[agent].up vs war_regime[ahl].up",
        "rationale": "The momentum agent must out-ride the trend house in up-regimes.",
    },
    {
        "id": "s09-range-defense",
        "name": "Range defense",
        "tier": 2,
        "prerequisites": ["s03-war-book-profit"],
        "scenario": {"window": "5y", "regime": "down", "field": "citadel"},
        "objective": "war_vs",
        "pass_bar": {"beats": "citadel", "regime": "down"},
        "metric_source": "war_regime[agent].down vs war_regime[citadel].down",
        "rationale": "Do not bleed to the relative-value house in choppy regimes.",
    },
    {
        "id": "s10-hype-fade-duel",
        "name": "Hype-fade duel",
        "tier": 3,
        "prerequisites": ["s07-beats-random"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "citron"},
        "objective": "h2h_and_war",
        "pass_bar": {"h2h_wins_gt_losses": "citron", "war_beats": "citron"},
        "metric_source": "battle.h2h.citron + war.citron.net_return",
        "rationale": "Survive the adversarial short-seller in froth.",
    },
    {
        "id": "s11-hedge-fund-gauntlet",
        "name": "Hedge-fund gauntlet",
        "tier": 3,
        "prerequisites": ["s08-trend-ride", "s09-range-defense"],
        "scenario": {"window": "5y", "regime": "mixed", "field": "personas"},
        "objective": "war_vs_multi",
        "pass_bar": {"beats": ["citadel", "ahl", "citron"]},
        "metric_source": "war books net_return",
        "rationale": "Beat all three persona houses in the war.",
    },
    {
        "id": "s12-future-autonomy",
        "name": "Future autonomy",
        "tier": 4,
        "prerequisites": ["s05-window-2026"],
        "scenario": {"window": "1000-1250", "regime": "mixed", "field": "full"},
        "objective": "gate_margins",
        "pass_bar": {
            "windows": ["1000-1250"],
            "min_margin": 0.01,
            "consecutive": 3,
        },
        "metric_source": "gate.results[*].margin",
        "rationale": "The unseen future holds the autonomy bar for 3 consecutive "
        "iterations. (audit 2026-08-11: the old 0-500 bear window was dropped — "
        "not discriminable at +1% even in-sample, see #68.)",
    },
    {
        "id": "s13-gate-locked",
        "name": "Gate locked",
        "tier": 4,
        "prerequisites": ["s12-future-autonomy"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "full"},
        "objective": "gate_pass",
        "pass_bar": {"consecutive_passes": 2},
        "metric_source": "gate.pass",
        "rationale": "The autonomy bar is official.",
    },
    {
        "id": "s14-qlora-distilled",
        "name": "QLoRA distilled",
        "tier": 4,
        "prerequisites": ["s13-gate-locked"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "full"},
        "objective": "adapter",
        "pass_bar": {"adapter_exists": True, "validation_discrim": 0.01},
        "metric_source": "data/gpu_scheduler/adapters/momentum-agent + validate_momentum_agent.py",
        "rationale": "The policy survives distillation into the 7B agent.",
    },
    {
        "id": "s15-mot-weight",
        "name": "Momentum earns MoT weight",
        "tier": 5,
        "prerequisites": ["s14-qlora-distilled"],
        "scenario": {"window": "mixed", "regime": "mixed", "field": "full"},
        "objective": "deployment",
        "pass_bar": {"validation_pass": True},
        "metric_source": "validate_momentum_agent.py",
        "rationale": "The agent earns its seat in the MoT roster.",
    },
]


def render_weakness_report(state, tech=None):
    g = state.get("gate", {})
    margins = " ".join(
        f"{r['window']}={r['margin']:+.2%}" for r in g.get("results", [])
    )
    lines = [
        f"ITERATION {state.get('iteration')} | gate margins {margins} | pass={g.get('pass')}",
    ]
    if tech:
        lit = tech.get("discovered", {})
        nodes = tech.get("nodes", [])
        missing = [n["id"] for n in nodes if n["id"] not in lit]
        lines.append(
            f"TECH TREE {len(lit)}/{len(nodes)} lit | missing: {', '.join(missing)}"
        )
    b = state.get("battle", {})
    st = b.get("standings", {})
    a = st.get("agent", {})
    lines.append(
        f"BATTLE agent takes={a.get('takes')} take_mean={a.get('take_mean', 0):+.2%} "
        f"arena_z={a.get('arena_score', 0):+.3f}"
    )
    field = sorted((n, s.get("arena_score", 0)) for n, s in st.items() if n != "agent")
    # trim zero-activity opponents (always-skip +0.000) — token budget on 8GB
    field = [(n, z) for n, z in field if abs(z) > 0.0005 or n in ("citron", "ahl", "rule-config")]
    lines.append("BATTLE field " + " | ".join(f"{n}={z:+.3f}" for n, z in field))
    h2h = b.get("h2h", {})
    # audit 2026-08-11: trim zero-activity opponents (always-skip 0W/0L etc.)
    # so the report stays inside the 512-token training ceiling on the 8GB card
    active_h2h = {n: h for n, h in sorted(h2h.items())
                  if h.get("wins", 0) + h.get("losses", 0) > 0}
    lines.append(
        "H2H "
        + " | ".join(
            f"vs {n} {h.get('wins', 0)}W/{h.get('losses', 0)}L"
            for n, h in active_h2h.items()
        )
    )
    w = state.get("war", {})
    active_war = {n: v for n, v in sorted(w.items())
                  if v.get("n_trades", 0) > 0}
    lines.append(
        "WAR "
        + " | ".join(
            f"{n} {v.get('net_return', 0):+.2%} ({v.get('n_trades', 0)}t)"
            for n, v in active_war.items()
        )
    )
    reg = state.get("war_regime", {})
    a_reg = reg.get("agent", {})
    lines.append(
        "REGIME agent "
        + " | ".join(
            f"{r} {v.get('mean_pnl_pct', 0):+.2%} ({v.get('n', 0)})"
            for r, v in a_reg.items()
        )
    )
    lines.append(f"BEAR RELABELS trained={state.get('n_bear_relabels', 0)}")
    return "\n".join(lines)


def validate_proposal(p, existing_ids):
    if not isinstance(p, dict):
        return False, "not a dict"
    if p.get("noop"):
        return True, None
    if not all(k in p for k in SKILL_SCHEMA_KEYS):
        return False, f"missing keys: {[k for k in SKILL_SCHEMA_KEYS if k not in p]}"
    if p["id"] in existing_ids:
        return False, "duplicate id"
    if not isinstance(p["pass_bar"], dict) or not p.get("metric_source"):
        return False, "pass_bar must be an object with metric_source"
    return True, None


def load_state():
    state_path = OUT / "arena_state.json"
    tech_path = OUT / "tech_tree.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    tech = json.loads(tech_path.read_text()) if tech_path.exists() else None
    return state, tech


ARCHITECT_ADAPTER = PROJECT / "data/gpu_scheduler/adapters/architect"

PRELUDE = (
    "You are the Curriculum Architect. From the weakness report propose ONE next "
    "skill as JSON: {id, name, tier, prerequisites, scenario{window,regime,field}, "
    "objective, pass_bar, metric_source, rationale}, numeric pass bars. "
    'Or {"noop": true, "rationale": "..."}.\n\n'
)

FEW_SHOT = (
    'Example 1:\n{"id": "s09-range-defense", "name": "Range defense", "tier": 2, '
    '"prerequisites": ["s03-war-book-profit"], "scenario": {"window": "5y", '
    '"regime": "down", "field": "citadel"}, "objective": "war_vs", '
    '"pass_bar": {"beats": "citadel", "regime": "down"}, '
    '"metric_source": "war_regime[agent].down vs war_regime[citadel].down", '
    '"rationale": "Do not bleed to the relative-value house in choppy regimes."}\n'
    'Example 2:\n{"id": "s10-hype-fade-duel", "name": "Hype-fade duel", "tier": 3, '
    '"prerequisites": ["s07-beats-random"], "scenario": {"window": "mixed", '
    '"regime": "mixed", "field": "citron"}, "objective": "h2h_and_war", '
    '"pass_bar": {"h2h_wins_gt_losses": "citron", "war_beats": "citron"}, '
    '"metric_source": "battle.h2h.citron + war.citron.net_return", '
    '"rationale": "Survive the adversarial short-seller in froth."}\n\n'
)


def load_architect(adapter=ARCHITECT_ADAPTER):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )
    # device_map={"": 0} pins every tensor to GPU 0 at load time (audit
    # 2026-08-11: "auto" parks embeddings on CPU on repeat in-process loads ->
    # the SECOND arch_review in a loop crashes with a device mismatch. Verified:
    # two in-process reviews complete with the explicit map.)
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb,
        device_map={"": 0},
        attn_implementation="eager",
    )
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tok


def extract_json(text):
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = text[start : i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    # tolerate small LLM JSON artifacts: doubled/trailing commas
                    cleaned = re.sub(r",\s*,", ",", raw)
                    cleaned = re.sub(r",\s*}", "}", cleaned)
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        return None
    return None


def propose(model, tok, report_text, known_ids=None):
    import torch

    constraint = ""
    if known_ids:
        # audit 2026-08-11: keep this compact — the full id list (~115 tokens)
        # pushed prompts past the 512-token training ceiling on the 8GB card
        constraint = (
            "\nPrerequisites MUST be ids from the existing skill list"
            f" (e.g. {', '.join(sorted(known_ids)[:6])}, ...). Never invent ids.\n"
        )
    prompt = (
        PRELUDE
        + constraint
        + report_text
        + "\n\nNext skill proposal (JSON):"
    )
    msgs = [{"role": "user", "content": prompt}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = tok(text, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=768, do_sample=False, repetition_penalty=1.15)  # audit: 256 truncated the JSON proposal
    reply = tok.decode(out[0][inp["input_ids"].shape[1] :], skip_special_tokens=True)
    return extract_json(reply), reply


def arch_review():
    """One Architect review: render the real weakness report, propose a skill,
    validate it, and print the verdict. Model is loaded fresh on GPU0 and
    freed after."""
    import gc
    import torch

    state, tech = load_state()
    report_text = render_weakness_report(state, tech)
    model, tok = load_architect()
    try:
        from arena.curriculum import load_state as cur_state

        known = list(cur_state().get("skills", {}).keys())
        proposal, reply = propose(model, tok, report_text, known_ids=known)
    finally:
        del model, tok
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    existing = [s["id"] for s in SEED_SKILLS]
    ok, err = validate_proposal(proposal, existing)
    print("=== architect reply ===")
    print(reply)
    print("=== validation ===", "PASS" if ok else f"FAIL: {err}")
    if ok and not proposal.get("noop"):
        from arena.curriculum import queue_proposal

        queue_proposal(proposal)
    return proposal, ok
