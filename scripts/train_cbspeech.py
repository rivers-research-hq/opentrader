#!/usr/bin/env python3
"""T6 — QLoRA fine-tune of Granite 4.2-8B on the labeled CB-speech corpus.

Loads ibm-granite/granite-4.2-8b in 4-bit (bitsandbytes NF4), formats the
labeled corpus as instruction examples (user = bank/speech/stress, assistant =
the Warden's strict-JSON expectation), and trains a LoRA adapter. Precedent:
Ptolemy-1 (data/models/finetune/Ptolemy-1: lora_r=8, lora_alpha=8, lr=2e-4,
batch=1, max_seq=1024, RTX 3070).

Run with the rocm venv (has transformers/peft/bitsandbytes):
  /home/mrc/rocm_venv/bin/python3 scripts/train_cbspeech.py \
    --data /home/mrc/opentrader-data/feeds/cbspeeches/corpus_labeled.jsonl \
    --out /home/mrc/opentrader/data/models/finetune/warden-cbft1
"""

import argparse
import json
from pathlib import Path

import torch
from transformers import (AutoTokenizer, AutoModelForCausalLM, TrainingArguments,
                          Trainer, DataCollatorForLanguageModeling, BitsAndBytesConfig)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

BASE = "/home/mrc/models/granite-4.2-8b-hf"

SYSTEM = ("You are the Warden: a bounded monitor for an FX practice account. "
          "Given a central-bank speech and a stress snapshot, set the EXPECTED "
          "weekly P&L (account %, e.g. 0.1 = +0.1%) for the speech's currency. "
          "Return STRICT JSON only: "
          '{"expected_pnl_pct": <float>, "direction": "long_bias|short_bias|flat", '
          '"rationale": "<one sentence>"}. CITE ONLY the numbers given; never '
          "compute or invent a percentage.")


def build_examples(docs, max_text=1500):
    """Instruction examples: user prompt + assistant (Warden JSON) target."""
    out = []
    for d in docs:
        if d.get("ret_5d") is None:
            continue
        ret = float(d["ret_5d"])
        exp = ret * 100.0  # fractional -> account %
        direction = ("long_bias" if ret > 0.001 else
                     "short_bias" if ret < -0.001 else "flat")
        stress = {k: d.get(k) for k in d if k.startswith("stress_")}
        user = (f"bank: {d.get('bank')} | date: {d.get('date')}\n"
                f"speech title: {(d.get('title') or '')[:200]}\n"
                f"speech text: {(d.get('text') or '')[:max_text]}\n"
                f"stress snapshot: {json.dumps(stress)}")
        assistant = json.dumps({
            "expected_pnl_pct": round(exp, 2),
            "direction": direction,
            "rationale": f"{d.get('bank')} speech dated {d.get('date')}, 5d outcome {ret*100:+.2f}%",
        })
        out.append({"user": user, "assistant": assistant})
    return out


def format_text(ex, tok):
    """Format one example as a causal-LM training sequence."""
    prompt = f"{SYSTEM}\n\nUser: {ex['user']}\nAssistant: "
    target = ex["assistant"] + tok.eos_token
    return prompt + target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq", type=int, default=512)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--year-lt", default=None,
                    help="train only on docs dated strictly before this year "
                         "(temporal holdout; e.g. 2025 keeps 2025+ out of train)")
    a = ap.parse_args()

    docs = [json.loads(l) for l in open(a.data) if l.strip()]
    if a.year_lt:
        before = len(docs)
        docs = [d for d in docs if str(d.get("date", ""))[:4] < a.year_lt]
        print(f"[train] temporal split: {len(docs)}/{before} docs dated < {a.year_lt}")
    exs = build_examples(docs)
    if a.limit:
        exs = exs[:a.limit]
    print(f"[train] {len(exs)} training examples")

    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE, quantization_config=bnb, dtype=torch.bfloat16,
        device_map="auto", trust_remote_code=True)
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=8, lora_alpha=8, lora_dropout=0.05, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    # shrink activation memory so the 8B 4-bit model fits the 8GB 3070
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    model.gradient_checkpointing_enable()
    model.print_trainable_parameters()

    def tokenize(ex):
        text = format_text(ex, tok)
        return tok(text, truncation=True, max_length=a.max_seq)

    enc = [tokenize(e) for e in exs]

    # build a HuggingFace Dataset from the encodings
    from datasets import Dataset
    ds = Dataset.from_dict({"input_ids": [e["input_ids"] for e in enc],
                            "attention_mask": [e["attention_mask"] for e in enc]})

    args = TrainingArguments(
        output_dir=str(Path(a.out).parent / (Path(a.out).name + "_ckpt")),
        per_device_train_batch_size=a.batch,
        gradient_accumulation_steps=4,
        learning_rate=a.lr,
        num_train_epochs=a.epochs,
        logging_steps=5,
        save_strategy="no",
        bf16=True,
        report_to=[],
    )
    trainer = Trainer(
        model=model, args=args, train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tok, mlm=False),
    )
    trainer.train()
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print(f"[train] saved adapter -> {a.out}")


if __name__ == "__main__":
    main()
