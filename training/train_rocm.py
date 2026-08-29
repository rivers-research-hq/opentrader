#!/usr/bin/env python3
"""ROCm-compatible SFT QLoRA fine-tuning for AMD GPUs.

Uses transformers + peft + bitsandbytes + TRL SFTTrainer.
No Unsloth dependency — pure OSS stack for ROCm.

Usage:
    /home/mrc/rocm_venv/bin/python3 training/train_rocm.py \
        --base Qwen/Qwen2.5-7B-Instruct \
        --data data/training/training_data_legacy.jsonl \
        --output models/finetune/Ptolemy-S0 \
        --epochs 2
"""
import argparse
import json
import logging
import os
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from trl import SFTConfig

from training.model_config import BASE_MODEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("train_rocm")


def _check_bnb_works() -> bool:
    try:
        import bitsandbytes as bnb
        bnb.version.__version__
        return True
    except Exception:
        return False


def _check_rocm() -> tuple:
    if not torch.cuda.is_available():
        return False, "No CUDA/ROCm device"
    dev = torch.cuda.get_device_name(0) or "unknown"
    mem = torch.cuda.get_device_properties(0).total_memory / 1e9
    return True, f"{dev} ({mem:.1f} GB)"


def load_dataset(data_path: str) -> Dataset:
    examples = []
    with open(data_path) as f:
        for line in f:
            if line.strip():
                ex = json.loads(line)
                convs = ex.get("conversations", [])
                text = ""
                for turn in convs:
                    role = turn.get("from", turn.get("role", "user"))
                    role_map = {"human": "user", "gpt": "assistant", "system": "system"}
                    role = role_map.get(role, role)
                    text += f"{role}: {turn.get('content', turn.get('value', ''))}\n"
                examples.append({"text": text})
    logger.info(f"Loaded {len(examples)} examples from {data_path}")
    return Dataset.from_list(examples)


def train(
    data_path: str,
    output_dir: str,
    base_model: str = BASE_MODEL,
    use_4bit: bool = True,
    epochs: int = 2,
    batch_size: int = 1,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 1024,
    lora_r: int = 8,
    lora_alpha: int = 8,
) -> dict:
    result = {"status": "started", "output_dir": output_dir, "base_model": base_model}
    start = time.time()
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    ok, info = _check_rocm()
    if not ok:
        raise RuntimeError(f"No ROCm GPU: {info}")
    logger.info(f"GPU: {info}")

    ds = load_dataset(data_path)
    result["examples"] = len(ds)
    if len(ds) == 0:
        raise ValueError("Dataset is empty")

    bnb_works = _check_bnb_works() if use_4bit else False
    use_4bit_effective = bnb_works or use_4bit  # Force 4-bit on ROCm even if bnb check lies

    if use_4bit_effective:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=False,
        )
        logger.info(f"Loading {base_model} (4-bit QLoRA)...")
        try:
            model = AutoModelForCausalLM.from_pretrained(
                base_model,
                device_map="auto",
                quantization_config=bnb_config,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16,
            )
            logger.info("4-bit model loaded successfully")
        except Exception as e:
            logger.warning(f"4-bit load failed ({e}), falling back to bfloat16 + GC")
            use_4bit_effective = False

    if not use_4bit_effective:
        logger.info(f"Loading {base_model} (bfloat16 + gradient checkpointing)...")
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
        )
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
        bf16_enabled = True

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    logger.info(f"Trainable params: {trainable:,} / {total:,} ({100*trainable/total:.1f}%)")

    effective_batch = batch_size * grad_accum
    logger.info(f"Effective batch size: {effective_batch} ({batch_size} x {grad_accum})")

    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        logging_steps=max(1, min(10, len(ds) // effective_batch)),
        save_strategy="epoch",
        bf16=bf16_enabled,
        optim="adamw_8bit" if bnb_works else "adamw_torch",
        max_grad_norm=0.3,
        remove_unused_columns=False,
        report_to="none",
        dataloader_num_workers=0,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_pin_memory=False,
    )

    model.config.use_cache = False

    from trl import SFTTrainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=ds,
        processing_class=tokenizer,
        formatting_func=lambda ex: ex["text"],
    )

    logger.info(f"Training {epochs} epoch(s) on {len(ds)} examples...")
    train_result = trainer.train()

    adapter_path = os.path.join(output_dir, "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info(f"Saved adapter to {adapter_path}")

    # Test generation
    logger.info("Testing generation...")
    model.eval()
    test_prompt = (
        "user: Market data: BTC/USDT $64124, portfolio $100, regime trending.\n"
        "You are a trading agent. Output a SIGNAL line with BUY/SELL/HOLD.\n"
        "assistant: SIGNAL: "
    )
    inputs = tokenizer(test_prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=80,
            temperature=0.7,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    gen_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    logger.info(f"Test output: {gen_text[-200:]}")

    duration = time.time() - start
    result["status"] = "completed"
    result["duration_s"] = round(duration, 1)
    result["output_path"] = adapter_path
    result["trainable_params"] = trainable
    result["bnb_4bit"] = bnb_works
    result["loss"] = round(float(train_result.training_loss or 0), 4)

    status_path = os.path.join(output_dir, "status.json")
    with open(status_path, "w") as f:
        json.dump(result, f)
    logger.info(f"Training complete in {duration/60:.1f} min: {result}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE_MODEL, help="Base HF model name")
    parser.add_argument("--data", default="data/training/training_data_legacy.jsonl")
    parser.add_argument("--output", default="models/finetune/Ptolemy-S0")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=8)
    parser.add_argument("--no-4bit", action="store_true")
    args = parser.parse_args()

    train(
        data_path=args.data,
        output_dir=args.output,
        base_model=args.base,
        use_4bit=not args.no_4bit,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        max_seq_length=args.max_seq_len,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
    )


if __name__ == "__main__":
    main()
