#!/usr/bin/env python3
"""Research Model — fine-tunes a small triage model on capability data.

Gated on cumulative_scenarios >= 50. The research model helps research-scout
quickly triage findings for relevance before full LLM analysis.

Pipeline:
  1. Check gate: cumulative_scenarios >= 50 (or --force)
  2. Build dataset from data/research/scenarios/ + augmentations/
  3. Fine-tune Qwen2.5-1.5B-Instruct with QLoRA
  4. Save to models/finetune/research/{version}/
  5. Update research_model_status.json
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.research_model")

RESEARCH_BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
RESEARCH_OUTPUT_DIR = "models/finetune/research"
MIN_SCENARIOS = 50
STATUS_FILE = "research_model_status.json"


def _compute_version(state_dir: Path) -> str:
    """Auto-increment research model version."""
    out_root = state_dir.parent / RESEARCH_OUTPUT_DIR
    if not out_root.exists():
        return "research-v1"
    existing = [d for d in out_root.iterdir() if d.is_dir() and d.name.startswith("research-v")]
    if not existing:
        return "research-v1"
    nums = []
    for d in existing:
        try:
            nums.append(int(d.name.replace("research-v", "")))
        except ValueError:
            continue
    return f"research-v{max(nums) + 1}" if nums else "research-v1"


def check_gate(state_dir: str = "data") -> Dict:
    """Check if the research model gate has been reached.

    Returns dict with gate status and counts.
    """
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    registry_path = state_path / "research" / "distilled_registry.json"
    cumulative = 0
    if registry_path.exists():
        with open(registry_path) as f:
            registry = json.load(f)
        cumulative = registry.get("cumulative_scenarios", 0)

    scenarios_dir = state_path / "research" / "scenarios"
    existing_scenarios = len(list(scenarios_dir.glob("*.json"))) if scenarios_dir.exists() else 0

    result = {
        "gate_passed": cumulative >= MIN_SCENARIOS,
        "cumulative_scenarios": cumulative,
        "existing_scenario_files": existing_scenarios,
        "min_required": MIN_SCENARIOS,
        "remaining": max(0, MIN_SCENARIOS - cumulative),
    }
    return result


def build_triage_dataset(state_dir: str = "data", force: bool = False) -> Optional[str]:
    """Build a triage dataset from accumulated scenarios and augmentations.

    Returns path to the generated JSONL file, or None if gate not passed.
    """
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    gate = check_gate(state_dir)
    if not gate["gate_passed"] and not force:
        logger.info(
            "Research model gate not passed: %d/%d scenarios (use --force to override)",
            gate["cumulative_scenarios"],
            MIN_SCENARIOS,
        )
        return None

    research_dir = state_path / "research"
    output_dir = state_path / "training"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "research_triage_data.jsonl")

    rows = []

    # Load scenarios
    scenarios_dir = research_dir / "scenarios"
    if scenarios_dir.exists():
        for sf in sorted(scenarios_dir.glob("*.json")):
            with open(sf) as f:
                data = json.load(f)
            capability = data.get("capability", "unknown")
            source = data.get("origin", "unknown")
            for sc in data.get("scenarios", []):
                row = {
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a research triage assistant for a trading AI system. "
                                       "Classify research findings and generate training scenarios.",
                        },
                        {
                            "role": "user",
                            "content": f"Generate a {sc.get('difficulty', 'medium')} difficulty "
                                       f"training scenario for capability '{capability}'.\n\n"
                                       f"Prompt: {sc.get('prompt', '')}",
                        },
                        {
                            "role": "assistant",
                            "content": f"Reasoning: {sc.get('expected_reasoning', '')}\n"
                                       f"Action: {sc.get('expected_action', '')}",
                        },
                    ],
                    "metadata": {
                        "type": "scenario",
                        "capability": capability,
                        "difficulty": sc.get("difficulty", "medium"),
                        "source": source,
                    },
                }
                rows.append(row)

    # Load augmentations
    aug_dir = research_dir / "augmentations"
    if aug_dir.exists():
        for af in sorted(aug_dir.glob("*.jsonl")):
            with open(af) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            row = json.loads(line)
                            rows.append(row)
                        except json.JSONDecodeError:
                            continue

    if not rows:
        logger.warning("No scenario or augmentation data found for research model")
        return None

    with open(output_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info("Research triage dataset: %d rows → %s", len(rows), output_path)
    return output_path


def train_research_model(
    state_dir: str = "data",
    version: str = None,
    epochs: int = 3,
    batch_size: int = 2,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 1024,
    force: bool = False,
) -> Dict:
    """Fine-tune a small research triage model on capability data.

    Gated on cumulative_scenarios >= 50 unless --force is set.
    Returns status dict.
    """
    t0 = time.time()

    gate = check_gate(state_dir)
    if not gate["gate_passed"] and not force:
        msg = f"Gate not passed: {gate['cumulative_scenarios']}/{MIN_SCENARIOS} scenarios"
        logger.info(msg)
        return {"status": "skipped", "reason": msg, "duration_s": 0}

    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    # Build dataset
    data_path = build_triage_dataset(state_dir, force=force)
    if data_path is None:
        return {"status": "skipped", "reason": "No training data available", "duration_s": 0}

    # Compute version
    if version is None:
        version = _compute_version(state_path)

    output_dir = state_path.parent / RESEARCH_OUTPUT_DIR / version
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import torch
        from unsloth import FastLanguageModel
        from transformers import TrainingArguments
        from datasets import Dataset as HFDataset
    except ImportError as e:
        msg = f"Missing dependencies: {e}. Install with: pip install unsloth trl datasets"
        logger.error(msg)
        return {"status": "error", "error": msg, "duration_s": time.time() - t0}

    logger.info("Loading base model: %s", RESEARCH_BASE_MODEL)
    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=RESEARCH_BASE_MODEL,
            max_seq_length=max_seq_length,
            dtype=None,
            load_in_4bit=True,
        )
    except Exception as e:
        logger.error("Failed to load base model: %s", e)
        return {"status": "error", "error": str(e), "duration_s": time.time() - t0}

    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.pad_token_id = tokenizer.eos_token_id

    # Load dataset
    rows = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    dataset = HFDataset.from_list(rows)

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

    logger.info("Starting research model training: version=%s rows=%d epochs=%d", version, len(rows), epochs)

    # Format function for SFT-style training
    def format_fn(example):
        messages = example.get("messages", [])
        text = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                text += f"<|im_start|>system\n{content}<|im_end|>\n"
            elif role == "user":
                text += f"<|im_start|>user\n{content}<|im_end|>\n"
            elif role == "assistant":
                text += f"<|im_start|>assistant\n{content}<|im_end|>\n"
        text += "<|im_start|>assistant\n"
        return {"text": text}

    formatted = dataset.map(format_fn, remove_columns=dataset.column_names)

    from trl import SFTTrainer

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=formatted,
        tokenizer=tokenizer,
        max_seq_length=max_seq_length,
    )

    trainer.train()

    model.save_pretrained(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    elapsed = time.time() - t0
    meta = {
        "version": version,
        "base_model": RESEARCH_BASE_MODEL,
        "training_type": "research_triage",
        "rows": len(rows),
        "epochs": epochs,
        "learning_rate": learning_rate,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(elapsed, 1),
        "gate_cumulative_scenarios": gate["cumulative_scenarios"],
    }
    with open(output_dir / "training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Save status
    status = {
        "status": "completed",
        "version": version,
        "output_dir": str(output_dir),
        "rows": len(rows),
        "epochs": epochs,
        "duration_s": round(elapsed, 1),
    }
    status_path = state_path / "research" / STATUS_FILE
    status_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_path, "w") as f:
        json.dump(status, f, indent=2)

    logger.info("Research model training completed: %s (%ds)", version, elapsed)
    return status


def load_research_model(state_dir: str = "data"):
    """Load the latest trained research model for triage inference.

    Returns (model, tokenizer) or (None, None) if no model exists.
    """
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    status_path = state_path / "research" / STATUS_FILE
    if not status_path.exists():
        return None, None

    with open(status_path) as f:
        status = json.load(f)

    if status.get("status") != "completed":
        return None, None

    output_dir = status.get("output_dir")
    if not output_dir or not Path(output_dir).exists():
        return None, None

    try:
        from unsloth import FastLanguageModel

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=output_dir,
            max_seq_length=1024,
            dtype=None,
            load_in_4bit=True,
        )
        FastLanguageModel.for_inference(model)
        return model, tokenizer
    except Exception as e:
        logger.warning("Could not load research model %s: %s", output_dir, e)
        return None, None


def triage_finding(finding_text: str, state_dir: str = "data") -> Dict:
    """Use the research model to triage a finding for relevance.

    Returns dict with relevance_score and capability prediction.
    """
    model, tokenizer = load_research_model(state_dir)
    if model is None:
        return {"available": False, "relevance_score": None, "capability": None}

    prompt = (
        "<|im_start|>system\n"
        "You are a research triage assistant. Classify the following research finding "
        "for relevance to a crypto trading AI system. Respond with a JSON object "
        "containing 'relevance' (0.0-1.0) and 'capability' (one of: "
        "regime_detection, risk_management, trade_signal, multi_step_reasoning, "
        "sentiment_analysis, data_augmentation, eval_methodology, "
        "training_technique, inference_efficiency).<|im_end|>\n"
        "<|im_start|>user\n"
        f"{finding_text}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    try:
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=1024)
        if hasattr(model, "device"):
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
        outputs = model.generate(**inputs, max_new_tokens=128, temperature=0.1)
        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            return {
                "available": True,
                "relevance_score": result.get("relevance", 0.5),
                "capability": result.get("capability", "unknown"),
            }
    except Exception as e:
        logger.debug("Research triage failed: %s", e)

    return {"available": True, "relevance_score": 0.5, "capability": "unknown"}


def get_research_model_status(state_dir: str = "data") -> Dict:
    """Return the status of the research model."""
    state_path = Path(state_dir)
    if not state_path.is_absolute():
        state_path = Path(__file__).resolve().parent.parent / state_dir

    gate = check_gate(state_dir)

    status_path = state_path / "research" / STATUS_FILE
    model_status = {"trained": False, "version": None, "output_dir": None, "rows": 0}
    if status_path.exists():
        with open(status_path) as f:
            model_status.update(json.load(f))
        model_status["trained"] = model_status.get("status") == "completed"

    return {
        "gate": gate,
        "model": model_status,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Research triage model training and inference")
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--version", default=None, help="Model version")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--force", action="store_true", help="Bypass gate check")
    parser.add_argument("--check-gate", action="store_true", help="Check gate status")
    parser.add_argument("--build-dataset", action="store_true", help="Build dataset only")
    parser.add_argument("--status", action="store_true", help="Show research model status")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    if args.check_gate:
        gate = check_gate(args.state_dir)
        print(json.dumps(gate, indent=2))
        return

    if args.status:
        status = get_research_model_status(args.state_dir)
        print(json.dumps(status, indent=2))
        return

    if args.build_dataset:
        path = build_triage_dataset(args.state_dir, force=args.force)
        if path:
            print(f"Dataset written to: {path}")
        else:
            print("No dataset generated.")
            sys.exit(1)
        return

    result = train_research_model(
        state_dir=args.state_dir,
        version=args.version,
        epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
