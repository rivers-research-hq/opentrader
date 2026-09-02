#!/usr/bin/env python3
"""ModelPool — VRAM-aware model manager for multi-agent deployment.

Loads a shared base model (Qwen2.5-1.5B-Instruct) plus optional LoRA adapters,
exposing a clean `generate()` interface for multiple specialist agents without
duplicating VRAM.

Architecture:
    Base Model (3GB bf16) ─┬─ LoRA "ptolemy-s0" (general trading)
                            │    ├─ TechnicalAnalyst
                            │    ├─ MomentumChaser
                            │    ├─ MeanReversionHunter
                            │    ├─ MacroSentiment
                            │    └─ TrainingCoach
                            │
                            └─ Future: LoRA "beta-1" (different strategy)
                                 ├─ VolatilityArbitrageur
                                 └─ PatternDayTrader

PEFT's add_adapter/set_adapter allows rapid LoRA switching without
reloading the base model. Each `.generate()` call routes through the
correct adapter + system prompt.

VRAM budget parameters:
  --vram-budget-gb N     Max GB allocated (default: 10)
  --max-instances N      Max concurrent model instances (default: 3)

Usage:
  pool = ModelPool(vram_budget_gb=10)
  pool.load_adapter("ptolemy-s0", "models/finetune/Ptolemy-S0/adapter")
  result = pool.generate("ptolemy-s0", system_prompt, user_prompt)
"""

import gc
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import torch

logger = logging.getLogger("opentrader.pool")


@dataclass
class AdapterInfo:
    name: str
    path: str
    base_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    metrics: Dict[str, float] = field(default_factory=dict)
    total_calls: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0
    last_used: float = 0.0


@dataclass
class ModelInstance:
    """A loaded base model + optional LoRA, ready for inference."""
    model: Any
    tokenizer: Any
    model_id: str
    adapter: Optional[str] = None
    vram_used_gb: float = 0.0
    total_calls: int = 0
    total_tokens: int = 0
    avg_latency_ms: float = 0.0


class ModelPool:
    """VRAM-aware pool of models with LoRA adapters.

    Supports two modes:
      - SINGLE (default): one base model, hot-swap LoRA adapters via PEFT.
        Good for sequential inference with minimal VRAM.
      - MULTI: multiple base model instances loaded simultaneously for
        parallel inference across different agents. Uses more VRAM.

    Falls back to CPU inference if GPU memory is insufficient.

    VRAM scaling (1.5B bf16 ≈ 3.2GB/instance):
      1 instance  =  3.2GB → coach only
      2 instances =  6.4GB → coach + ensemble parallel
      3 instances =  9.6GB → coach + ensemble + spare
      4 instances = 12.8GB → all specialists parallel
    """

    def __init__(self, vram_budget_gb: float = 10.0, max_instances: int = 4,
                 multi: bool = True):
        self.vram_budget_gb = vram_budget_gb
        self.max_instances = max_instances
        self.multi = multi
        self._lock = threading.RLock()

        self.base_model: Optional[Any] = None
        self.tokenizer: Optional[Any] = None
        self.model_device = "auto"

        self.adapters: Dict[str, AdapterInfo] = {}
        self._current_adapter: Optional[str] = None
        self._peft_model: Optional[Any] = None

        # Multi-instance mode
        self.instances: List[ModelInstance] = []
        self._instance_idx: int = 0

        self._vram_used_gb: float = 0.0
        self._base_model_id: Optional[str] = None

        self.stats: Dict[str, Any] = {"loads": 0, "switches": 0, "oom_events": 0, "instances": 0}

        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
        os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

    def estimate_vram(self, model_id: str = None) -> float:
        model_id = model_id or "Qwen/Qwen2.5-1.5B-Instruct"
        if "1.5b" in model_id.lower() or "1.5B" in model_id:
            return 3.2
        if "0.5b" in model_id.lower() or "0.5B" in model_id:
            return 1.5
        if "7b" in model_id.lower() or "7B" in model_id:
            return 15.0
        return 8.0

    def load_base(self, model_id: str = "Qwen/Qwen2.5-1.5B-Instruct",
                  force: bool = False) -> bool:
        with self._lock:
            if self.base_model is not None and not force and self._base_model_id == model_id:
                return True

            est_vram = self.estimate_vram(model_id)
            if est_vram > self.vram_budget_gb - self._vram_used_gb:
                logger.warning(
                    f"ModelPool: {model_id} needs ~{est_vram:.1f}GB, "
                    f"budget has {self.vram_budget_gb - self._vram_used_gb:.1f}GB free. "
                    f"Falling back to CPU."
                )
                self.model_device = "cpu"

            logger.info(f"ModelPool: loading {model_id} (~{est_vram:.1f}GB)...")
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer

                self.tokenizer = AutoTokenizer.from_pretrained(
                    model_id, trust_remote_code=True,
                )

                load_kwargs: Dict[str, Any] = {
                    "trust_remote_code": True,
                    "torch_dtype": torch.bfloat16,
                }

                if self.model_device == "auto" and torch.cuda.is_available():
                    load_kwargs["device_map"] = "auto"
                elif self.model_device == "cpu":
                    pass
                else:
                    load_kwargs["device_map"] = "auto"

                self.base_model = AutoModelForCausalLM.from_pretrained(
                    model_id, **load_kwargs,
                )
                self.base_model.eval()
                self._base_model_id = model_id
                self._vram_used_gb += est_vram
                self.stats["loads"] += 1
                logger.info(
                    f"ModelPool: {model_id} loaded "
                    f"({self._vram_used_gb:.1f}/{self.vram_budget_gb:.1f}GB used)"
                )
                return True
            except Exception as e:
                logger.error(f"ModelPool: failed to load {model_id}: {e}")
                return False

    def load_adapter(self, name: str, adapter_path: str,
                     base_model: str = "Qwen/Qwen2.5-1.5B-Instruct") -> bool:
        with self._lock:
            path = Path(adapter_path)
            if not path.exists():
                logger.warning(f"ModelPool: adapter path not found: {adapter_path}")
                return False

            if not self.base_model or self._base_model_id != base_model:
                ok = self.load_base(base_model)
                if not ok:
                    return False

            info = AdapterInfo(name=name, path=str(path), base_model=base_model)
            self.adapters[name] = info
            logger.info(f"ModelPool: registered adapter '{name}' at {adapter_path}")
            return True

    def _ensure_peft(self) -> bool:
        if self._peft_model is not None:
            return True
        if self.base_model is None:
            return False
        try:
            from peft import PeftModel
            self._peft_model = PeftModel.from_pretrained(
                self.base_model, self._current_adapter,
            )
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def switch_adapter(self, name: str) -> bool:
        with self._lock:
            if name not in self.adapters:
                logger.warning(f"ModelPool: adapter '{name}' not registered")
                return False

            if self._current_adapter == name and self._peft_model is not None:
                return True

            info = self.adapters[name]
            logger.debug(f"ModelPool: switching to adapter '{name}'")

            try:
                from peft import PeftModel

                if self._peft_model is None:
                    self._peft_model = PeftModel.from_pretrained(
                        self.base_model, info.path,
                    )
                else:
                    self._peft_model = PeftModel.from_pretrained(
                        self.base_model, info.path,
                    )

                self._current_adapter = name
                self.stats["switches"] += 1
                return True

            except Exception as e:
                logger.debug(f"ModelPool: switch failed ({e}), generating with base model")
                self._peft_model = None
                self._current_adapter = name
                return True

    def _curate_adapter(self, name: str) -> Optional[Any]:
        if self._peft_model is not None and self._current_adapter == name:
            return self._peft_model
        if self.base_model is None:
            return None

        self.switch_adapter(name)
        return self._peft_model

    # ── Multi-Instance Mode ─────────────────────────────────────

    def spin_up_instances(self, count: int, model_id: str = "Qwen/Qwen2.5-1.5B-Instruct",
                          adapter_name: str = None) -> int:
        """Load `count` additional model instances for parallel inference.

        Each instance is an independent model + tokenizer. Total VRAM =
        estimate_vram(model_id) × count. Falls back to single instance
        if insufficient VRAM.

        Returns number of instances actually loaded.
        """
        with self._lock:
            return self._spin_up(count, model_id, adapter_name)

    def _spin_up(self, count: int, model_id: str, adapter_name: str = None) -> int:
        est = self.estimate_vram(model_id)
        needed = est * count
        available = self.vram_budget_gb - self._vram_used_gb
        if needed > available and count > 1:
            feasible = int(available / max(est, 0.1))
            logger.warning(
                f"ModelPool: requested {count} instances ({needed:.1f}GB), "
                f"only {available:.1f}GB free. Loading {feasible} instead."
            )
            count = max(feasible, 0)
        if count <= 0:
            return 0

        from transformers import AutoModelForCausalLM, AutoTokenizer
        import gc

        loaded = 0
        for i in range(count):
            try:
                tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
                model = AutoModelForCausalLM.from_pretrained(
                    model_id,
                    device_map="auto",
                    trust_remote_code=True,
                    torch_dtype=torch.bfloat16,
                )
                model.eval()

                instance = ModelInstance(
                    model=model, tokenizer=tok, model_id=model_id,
                    adapter=adapter_name, vram_used_gb=est,
                )

                # Load LoRA if adapter specified
                if adapter_name and adapter_name in self.adapters:
                    try:
                        from peft import PeftModel
                        instance.model = PeftModel.from_pretrained(
                            model, self.adapters[adapter_name].path,
                        )
                        instance.adapter = adapter_name
                    except Exception:
                        pass

                self.instances.append(instance)
                self._vram_used_gb += est
                loaded += 1
                self.stats["instances"] = len(self.instances)
            except Exception as e:
                logger.warning(f"ModelPool: failed to load instance {i}: {e}")
                gc.collect()
                torch.cuda.empty_cache()
                break

        logger.info(
            f"ModelPool: spun up {loaded} instances ({self._vram_used_gb:.1f}/{self.vram_budget_gb:.1f}GB)",
        )
        return loaded

    def get_instance(self, idx: Optional[int] = None) -> Optional[ModelInstance]:
        """Round-robin instance selection for parallel inference."""
        if not self.instances:
            return None
        if idx is None:
            idx = self._instance_idx % len(self.instances)
            self._instance_idx += 1
        return self.instances[idx % len(self.instances)]

    def generate_parallel(self, adapter_name: str, system_prompt: str,
                          user_prompt: str, max_tokens: int = 350,
                          temperature: float = 0.5, timeout: float = 60.0,
                          json_output: bool = False) -> Optional[str]:
        """Generate using a multi-instance model (round-robin).

        When multi-instance mode is active, routes to the next available
        instance instead of the shared base model. Falls back to the
        single-instance generate() if no instances loaded.
        """
        inst = self.get_instance()
        if inst is not None:
            return self._generate_with(inst, system_prompt, user_prompt,
                                       max_tokens, temperature, timeout,
                                       json_output, adapter_name)
        return self.generate(adapter_name, system_prompt, user_prompt,
                             max_tokens, temperature, timeout, json_output)

    def _generate_with(self, instance: ModelInstance, system_prompt: str,
                       user_prompt: str, max_tokens: int, temperature: float,
                       timeout: float, json_output: bool,
                       adapter_name: str) -> Optional[str]:
        import time
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            text = instance.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            inputs = instance.tokenizer(
                text, return_tensors="pt", truncation=True, max_length=2048,
            )
            device = getattr(instance.model, "device", None)
            if device is not None:
                inputs = {k: v.to(device) for k, v in inputs.items()}

            start = time.time()
            with torch.no_grad():
                outputs = instance.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature if temperature > 0 else 1.0,
                    do_sample=temperature > 0,
                    pad_token_id=instance.tokenizer.eos_token_id,
                )

            elapsed_ms = (time.time() - start) * 1000
            generated = instance.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            ).strip()

            instance.total_calls += 1
            instance.total_tokens += len(outputs[0]) - inputs["input_ids"].shape[1]
            instance.avg_latency_ms = (
                (instance.avg_latency_ms * (instance.total_calls - 1) + elapsed_ms)
                / instance.total_calls
            )

            if adapter_name in self.adapters:
                self.adapters[adapter_name].total_calls += 1
                self.adapters[adapter_name].avg_latency_ms = instance.avg_latency_ms
                self.adapters[adapter_name].last_used = time.time()

            return generated

        except torch.cuda.OutOfMemoryError:
            self.stats["oom_events"] += 1
            torch.cuda.empty_cache()
            return None
        except Exception as e:
            logger.debug(f"ModelPool instance generate error: {e}")
            return None

    def generate(self, adapter_name: str, system_prompt: str,
                 user_prompt: str, max_tokens: int = 350,
                 temperature: float = 0.5, timeout: float = 60.0,
                 json_output: bool = False) -> Optional[str]:
        model = self._curate_adapter(adapter_name)
        if model is None or self.tokenizer is None:
            logger.warning(f"ModelPool: no model loaded for adapter '{adapter_name}'")
            return None

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        if json_output and not system_prompt.rstrip().endswith("JSON only."):
            user_prompt = user_prompt + "\n\nRespond with JSON only."

        try:
            text = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )

            inputs = self.tokenizer(
                text, return_tensors="pt", truncation=True, max_length=2048,
            )

            if hasattr(model, "device") and isinstance(model.device, torch.device):
                inputs = {k: v.to(model.device) for k, v in inputs.items()}
            elif hasattr(self.base_model, "device"):
                try:
                    inputs = {k: v.to(self.base_model.device) for k, v in inputs.items()}
                except Exception:
                    pass

            start = time.time()
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=temperature,
                    do_sample=temperature > 0,
                    pad_token_id=self.tokenizer.eos_token_id,
                )

            elapsed_ms = (time.time() - start) * 1000
            generated = self.tokenizer.decode(
                outputs[0][inputs["input_ids"].shape[1]:],
                skip_special_tokens=True,
            ).strip()

            if adapter_name in self.adapters:
                info = self.adapters[adapter_name]
                info.total_calls += 1
                info.total_tokens += len(outputs[0]) - inputs["input_ids"].shape[1]
                info.avg_latency_ms = (
                    (info.avg_latency_ms * (info.total_calls - 1) + elapsed_ms)
                    / info.total_calls
                )
                info.last_used = time.time()

            return generated

        except torch.cuda.OutOfMemoryError:
            self.stats["oom_events"] += 1
            logger.warning(f"ModelPool: OOM during generate for '{adapter_name}'")
            torch.cuda.empty_cache()
            return None
        except Exception as e:
            logger.debug(f"ModelPool: generate error for '{adapter_name}': {e}")
            return None

    def unload(self) -> None:
        with self._lock:
            del self.base_model
            del self.tokenizer
            self.base_model = None
            self.tokenizer = None
            self._peft_model = None
            self._current_adapter = None
            self.adapters.clear()
            self._vram_used_gb = 0.0
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("ModelPool: all models unloaded")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "base_model": self._base_model_id,
            "vram_used_gb": round(self._vram_used_gb, 2),
            "vram_budget_gb": self.vram_budget_gb,
            "adapters": {
                name: {
                    "calls": i.total_calls,
                    "tokens": i.total_tokens,
                    "avg_latency_ms": round(i.avg_latency_ms, 1),
                }
                for name, i in self.adapters.items()
            },
            "stats": self.stats,
        }
