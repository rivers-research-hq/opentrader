#!/usr/bin/env python3
"""Auto fine-tuning for OpenTrader — uses Unsloth + QLoRA to fine-tune
the trading agent from reflection log data.

Designed to be triggered by the MoT (Model of Traders) when:
  1. The MoT evaluation score drops below threshold
  2. Enough resolved reflections have accumulated (default: 10+)
  3. Not already training

Runs as an optional subprocess so it doesn't block the harness loop,
or can be called in-process by the FlashTrainer for quick runs.

Architecture:
  reflection_log.json ─→ data_builder.py ─→ training_data.jsonl
                                               ↓
  finetune_cycle.py:  training_data.jsonl ─→ LoRA adapter (saved to models/finetune/{version}/)
                                               ↓
                                         status.json written for dashboard

Usage:
    python -m training.finetune_cycle \
        --state-dir data \
        --version Ptolemy-S1 \
        --epochs 1

Or imported:
    from training.finetune_cycle import run_finetune
    result = run_finetune(state_dir="data", version="Ptolemy-S1")
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.finetune_cycle")

# Trainable base model — single source of truth in training/model_config.py
# (reads config/models.json; OPENTRADER_BASE_MODEL env overrides it).
from training.model_config import BASE_MODEL as DEFAULT_BASE_MODEL
FINETUNE_OUTPUT_DIR = "models/finetune"
STATUS_FILE = "finetune_status.json"


def run_finetune(
    state_dir: str,
    version: str = None,
    data_path: str = None,
    output_dir: str = None,
    epochs: int = 1,
    batch_size: int = 1,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 1024,
    lora_r: int = 8,
    lora_alpha: int = 8,
    dry_run: bool = False,
) -> dict:
    """Run a fine-tuning cycle on collected reflection data.

    Steps:
      1. Build training data from reflection log (via data_builder)
      2. Load base model with Unsloth + 4-bit QLoRA
      3. Train for N epochs
      4. Save LoRA adapter to models/finetune/{version}/
      5. Write status file for dashboard

    Returns:
        dict with keys: status, version, examples, epochs,
                        output_path, duration_s, error (if any)
    """
    result = {
        "status": "started",
        "version": version or "unknown",
        "examples": 0,
        "epochs": epochs,
        "output_path": "",
        "duration_s": 0.0,
        "error": "",
    }

    start_time = time.time()
    state_path = Path(state_dir)

    # ── Step 1: Build or use training data ──────────────────
    if data_path and Path(data_path).exists():
        # Use existing training data (e.g., ADIR-generated)
        actual_path = data_path
        num_examples = sum(1 for _ in open(actual_path))
        logger.info(f"Using existing training data: {num_examples} examples at {actual_path}")
    else:
        from training.data_builder import build_training_data

        actual_path, num_examples = build_training_data(
            state_dir=state_dir,
            output_path=data_path,
            include_history=True,
        )

    if not actual_path or num_examples == 0:
        result["status"] = "skipped"
        result["error"] = "Not enough training data"
        _write_status(state_path, result)
        logger.info("Fine-tune skipped: insufficient training data")
        return result

    result["examples"] = num_examples
    logger.info(f"Training data: {num_examples} examples at {actual_path}")

    # ── Step 2: Verify GPU environment ─────────────────────
    try:
        import torch
    except ImportError:
        result["status"] = "error"
        result["error"] = "PyTorch not installed. Activate rocm_venv."
        _write_status(state_path, result)
        return result

    if not torch.cuda.is_available():
        result["status"] = "error"
        result["error"] = "ROCm/CUDA GPU not available"
        _write_status(state_path, result)
        return result

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    logger.info(f"GPU: {gpu_name} ({vram_gb:.1f} GB)")

    # ── Step 3: Resolve version ────────────────────────────
    if version is None:
        # Try to get current MoT version
        mot_path = state_path / "mot_state.json"
        if mot_path.exists():
            try:
                mot = json.loads(mot_path.read_text())
                name = mot.get("name", "Ptolemy")
                gen = mot.get("generation", 1)
                version = f"{name}-{gen}"
            except Exception:
                version = "Ptolemy-S0"
        else:
            version = "Ptolemy-S0"

    result["version"] = version

    # Output directory
    if output_dir is None:
        output_dir = str(state_path / FINETUNE_OUTPUT_DIR / version)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    result["output_path"] = output_dir

    # ── Step 4: Load model and tokenizer ──────────────────
    logger.info(f"Loading base model: {DEFAULT_BASE_MODEL}")
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    try:
        from unsloth import FastLanguageModel, is_bfloat16_supported
        from unsloth.chat_templates import get_chat_template, standardize_sharegpt
    except ImportError:
        result["status"] = "error"
        result["error"] = (
            "Unsloth not installed. Activate ~/rocm_venv:\n"
            "  source ~/rocm_venv/bin/activate\n"
            "  pip install unsloth"
        )
        _write_status(state_path, result)
        return result

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=DEFAULT_BASE_MODEL,
            max_seq_length=max_seq_length,
            dtype=None,
            load_in_4bit=True,
        )
        logger.info(
            f"Model loaded. Params: "
            f"{sum(p.numel() for p in model.parameters()) / 1e6:.1f}M"
        )
    except Exception as e:
        result["status"] = "error"
        result["error"] = f"Model load failed: {e}"
        _write_status(state_path, result)
        return result

    # ── Step 5: Apply LoRA ────────────────────────────────
    logger.info(f"Applying LoRA (r={lora_r}, alpha={lora_alpha})...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=lora_alpha,
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
        use_rslora=False,
        loftq_config=None,
    )

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    logger.info(f"Trainable: {trainable / 1e6:.1f}M ({100 * trainable / total:.1f}%)")

    if dry_run:
        result["status"] = "dry_run"
        result["duration_s"] = round(time.time() - start_time, 1)
        _write_status(state_path, result)
        logger.info("DRY RUN — exiting without training.")
        return result

    # ── Step 6: Prepare dataset ───────────────────────────
    logger.info("Preparing training dataset...")
    # Qwen2.5 uses ChatML format (not gemma)
    tokenizer = get_chat_template(tokenizer, chat_template="chatml")

    raw_examples = []
    with open(actual_path) as f:
        for line in f:
            line = line.strip()
            if line:
                raw_examples.append(json.loads(line))

    # Convert to Dataset first, then standardize (Unsloth API change)
    from datasets import Dataset
    hf_dataset = Dataset.from_list(raw_examples)
    dataset = standardize_sharegpt(hf_dataset)

    def formatting_fn(examples):
        texts = []
        for conv in examples["conversations"]:
            try:
                text = tokenizer.apply_chat_template(
                    conv, tokenize=False, add_generation_prompt=False,
                )
                texts.append(text)
            except Exception:
                texts.append("")
        return {"text": texts}

    hf_dataset = dataset.map(formatting_fn, batched=True)

    logger.info(f"Dataset: {len(hf_dataset)} samples")

    # ── Step 7: Train ─────────────────────────────────────
    from trl import SFTTrainer
    from transformers import TrainingArguments

    effective_batch = batch_size * grad_accum
    steps = len(hf_dataset) * epochs // max(effective_batch, 1)

    _write_status(state_path, {
        **result,
        "status": "training",
        "progress": 0.0,
        "total_steps": steps,
    })

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=hf_dataset,
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        args=TrainingArguments(
            per_device_train_batch_size=batch_size,
            gradient_accumulation_steps=grad_accum,
            warmup_steps=2,
            num_train_epochs=epochs,
            learning_rate=learning_rate,
            fp16=False,
            bf16=is_bfloat16_supported(),
            logging_steps=1,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="linear",
            seed=42,
            output_dir=f"{output_dir}_checkpoints",
            save_strategy="no",
            report_to="none",
        ),
    )

    logger.info(f"Starting training: {epochs} epoch(s), {steps} step(s)")
    trainer.train()
    logger.info("Training complete.")

    # ── Step 8: Save adapter ──────────────────────────────
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Save metadata
    meta = {
        "base_model": DEFAULT_BASE_MODEL,
        "version": version,
        "training_examples": len(raw_examples),
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "max_seq_length": max_seq_length,
        "trainable_params_m": round(trainable / 1e6, 2),
        "vram_gb": round(vram_gb, 1),
        "gpu": gpu_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.time() - start_time, 1),
    }
    with open(Path(output_dir) / "training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    duration = round(time.time() - start_time, 1)
    result["status"] = "completed"
    result["duration_s"] = duration

    _write_status(state_path, result)

    # ── Register with Adapter Registry ──────────────────────
    try:
        from mot import AdapterRegistry

        # Get current MoT score for context
        mot_score = 0.0
        mot_cycles = 0
        try:
            mot_path = state_path / "mot_state.json"
            if mot_path.exists():
                mot_data = json.loads(mot_path.read_text())
                mot_score = mot_data.get("current_score", 0.0)
                mot_cycles = mot_data.get("total_reviews", 0)
        except Exception:
            pass

        # Get previous version from MoT coordinator
        prev_version = ""
        try:
            from mot import MoTCoordinator
            coord = MoTCoordinator(str(state_path))
            if hasattr(coord, 'state') and hasattr(coord.state, 'name'):
                pass
        except Exception:
            pass

        registry = AdapterRegistry(state_dir)
        registry.register(
            version=version,
            path=output_dir,
            training_score=mot_score,
            training_cycles=mot_cycles,
            training_examples=num_examples,
            previous_version=prev_version,
        )
        logger.info(f"Adapter registered in lifecycle: {version}")
    except Exception as e:
        logger.warning(f"Adapter registry update failed (non-fatal): {e}")

    # ── Auto-promote gate: requires eval_score > 0 ─────────────
    try:
        registry = AdapterRegistry(state_dir)
        active = registry.get_active()
        record = registry.get(version)
        if active is None and record and record.eval_score > 0:
            registry.promote(version)
            logger.info(f"Auto-promoted {version} to active (first adapter with eval)")
        elif active is None:
            logger.warning(
                f"Cannot auto-promote {version}: gate now requires eval_score > 0 "
                f"from deep_eval. eval_gate cron will promote after evaluation."
            )
        else:
            logger.info(
                f"Adapter {version} registered as pending. "
                f"Active: {active.version}"
            )
    except Exception as e:
        logger.debug(f"Auto-promote check failed: {e}")

    logger.info(
        f"Fine-tune complete: {version} — "
        f"{num_examples} examples, {duration}s"
    )
    return result


def _write_status(state_path: Path, data: dict) -> None:
    """Write fine-tune status for dashboard consumption."""
    train_dir = state_path / "training"
    train_dir.mkdir(parents=True, exist_ok=True)
    path = train_dir / STATUS_FILE
    safe = {
        "status": data.get("status", "unknown"),
        "version": data.get("version", ""),
        "examples": data.get("examples", 0),
        "epochs": data.get("epochs", 0),
        "output_path": data.get("output_path", ""),
        "duration_s": data.get("duration_s", 0.0),
        "progress": data.get("progress", None),
        "total_steps": data.get("total_steps", 0),
        "error": data.get("error", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(safe, indent=2))
    os.replace(tmp, path)


def read_status(state_dir: str) -> dict:
    """Read fine-tune status for dashboard."""
    path = Path(state_dir) / "training" / STATUS_FILE
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {
        "status": "idle",
        "version": "",
        "examples": 0,
        "duration_s": 0.0,
        "error": "",
    }


def main():
    parser = argparse.ArgumentParser(description="Fine-tune trading agent")
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--version", default=None, help="MoT version (e.g. Ptolemy-S1)")
    parser.add_argument("--data", default=None, help="Path to training data .jsonl")
    parser.add_argument("--output", default=None, help="Output directory for LoRA")
    parser.add_argument("--epochs", type=int, default=1, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=1, help="Per-device batch")
    parser.add_argument("--grad-accum", type=int, default=4, help="Grad accum steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--lora-r", type=int, default=8, help="LoRA rank")
    parser.add_argument("--lora-alpha", type=int, default=8, help="LoRA alpha")
    parser.add_argument("--max-seq-length", type=int, default=1024)
    parser.add_argument("--dry-run", action="store_true", help="Prep only, no train")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    result = run_finetune(
        state_dir=args.state_dir,
        version=args.version,
        data_path=args.data,
        output_dir=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        max_seq_length=args.max_seq_length,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("completed", "skipped", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
