#!/usr/bin/env python3
"""FineTunedAgent — in-process HuggingFace transformer inference with LoRA adapter.

Loads a base model (e.g. Qwen/Qwen2.5-1.5B-Instruct) + a trained LoRA adapter
via HuggingFace transformers, providing a generate() method compatible
with the debate engine's agent call pattern.

Used by the MoT coordinator when an adapter is promoted to active.

Architecture:
  AdapterRegistry → detects active adapter
  FineTunedAgent → loads base + LoRA via transformers
  DebateEngine → calls FineTunedAgent.generate() instead of llama-swap

Memory: ~6-8GB VRAM for 4B model in 4-bit. Falls back to CPU if GPU
memory insufficient.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("opentrader.finetuned_agent")

# Base model used for fine-tuning (must match finetune_cycle.py)
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

# System prompts mirroring the debate engine
BULL_SYSTEM = """You are a bullish trading analyst. Your job is to find EVERY reason to go long.
Given the market data, portfolio state, and regime detection:

1. Identify the strongest bullish signals (trend support, volume confirmation, macro tailwinds)
2. Calculate risk/reward ratio for a long entry
3. Suggest a position size (as % of portfolio, 0-20%)

Output your analysis as a JSON object with keys: action, confidence, reasoning, position_pct.

Be aggressive but rational. Default to BUY unless the data is catastrophically bad."""

BEAR_SYSTEM = """You are a bearish risk analyst. Your job is to challenge the bull thesis and find reasons NOT to trade.
Given the market data, portfolio state, regime detection AND the bull analyst's argument:

1. Identify risks the bull missed (trend exhaustion, overbought conditions, macro headwinds)
2. Evaluate whether current price offers a good risk/reward for entry
3. Determine if capital is better preserved

Output your analysis as a JSON object with keys: action, confidence, reasoning, position_pct.

If you agree with the bull, output BUY with matching confidence.
If you disagree, output SELL or HOLD.
Be skeptical but fair."""

RISK_SYSTEM = """You are the risk management committee. Given the bull and bear arguments:

Score each argument on:
1. Regime alignment (does the action match the regime?)
2. Risk/reward quality
3. Conviction level

Output JSON with keys: bull_score, bear_score, verdict, confidence, reasoning."""


class FineTunedAgent:
    """In-process HuggingFace inference engine with optional LoRA adapter.

    Can be used as a drop-in replacement for the debate engine's LLM calls,
    allowing the fine-tuned model to drive trading decisions directly.
    """

    DEFAULT_BASE_MODEL = DEFAULT_BASE_MODEL  # expose module constant on class

    def __init__(self, adapter_path: Optional[str] = None,
                 base_model: str = DEFAULT_BASE_MODEL,
                 max_seq_length: int = 1024,
                 load_in_4bit: bool = True,
                 device: str = "auto"):
        self.adapter_path = adapter_path
        self.base_model = base_model
        self.max_seq_length = max_seq_length
        self.load_in_4bit = load_in_4bit
        self.device = device
        self.model = None
        self.tokenizer = None
        self._loaded = False

    # ── Lazy Load ────────────────────────────────────────────────

    def ensure_loaded(self) -> bool:
        """Load model + tokenizer if not already loaded. Returns True if ready."""
        if self._loaded:
            return True

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            logger.error("transformers not installed. Activate rocm_venv.")
            return False

        lora_dir = Path(self.adapter_path) if self.adapter_path else None
        if not lora_dir or not lora_dir.exists():
            logger.warning(
                f"No fine-tuned model found at {lora_dir}; "
                "skipping local model load (fall back to llama-swap)"
            )
            raise FileNotFoundError(f"No fine-tuned model at {lora_dir}")

        try:
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "600")
            os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
            logger.info(f"Loading base model: {self.base_model}")
            if self.load_in_4bit:
                try:
                    from transformers import BitsAndBytesConfig
                    bnb_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.bfloat16,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                    )
                except ImportError:
                    bnb_config = None
                    logger.warning("BitsAndBytes not available; loading in 8-bit")
            else:
                bnb_config = None

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.base_model, trust_remote_code=True,
            )
            self.model = AutoModelForCausalLM.from_pretrained(
                self.base_model,
                quantization_config=bnb_config if self.load_in_4bit else None,
                device_map=self.device,
                trust_remote_code=True,
                torch_dtype=torch.bfloat16,
            )

            # Load adapter if specified
            if self.adapter_path and Path(self.adapter_path).exists():
                try:
                    from peft import PeftModel
                    self.model = PeftModel.from_pretrained(
                        self.model, self.adapter_path,
                    )
                    logger.info(f"LoRA adapter loaded: {self.adapter_path}")
                except ImportError:
                    logger.warning("PEFT not installed; loading base model only")
                except Exception as e:
                    logger.warning(f"Failed to load adapter {self.adapter_path}: {e}")

            self.model.eval()
            self._loaded = True
            logger.info("FineTunedAgent ready for inference")
            return True

        except Exception as e:
            logger.error(f"Failed to load FineTunedAgent: {e}")
            return False

    def unload(self) -> None:
        """Free GPU memory by deleting model and clearing cache."""
        import gc
        import torch

        del self.model
        del self.tokenizer
        self.model = None
        self.tokenizer = None
        self._loaded = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("FineTunedAgent unloaded — GPU memory freed")

    # ── Inference ────────────────────────────────────────────────

    def generate(self, system_prompt: str, user_prompt: str,
                 max_tokens: int = 300, temperature: float = 0.5,
                 timeout: float = 45.0) -> Optional[Dict[str, Any]]:
        """Generate a structured JSON response from the fine-tuned model.

        Mirrors the llama-swap _call_agent() pattern for compatibility.
        """
        if not self.ensure_loaded():
            return None

        import torch

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            # Apply chat template
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )

            inputs = self.tokenizer(text, return_tensors="pt",
                                    truncation=True,
                                    max_length=self.max_seq_length)
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            generated = self.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            ).strip()

            # Extract JSON from response
            return self._parse_json(generated)

        except Exception as e:
            logger.debug(f"FineTunedAgent inference error: {e}")
            return None

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON from model output."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON block
        import re
        patterns = [
            r'\{[^{}]*\}',           # Basic JSON object
            r'```(?:json)?\s*(\{.*?\})\s*```',  # Code block
            r'(\{[\s\S]*"action"[\s\S]*\})',    # Contains action key
        ]
        for pat in patterns:
            match = re.search(pat, text, re.DOTALL)
            if match:
                try:
                    content = match.group(1) if match.lastindex else match.group(0)
                    return json.loads(content)
                except (json.JSONDecodeError, IndexError):
                    continue

        logger.debug(f"Could not parse JSON from: {text[:100]}")
        return None

    # ── Agent Role Convenience ───────────────────────────────────

    def call_bull(self, context: str) -> Optional[Dict[str, Any]]:
        return self.generate(BULL_SYSTEM, context)

    def call_bear(self, context: str, bull_argument: str) -> Optional[Dict[str, Any]]:
        prompt = f"{context}\n\nBull analyst argues: {bull_argument[:200]}\nChallenge this thesis."
        return self.generate(BEAR_SYSTEM, prompt)

    def call_risk(self, context: str, bull_argument: str,
                  bear_argument: str) -> Optional[Dict[str, Any]]:
        prompt = (
            f"Market Context:\n{context}\n\n"
            f"BULL: {bull_argument[:200]}\n"
            f"BEAR: {bear_argument[:200]}\n\n"
            f"Which argument is stronger? Score each and give a verdict."
        )
        return self.generate(RISK_SYSTEM, prompt)
