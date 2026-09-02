#!/usr/bin/env python3
"""Validate the Momentum agent: does it discriminate TAKE vs SKIP on held-out
candidates? Loads the trained LoRA (qwen2.5-7b base), judges a held-out
candidate sample, compares TAKE'd forward returns vs all (the holdout bar)."""

import json
import re
import statistics
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
ADAPTER = PROJECT / "data" / "gpu_scheduler" / "adapters" / "momentum-agent"


def main():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    base = "Qwen/Qwen2.5-7B-Instruct"
    tok = AutoTokenizer.from_pretrained(base)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16)
    model = AutoModelForCausalLM.from_pretrained(base, quantization_config=bnb,
                                                 device_map="auto", torch_dtype=torch.float16)
    model = PeftModel.from_pretrained(model, str(ADAPTER)).to("cuda")
    model.eval()

    # held-out candidates from 2026 (recent, unseen by training which used 2021-25)
    from setup_search.core import clamp_config
    from setup_search.data import REGIME_SYM, load_ohlcv, align
    from setup_search.engine import _features, _score_at
    base_cfg = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, list(data.keys()))
    spy = al[0].get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean()
    feat = _features(al[0], al[1], al[2], al[3], base_cfg)
    w = base_cfg
    FORWARD = 10
    cands = []
    for sym in sorted(al[0].keys()):
        if sym == REGIME_SYM or str(al[0][sym].index[-1])[:4] != "2026":
            continue
        c, f = al[0][sym], feat[sym]
        score = (w["w_mom"] * f["mom"] + w["w_rev"] * f["rev"] + w["w_rsi"] * f["rsi"]
                 + w["w_brk"] * f["brk"] + w["w_z"] * f["z"])
        fwd = (c.shift(-FORWARD) / c - 1.0).values
        for t in range(60, len(c) - FORWARD):
            s = score.iloc[t]
            if s != s or s < -0.3:
                continue
            d = c.index[t]
            if str(d)[:7] < "2026-01" or str(d)[:7] > "2026-05":
                continue
            regime = "up" if (spy[d] > spy_ma200[d]) else "down"
            recent = " -> ".join(f"{v:,.0f}" for v in c.iloc[t - 5:t + 1])
            prompt = (f"[Market context]\nSymbol: {sym}\nRegime (SPY vs 200d): {regime}\n"
                      f"Momentum score: {s:.3f} (threshold 0.28)\nRecent closes: {recent}\n\n"
                      f"Decision (TAKE or SKIP this long entry):")
            cands.append({"prompt": prompt, "fwd": float(fwd[t])})
        cands = cands[:200]
    print(f"[val] {len(cands)} held-out 2026 candidates (sampled)", flush=True)

    taken, skipped = [], []
    for c in cands:
        msgs = [{"role": "user", "content": c["prompt"]}]
        enc = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                       return_tensors="pt")
        ids = enc["input_ids"].to("cuda") if hasattr(enc, "input_ids") else enc.to("cuda")
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=4, do_sample=False, pad_token_id=tok.eos_token_id)
        txt = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
        take = "TAKE" in txt.upper()
        (taken if take else skipped).append(c["fwd"])

    all_m = statistics.mean(c["fwd"] for c in cands)
    take_m = statistics.mean(taken) if taken else 0.0
    skip_m = statistics.mean(skipped) if skipped else 0.0
    margin = take_m - all_m
    print(f"all-mean={all_m:+.2%}  TAKE-mean={take_m:+.2%}  SKIP-mean={skip_m:+.2%}")
    print(f"discrimination (TAKE-mean - all-mean) = {margin:+.2%}")
    verdict = "PASS - agent discriminates" if margin > 0.005 else "FAIL - agent not discriminating yet"
    print(f"verdict: {verdict}")
    out = PROJECT / "data" / "research_gate" / "momentum_agent_validation.json"
    out.write_text(json.dumps({"n": len(cands), "taken": len(taken), "all_m": all_m,
                               "take_m": take_m, "margin": margin, "verdict": verdict}, indent=1))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
