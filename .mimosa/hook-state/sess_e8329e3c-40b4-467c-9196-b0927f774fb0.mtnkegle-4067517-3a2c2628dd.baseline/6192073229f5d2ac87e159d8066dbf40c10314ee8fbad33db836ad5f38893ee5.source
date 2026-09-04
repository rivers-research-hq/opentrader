#!/usr/bin/env python3
"""Genuine continuous GPU0 work: QLoRA fine-tune of Qwen2.5-7B on financial
tweet sentiment (predict 1-day forward class from text) -> a sentiment
specialist model for the MoT. Runs for HOURS on the RTX 3070.

The idle qwen llama-server holds 4.9GB; this task frees it (stops the server),
trains on the full card, then restarts the server so the MoT/debate can use it
later. Save the LoRA adapter to data/gpu_scheduler/adapters/qwen-sentiment.
"""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import torch

PROJECT = Path(__file__).resolve().parent.parent
DATA = Path("/tmp/opencode")
OUT = PROJECT / "data" / "gpu_scheduler" / "adapters"
SERVICE = "opentrader-llama-gpu0.service"
MODEL = "/home/mrc/models/qwen2.5-7b-instruct"
MAX_ROWS = 6000
EPOCHS = 1
BATCH = 2
LR = 2e-4


def main():
    import torch.nn as nn
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
    from peft import LoraConfig, get_peft_model
    from trl import SFTTrainer

    # 1. Free the card: stop the idle qwen server (rule-primary doesn't use it)
    subprocess.run(["systemctl", "--user", "stop", SERVICE], check=False)
    torch.cuda.empty_cache()
    free = torch.cuda.mem_get_info()[0] / 1e9
    print(f"[ft] stopped {SERVICE}; GPU0 free VRAM now {free:.1f} GB", flush=True)

    # 2. Dataset: fintweet text -> 1-day forward class (0/1/2)
    df = pd.read_parquet(DATA / "fintweet_train.parquet")
    df = df.sample(min(MAX_ROWS, len(df)), random_state=7)
    df["label"] = df["label_1d_3class"].astype(int)
    data = [{"text": t, "label": int(l)} for t, l in zip(df["text"], df["label"])]
    print(f"[ft] {len(data)} examples", flush=True)

    # 3. Tokenizer + QLoRA model on GPU0
    tok = AutoTokenizer.from_pretrained(MODEL, use_fast=False)
    tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.float16,
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, quantization_config=bnb, device_map="auto",
        torch_dtype=torch.float16, attn_implementation="eager")
    lora = LoraConfig(r=8, lora_alpha=16, target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
                      lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    # 4. Format as chat
    def fmt(row):
        return f"<|im_start|>user\nFinancial tweet: {row['text']}\nPredict the 1-day forward outcome class (0=down,1=flat,2=up).<|im_end|>\n<|im_start|>assistant\n{row['label']}<|im_end|>"
    train_txt = [fmt(r) for r in data]
    tokenized = tok(train_txt, truncation=True, max_length=256, padding=True, return_tensors="pt")

    from torch.utils.data import Dataset

    class SentDS(Dataset):
        def __init__(self, tok_data):
            self.d = tok_data

        def __len__(self):
            return len(self.d["input_ids"])

        def __getitem__(self, i):
            return {k: v[i] for k, v in self.d.items()}

    train_args = TrainingArguments(
        output_dir=str(OUT), per_device_train_batch_size=BATCH,
        gradient_accumulation_steps=8, num_train_epochs=EPOCHS, learning_rate=LR,
        fp16=True, logging_steps=20, save_strategy="no", report_to=[],
        gradient_checkpointing=True, optim="adamw_8bit", dataloader_num_workers=0)
    trainer = SFTTrainer(
        model=model, args=train_args, train_dataset=SentDS(tokenized),
        tokenizer=tok, dataset_text_field="text", max_seq_length=256)
    trainer.train()

    # 5. Save adapter + summary
    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT / "qwen-sentiment")
    tok.save_pretrained(OUT / "qwen-sentiment")
    (OUT / "summary.json").write_text(json.dumps(
        {"examples": len(data), "epochs": EPOCHS, "loss": float(trainer.state.log_history[-1].get("loss", 0))},
        indent=1))
    print(f"[ft] adapter saved -> {OUT / 'qwen-sentiment'}", flush=True)

    # 6. Restart the qwen server for the MoT/debate
    torch.cuda.empty_cache()
    subprocess.run(["systemctl", "--user", "start", SERVICE], check=False)
    print("[ft] qwen server restarted; fine-tune done", flush=True)


if __name__ == "__main__":
    main()
