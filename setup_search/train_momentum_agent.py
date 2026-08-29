#!/usr/bin/env python3
"""Train the first in-house MoT agent: MOMENTUM (wayfinder #51).

A QLoRA fine-tune of a base LLM (hermes-3-8b) on momentum-trading decisions
derived from the validated rule config's candidates: given a technical +
regime context, decide take/skip. The correct label comes from the realized
10-day forward return. Trained on GPU0 (the arsenal), then validated against
the holdout gate before it earns MoT weight.

Usage: python3 -m setup_search.train_momentum_agent --steps 24 --examples 400
"""

import argparse
import json
import random
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

# audit 2026-08-11: the caching allocator fragments across the training loop
# on the 8GB card (multi-GB reserved-but-unallocated) -> OOM mid-epoch.
# expandable_segments lets segments grow/shrink instead of fragmenting.
import os

os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

BASE = "Qwen/Qwen2.5-7B-Instruct"
OUT = PROJECT / "data" / "gpu_scheduler" / "adapters" / "momentum-agent"


def build_dataset(n_examples: int, seed: int = 11):
    import numpy as np
    from setup_search.core import clamp_config
    from setup_search.data import REGIME_SYM, load_ohlcv, align
    from setup_search.engine import _features, _score_at

    base = clamp_config(
        json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"]
    )
    data = load_ohlcv("5y")
    al = align(data, list(data.keys()))
    spy = al[0].get(REGIME_SYM)
    spy_ma200 = spy.rolling(200, min_periods=60).mean()
    feat = _features(al[0], al[1], al[2], al[3], base)
    w = base
    FORWARD = 10
    rows = []
    for sym in sorted(al[0].keys()):
        if sym == REGIME_SYM:
            continue
        c, f = al[0][sym], feat[sym]
        score = (
            w["w_mom"] * f["mom"]
            + w["w_rev"] * f["rev"]
            + w["w_rsi"] * f["rsi"]
            + w["w_brk"] * f["brk"]
            + w["w_z"] * f["z"]
        )
        fwd = (c.shift(-FORWARD) / c - 1.0).values
        for t in range(60, len(c) - FORWARD):
            s = score.iloc[t]
            if s != s or s < -0.3:
                continue
            d = c.index[t]
            regime = "up" if (spy[d] > spy_ma200[d]) else "down"
            recent = " -> ".join(f"{v:,.0f}" for v in c.iloc[t - 5 : t + 1])
            decision = "TAKE" if fwd[t] > 0 else "SKIP"
            prompt = (
                f"[Market context]\nSymbol: {sym}\nRegime (SPY vs 200d): {regime}\n"
                f"Momentum score: {s:.3f} (threshold 0.28)\nRecent closes: {recent}\n\n"
                f"Decision (TAKE or SKIP this long entry):"
            )
            rows.append({"prompt": prompt, "decision": decision, "fwd": float(fwd[t])})
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:n_examples]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--examples", type=int, default=400)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument(
        "--dataset",
        default=None,
        help="JSONL of {prompt, decision} rows (arena export) instead of build_dataset",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="override the adapter output directory (default: gpu_scheduler/adapters/momentum-agent)",
    )
    ap.add_argument(
        "--max-length",
        type=int,
        default=64,
        help="token truncation length (architect prompts are ~950 chars; "
             "audit 2026-08-11: the 64-token default truncated them to nothing)",
    )
    args = ap.parse_args()
    global OUT
    if args.out_dir:
        OUT = PROJECT / args.out_dir

    import torch
    import pandas as pd
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, get_peft_model

    print(
        "GPU0 free VRAM:",
        round(torch.cuda.mem_get_info()[0] / 1e9, 2),
        "GB",
        flush=True,
    )
    if args.dataset:
        import json as _json

        with open(args.dataset) as f:
            rows = [_json.loads(line) for line in f if line.strip()]
        print(
            f"[mom] loaded {len(rows)} arena-labeled examples from {args.dataset}",
            flush=True,
        )
    else:
        rows = build_dataset(args.examples)
    pos = sum(1 for r in rows if r["decision"] == "TAKE")
    print(
        f"[mom] {len(rows)} examples ({pos} TAKE / {len(rows) - pos} SKIP)",
        flush=True,
    )

    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
    tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2.5-7B-Instruct",
        quantization_config=bnb,
        device_map="auto",
        attn_implementation="eager",
    )
    lora = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_dropout=0.05,
    )
    model = get_peft_model(model, lora).to("cuda")
    model.gradient_checkpointing_enable()

    texts = [
        f"<|im_start|>user\n{r['prompt']}<|im_end|>\n<|im_start|>assistant\n{r['decision']}<|im_end|>"
        for r in rows
    ]
    # audit 2026-08-11: tokenizing ALL rows at once with padding=True pads every
    # row to the LONGEST sequence (~703 tok with the new architect reports),
    # blowing the 8GB card. Tokenize per batch instead so each example runs at
    # its own natural length (and matches inference, where the decision follows
    # the prompt directly).
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    lossf = torch.nn.CrossEntropyLoss()
    model.train()
    n_batches = max((len(texts) + args.batch - 1) // args.batch, 1)
    printed = 0
    for epoch in range(args.epochs):
        total = 0.0
        for i in range(0, len(texts), args.batch):
            chunk = texts[i : i + args.batch]
            b = tok(chunk, truncation=True, max_length=args.max_length, padding=True,
                    return_tensors="pt")
            b = {k: v.to("cuda") for k, v in b.items()}
            # audit 2026-08-11: mask the prompt — only the assistant decision
            # contributes loss (full-sequence labels made the adapter memorize
            # the prompt and degenerate into token loops at inference)
            labels = b["input_ids"].clone()
            if tok.chat_template is not None:
                lbl = labels[0].tolist()
                asst = tok("<|im_start|>assistant\n", add_special_tokens=False)["input_ids"]
                try:
                    first = next(i for i in range(len(lbl) - len(asst) + 1)
                                 if lbl[i:i + len(asst)] == asst)
                    labels[:, : first + len(asst)] = -100
                except StopIteration:
                    pass
            out = model(**b, labels=labels)
            loss = out.loss / n_batches
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
            printed += 1
            if printed % 10 == 0:
                print(f"[mom] iter {printed} loss {total:.3f}", flush=True)
        print(f"[mom] epoch {epoch} loss {total:.3f}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT)
    tok.save_pretrained(OUT)
    (OUT / "summary.json").write_text(
        json.dumps(
            {"base": BASE, "examples": len(rows), "take_pct": pos / len(rows)}, indent=1
        )
    )
    print(f"[mom] adapter saved -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
