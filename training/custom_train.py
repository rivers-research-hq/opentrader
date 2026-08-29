#!/usr/bin/env python3
"""Custom QLoRA fine-tune for Cartographer adapters.

Bypasses Unsloth to avoid OOM during model loading.
Uses transformers + bitsandbytes + PEFT directly with 4-bit quantization.

Usage:
    ~/rocm_venv/bin/python3 training/custom_train.py \
        --version Ptolemy-S1 \
        --base Qwen/Qwen2.5-7B-Instruct \
        --data data/training/training_data_combined.jsonl \
        --epochs 3 --batch-size 1 --grad-accum 8 --lora-r 8

The --base default is the single source of truth (config/models.json, via
training/model_config.py); passing --base overrides it.
"""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("opentrader.custom_train")

# Must import torch before transformers
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import TrainerCallback

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
from training.model_config import BASE_MODEL


def load_dataset(path: str) -> list:
    """Load ShareGPT-formatted training data."""
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / path
    examples = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            # ShareGPT format: {"conversations": [{"from":"human","value":"..."}, ...]}
            convs = obj.get("conversations", [])
            if len(convs) < 2:
                continue
            examples.append(obj)
    logger.info("Loaded %d examples from %s", len(examples), p)
    return examples


def format_example(example: dict, tokenizer) -> str:
    """Convert ShareGPT conversation to chat-formatted text."""
    convs = example.get("conversations", [])
    messages = []
    for turn in convs:
        role = turn.get("role", turn.get("from", ""))
        content = turn.get("content", turn.get("value", ""))
        role_map = {"human": "user", "gpt": "assistant", "system": "system"}
        role = role_map.get(role, role)
        messages.append({"role": role, "content": content})

    # Use Qwen chat template
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    return text


def tokenize_dataset(examples: list, tokenizer, max_length: int = 2048) -> list:
    """Tokenize formatted examples."""
    tokenized = []
    for ex in examples:
        text = format_example(ex, tokenizer)
        enc = tokenizer(
            text,
            truncation=True,
            max_length=max_length,
            padding=False,
            return_tensors=None,
        )
        tokenized.append({"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]})
    logger.info("Tokenized %d examples (max_length=%d)", len(tokenized), max_length)
    return tokenized


def train(
    base_model: str,
    data_path: str,
    version: str,
    epochs: int = 3,
    batch_size: int = 1,
    grad_accum: int = 8,
    lora_r: int = 8,
    lora_alpha: int = 16,
    lora_dropout: float = 0.05,
    learning_rate: float = 2e-4,
    max_length: int = 2048,
    warmup_steps: int = 10,
    save_steps: int = 50,
):
    """Run QLoRA training and save adapter."""
    output_dir = BASE_DIR / "models" / "finetune" / version
    output_dir.mkdir(parents=True, exist_ok=True)
    status_file = output_dir / "status.json"

    # Write initial status
    _write_status(status_file, "loading", base_model, version, 0, "Loading base model...")
    logger.info("Training %s from %s", version, base_model)
    logger.info("Output: %s", output_dir)

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Configure 4-bit quantization
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    logger.info("Loading base model with 4-bit quantization...")
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )
    model = prepare_model_for_kbit_training(model)
    logger.info("Model loaded. VRAM allocated: %.2f GB", torch.cuda.memory_allocated() / 1e9)

    # Apply LoRA
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=target_modules,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Load and tokenize data
    examples = load_dataset(data_path)
    tokenized = tokenize_dataset(examples, tokenizer, max_length=max_length)

    # Data collator with padding
    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    # Training arguments
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        warmup_steps=warmup_steps,
        learning_rate=learning_rate,
        logging_steps=5,
        save_steps=save_steps,
        save_total_limit=3,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch",
        lr_scheduler_type="cosine",
        report_to=[],
        remove_unused_columns=False,
    )

    # Custom callback for status updates
    class StatusCallback(TrainerCallback):
        def __init__(self):
            self.step = 0

        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                loss = logs.get("loss", 0)
                logger.info("Step %d: loss=%.4f", state.global_step, loss)
                _write_status(status_file, "training", base_model, version,
                              state.global_step, f"loss={loss:.4f}")

    callback = StatusCallback()

    # Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=data_collator,
        callbacks=[callback],
    )

    # Train
    _write_status(status_file, "training", base_model, version, 0, "Training started")
    t0 = time.time()
    train_result = trainer.train()
    elapsed = time.time() - t0
    logger.info("Training complete in %.1f minutes", elapsed / 60)

    # Save adapter
    model.save_pretrained(str(output_dir / "adapter"))
    tokenizer.save_pretrained(str(output_dir / "adapter"))
    logger.info("Adapter saved to %s", output_dir / "adapter")

    # Write final status
    final_loss = train_result.training_loss
    _write_status(status_file, "completed", base_model, version, 0,
                  f"loss={final_loss:.4f}", final_loss=final_loss)

    return final_loss


def _write_status(path, status, base_model, version, step, message,
                  final_loss=None):
    data = {
        "status": status,
        "base_model": base_model,
        "version": version,
        "step": step,
        "message": message,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if final_loss is not None:
        data["final_loss"] = final_loss
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Custom QLoRA training (no Unsloth)")
    parser.add_argument("--version", default="Ptolemy-S1", help="Adapter version name")
    parser.add_argument("--base", default=BASE_MODEL, help="Base HF model name")
    parser.add_argument("--data", default="data/training/training_data_combined.jsonl")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level,
                        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    logger.info("Starting custom training: %s from %s", args.version, args.base)
    logger.info("Data: %s, epochs=%d, batch=%d, grad_accum=%d, lora_r=%d",
                args.data, args.epochs, args.batch_size, args.grad_accum, args.lora_r)

    try:
        loss = train(
            base_model=args.base,
            data_path=args.data,
            version=args.version,
            epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            lora_r=args.lora_r,
            lora_alpha=args.lora_alpha,
            learning_rate=args.lr,
            max_length=args.max_length,
        )
        logger.info("Training complete. Final loss: %.4f", loss)
        print(json.dumps({"status": "completed", "final_loss": loss, "version": args.version}))
        sys.exit(0)
    except Exception as e:
        logger.error("Training failed: %s", e, exc_info=True)
        # Write error status
        status_file = BASE_DIR / "models" / "finetune" / args.version / "status.json"
        _write_status(status_file, "failed", args.base, args.version, 0, str(e))
        print(json.dumps({"status": "failed", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()