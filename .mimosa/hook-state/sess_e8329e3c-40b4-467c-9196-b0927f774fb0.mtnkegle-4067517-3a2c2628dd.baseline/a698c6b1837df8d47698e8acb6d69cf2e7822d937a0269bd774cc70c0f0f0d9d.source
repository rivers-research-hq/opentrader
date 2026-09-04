#!/usr/bin/env python3
"""DPO Trainer — fine-tunes the trading agent with Direct Preference Optimization.

Uses Unsloth + TRL DPOTrainer on preference pairs from dpo_builder.py.
Designed to run as a subprocess from the harness or scheduler.
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("opentrader.dpo_trainer")

from training.model_config import BASE_MODEL as DEFAULT_BASE_MODEL
DPO_OUTPUT_DIR = "models/finetune"
STATUS_FILE = "dpo_status.json"
MIN_PAIRS = 10


def run_dpo_train(
    state_dir: str,
    data_path: str = None,
    version: str = None,
    epochs: int = 1,
    batch_size: int = 1,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 1024,
    lora_r: int = 8,
    lora_alpha: int = 8,
) -> Dict:
    """Run DPO fine-tuning on the base model using preference pairs.

    Args:
        state_dir: Path to data directory containing training data.
        data_path: Path to DPO JSONL file (auto-discovered if not set).
        version: Model version name (auto-incremented if not set).
        epochs, batch_size, grad_accum: Training hyperparameters.
        learning_rate: Peak learning rate for LoRA.
        max_seq_length: Max token sequence length.
        lora_r, lora_alpha: LoRA rank and alpha.

    Returns:
        Status dict with keys: status, version, output_dir, error, duration_s.
    """
    t0 = time.time()
    try:
        import torch
        from unsloth import FastLanguageModel
        from trl import DPOTrainer
        from transformers import TrainingArguments
        from datasets import Dataset as HFDataset
    except ImportError as e:
        msg = f"Missing dependencies: {e}. Install with: pip install unsloth trl datasets"
        logger.error(msg)
        return {"status": "error", "error": msg, "duration_s": 0}

    state_path = Path(state_dir)
    training_dir = state_path / "training"

    # Discover data file
    if data_path is None:
        dpo_file = training_dir / "dpo_training_data.jsonl"
        if not dpo_file.exists():
            return {"status": "skipped", "reason": "No DPO data file found", "duration_s": 0}
        data_path = str(dpo_file)

    if not os.path.exists(data_path):
        return {"status": "skipped", "reason": f"Data file not found: {data_path}", "duration_s": 0}

    pairs = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))

    if len(pairs) < MIN_PAIRS:
        return {"status": "skipped", "reason": f"Only {len(pairs)} pairs (need {MIN_PAIRS}+)", "duration_s": 0}

    logger.info("Loading %d DPO preference pairs", len(pairs))

    # Auto-increment version
    if version is None:
        out_root = state_path.parent / DPO_OUTPUT_DIR
        out_root.mkdir(parents=True, exist_ok=True)
        existing = [d for d in out_root.iterdir() if d.is_dir() and d.name.startswith("DPO-")]
        version = f"DPO-{len(existing) + 1}"

    output_dir = state_path.parent / DPO_OUTPUT_DIR / version
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("DPO fine-tune: version=%s pairs=%d epochs=%d lora_r=%d", version, len(pairs), epochs, lora_r)

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=DEFAULT_BASE_MODEL,
            max_seq_length=max_seq_length,
            dtype=None,
            load_in_4bit=True,
        )
    except Exception as e:
        logger.warning("Could not load %s: %s — trying cached model", DEFAULT_BASE_MODEL, e)
        return {"status": "error", "error": str(e), "duration_s": time.time() - t0}

    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.pad_token_id = tokenizer.eos_token_id

    dpo_dataset = HFDataset.from_list(pairs)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        num_train_epochs=epochs,
        learning_rate=learning_rate,
        logging_steps=1,
        save_strategy="no",
        remove_unused_columns=False,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        report_to="none",
    )

    dpo_trainer = DPOTrainer(
        model=model,
        args=training_args,
        train_dataset=dpo_dataset,
        tokenizer=tokenizer,
        max_length=max_seq_length,
        max_prompt_length=max_seq_length // 2,
    )

    logger.info("Starting DPO training...")
    train_result = dpo_trainer.train()

    # Save LoRA adapter
    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    elapsed = time.time() - t0

    # Write training metadata
    meta = {
        "version": version,
        "base_model": DEFAULT_BASE_MODEL,
        "training_type": "dpo",
        "preference_pairs": len(pairs),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(elapsed, 1),
    }
    with open(output_dir / "training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    result = {
        "status": "completed",
        "version": version,
        "output_dir": str(output_dir),
        "pairs": len(pairs),
        "epochs": epochs,
        "duration_s": round(elapsed, 1),
    }
    logger.info("DPO training completed: %s (%ds)", version, elapsed)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run DPO fine-tuning on preference pairs")
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--data", default=None, help="Path to DPO JSONL file")
    parser.add_argument("--version", default=None, help="Model version name")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--lora-r", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=8)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    state_dir = Path(args.state_dir)
    if not state_dir.is_absolute():
        state_dir = Path(__file__).resolve().parent.parent / args.state_dir

    result = run_dpo_train(
        str(state_dir),
        data_path=args.data,
        version=args.version,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        max_seq_length=args.max_seq_length,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
    )

    status_path = state_dir / "training" / STATUS_FILE
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
