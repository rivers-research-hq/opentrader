"""Single source of truth for model identity used across the training pipeline.

The serving model (llama-server GGUF on GPU1) and the trainable LoRA base
(HuggingFace model) are declared in one place: config/models.json. A model
swap — e.g. the upcoming Qwen3.8-27b — is a drop-in edit of that file (or an
OPENTRADER_BASE_MODEL override), not a code change scattered across training
modules.

Serving (Qwen3.5-9B) and train_base (Qwen2.5-7B) currently DIFFER, so the
fine-tune -> promote -> serve loop is disconnected until they are re-aligned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_JSON = Path(
    os.environ.get("OPENTRADER_MODELS_JSON", PROJECT_ROOT / "config" / "models.json")
)

_FALLBACK = {
    "serving": {
        "name": "DeepSeek-V4-Pro-Qwen3.5-9B-MTP",
        "model_path": "/home/mrc/models/deepseek-v4-pro-qwen3.5-9b/DeepSeek-V4-Pro-Qwen3.5-9B-MTP-Q8_0.gguf",
        "alias": "deepseek-v4-pro-qwen3.5-9b",
        "aliases": ["qwythos-9b-mtp", "deepseek-v4-pro-qwen3.5-9b"],
        "port": 5802,
        "ctx_size": 16384,
        "n_predict": 2048,
    },
    "train_base": {
        "huggingface": "Qwen/Qwen2.5-7B-Instruct",
        "gguf": "/home/mrc/models/qwen2.5-7b-instruct/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
    },
}


def _load() -> dict:
    try:
        with open(MODELS_JSON) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _FALLBACK


_CONFIG = _load()

SERVING = _CONFIG.get("serving", _FALLBACK["serving"])
TRAIN_BASE = _CONFIG.get("train_base", _FALLBACK["train_base"])

# Trainable base model (HuggingFace id). Env override wins over the config file.
BASE_MODEL = os.environ.get("OPENTRADER_BASE_MODEL") or TRAIN_BASE.get(
    "huggingface", "Qwen/Qwen2.5-7B-Instruct"
)

SERVING_NAME = SERVING.get("name", "")
SERVING_MODEL_PATH = SERVING.get("model_path", "")
SERVING_ALIAS = SERVING.get("alias", "")
SERVING_ALIASES = SERVING.get("aliases", [])
SERVING_ALIAS_CSV = ",".join(SERVING_ALIASES) or SERVING_ALIAS
SERVING_PORT = SERVING.get("port", 5802)
SERVING_CTX_SIZE = SERVING.get("ctx_size", 16384)
SERVING_N_PREDICT = SERVING.get("n_predict", 2048)
TRAIN_BASE_GGUF = TRAIN_BASE.get("gguf", "")
