"""End-to-end probe of the locally-trained Architect.

Loads qwen-2.5-7b-Instruct 4-bit + the locally-trained architect LoRA on
GPU0, renders the real weakness report from the arena state, asks the model
for the next skill, and validates the JSON proposal. No cloud, no llama.cpp
needed — proves the trained artifact works on hardware.
"""

import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from arena.architect import load_state, render_weakness_report, validate_proposal

ADAPTER = PROJECT / "data/gpu_scheduler/adapters/architect"
PRELUDE = (
    "You are the Curriculum Architect for the Momentum trading agent. Read the "
    "weakness report and propose the single next skill that sharpens the agent's "
    "trading ability. Output ONLY a JSON object matching this schema: "
    "{id, name, tier, prerequisites, scenario{window,regime,field}, objective, "
    "pass_bar, metric_source, rationale} with numeric pass bars. If no new skill "
    'is warranted, output {"noop": true, "rationale": "..."}.\n\n'
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
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    state, tech = load_state()
    report = render_weakness_report(state, tech)
    prompt = PRELUDE + FEW_SHOT + report + "\n\nNext skill proposal (JSON):"
    print("=== weakness report ===")
    print(report)

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb,
        device_map="auto",
        attn_implementation="eager",
    )
    model = PeftModel.from_pretrained(model, ADAPTER)
    model.eval()

    msgs = [{"role": "user", "content": prompt}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    inp = tok(text, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=256, do_sample=False)
    reply = tok.decode(out[0][inp["input_ids"].shape[1] :], skip_special_tokens=True)
    print("=== architect reply ===")
    print(reply)

    proposal = extract_json(reply)
    existing = [
        s["id"]
        for s in __import__("arena.architect", fromlist=["SEED_SKILLS"]).SEED_SKILLS
    ]
    ok, err = validate_proposal(proposal, existing)
    print("=== validation ===", "PASS" if ok else f"FAIL: {err}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
