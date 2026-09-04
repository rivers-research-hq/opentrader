#!/usr/bin/env python3
"""OpenTrader Model Manager — discovers, downloads, and launches models.

Three model origins:
  - llama-swap:   Models registered in the local llama-swap instance
  - huggingface:  Models downloaded from HF, organized under models/hf/<category>/
  - trained:      Locally fine-tuned models with version tracking

API exposed to dashboard:
  GET  /api/models/origins       → list of origin types
  GET  /api/models?origin=X      → list models for origin
  GET  /api/models/:id/versions  → version list (trained only)
  POST /api/models/launch        → launch a model
  POST /api/models/download      → download from HF
  GET  /api/models/status        → running model + VRAM info
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.models")

PROJECT = str(Path(__file__).resolve().parent)
MODELS_DIR = Path(PROJECT) / "models"
TRAINED_DIR = MODELS_DIR / "_trained"
HF_DIR = MODELS_DIR / "_hf"
LLAMA_SWAP_URL = "http://127.0.0.1:8080"

# ── Model Role definitions ─────────────────────────────────────

ROLES = {
    "trading": {
        "name": "Trading Signal",
        "desc": "Models for live trading decisions",
        "icon": "📊",
    },
    "student": {
        "name": "Student Trainer",
        "desc": "Fast models for teacher/student training",
        "icon": "🧠",
    },
    "teacher": {
        "name": "Teacher/Scorer",
        "desc": "Deep reasoning models for scenario generation",
        "icon": "🎓",
    },
    "regime": {
        "name": "Regime Classifier",
        "desc": "Models for market regime detection",
        "icon": "🌡️",
    },
    "code": {"name": "Development", "desc": "Coding/development models", "icon": "💻"},
}


# Known model → role assignments (by name substring match, case-insensitive)
# Load from config/model_roles.json; fall back to defaults below if missing.
def _load_role_rules() -> tuple:
    """Load role rules from config file, falling back to hardcoded defaults."""
    config_path = Path(PROJECT) / "config" / "model_roles.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            rules = data.get("rules", [])
            default = data.get("default_roles", ["trading"])
            return rules, default
        except Exception:
            pass
    # Hardcoded fallback
    fallback_rules = [
        ("deckard", ["trading"], 100),
        ("gemma-4-e4b", ["trading", "student"], 90),
        ("agentic", ["trading", "teacher"], 80),
        ("hermes", ["trading", "student"], 70),
        ("qwen", ["trading", "teacher"], 70),
        ("coder", ["code", "student"], 60),
        ("sushi-coder", ["code"], 60),
        ("neo-code", ["code", "teacher"], 50),
        ("v2-coder", ["code", "student"], 60),
    ]
    return fallback_rules, ["trading"]


ROLE_RULES, DEFAULT_ROLES = _load_role_rules()

# ── Ensure model directories exist ────────────────────────────

for d in [MODELS_DIR, TRAINED_DIR, HF_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Data structures ───────────────────────────────────────────


@dataclass
class ModelInfo:
    id: str
    origin: str  # "llama-swap", "huggingface", "trained"
    name: str
    category: str = (
        ""  # organizational category (for HF models: "base", "coding", etc.)
    )
    description: str = ""
    path: str = ""  # local filesystem path
    size_gb: float = 0.0
    loaded: bool = False
    versions: List[str] = field(default_factory=list)


@dataclass
class ModelVersion:
    version: str
    created: str
    note: str = ""
    path: str = ""
    score: float = 0.0  # best TraderBench score at time of save


# ── Model Manager ─────────────────────────────────────────────


class ModelManager:
    """Discovers, launches, and manages models."""

    def __init__(self, llama_swap_url: str = LLAMA_SWAP_URL):
        self.llama_swap_url = llama_swap_url
        self.running_pids: Dict[str, int] = {}
        self.data_dir = self._find_data_dir()
        self.schedule_path = Path(str(self.data_dir)) / "model_schedule.json"
        self.schedule = self._load_schedule()
        # Estimated VRAM per model (GB)
        self.model_vram: Dict[str, float] = {
            "deckard-v2": 2.0,
            "gemma-4-e4b": 4.0,
            "gemma-4-12B-agentic": 10.0,
            "gemma-4-12B-agentic-ngram": 10.0,
            "gemma4-v2-coder": 8.0,
            "qwen3.6-35b-a3b": 16.0,
            "qwythos-9b-mtp": 5.5,
            "hermes-3-llama-3.1-8b": 6.0,
            "gemma-4-e4b-2b": 2.0,
            "deepseek-r1-7b": 6.0,
            "qwen2.5-7b": 6.0,
        }

    # ── Data directory ──────────────────────────────────────────

    def _find_data_dir(self) -> Path:
        """Find data directory relative to project root."""
        candidates = [
            Path(__file__).parent / "data",
            Path.cwd() / "data",
            Path.home() / "opentrader" / "data",
        ]
        for d in candidates:
            if d.exists():
                return d
        d = candidates[0]
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── Schedule ────────────────────────────────────────────────

    DEFAULT_SCHEDULE = {
        "trading": {"model": "ls:qwythos-9b-mtp", "start": 0, "end": 24, "vram": 5.5},
        "student": {"model": "ls:qwythos-9b-mtp", "start": 0, "end": 24, "vram": 5.5},
        "teacher": {"model": "ls:qwythos-9b-mtp", "start": 0, "end": 24, "vram": 5.5},
        "regime": {"model": "ls:deckard-v2", "start": 0, "end": 24, "vram": 2.0},
        "code": {"model": "ls:gemma4-v2-coder", "start": 0, "end": 24, "vram": 8.0},
    }

    def _load_schedule(self) -> dict:
        """Load schedule from disk."""
        try:
            if self.schedule_path.exists():
                data = json.loads(self.schedule_path.read_text())
                # Merge with defaults for any missing roles
                for role, default in self.DEFAULT_SCHEDULE.items():
                    if role not in data:
                        data[role] = dict(default)
                return data
        except Exception:
            pass
        return {k: dict(v) for k, v in self.DEFAULT_SCHEDULE.items()}

    def _save_schedule(self):
        """Persist schedule to disk."""
        try:
            self.schedule_path.parent.mkdir(parents=True, exist_ok=True)
            self.schedule_path.write_text(json.dumps(self.schedule, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save schedule: {e}")

    def _total_vram(self) -> float:
        """Authoritative total VRAM (GB), falling back to 16 if undeterminable."""
        try:
            return float(self.get_status().get("vram_total_gb", 16.0))
        except Exception:
            return 16.0

    def get_schedule(self) -> dict:
        """Return the schedule with VRAM usage per hour."""
        # Calculate VRAM at each hour
        hourly_vram = [0.0] * 24
        for role, slot in self.schedule.items():
            vram = slot.get("vram", 0)
            start = int(slot.get("start", 0))
            end = int(slot.get("end", 24))
            for h in range(start, end):
                if 0 <= h < 24:
                    hourly_vram[h] += vram

        return {
            "schedule": self.schedule,
            "hourly_vram": [round(v, 1) for v in hourly_vram],
            "total_vram": self._total_vram(),
        }

    def set_schedule(self, role: str, slot: dict) -> dict:
        """Update a role's time slot and check VRAM conflicts."""
        self.schedule[role] = slot
        self._save_schedule()
        result = self.get_schedule()

        # Check for VRAM overflow
        total = self._total_vram()
        warnings = []
        for h, vram in enumerate(result["hourly_vram"]):
            if vram > total:
                warnings.append(f"Hour {h}: {vram}G exceeds {total:.0f}G limit")
        if warnings:
            result["warnings"] = warnings
        return result

    # ── Role inference ───────────────────────────────────────

    @staticmethod
    def _infer_role(name: str) -> List[str]:
        """Infer model roles from name using substring rules."""
        name_lower = name.lower()
        matched = []
        for keyword, roles, priority in ROLE_RULES:
            if keyword in name_lower:
                matched.append((priority, roles))
        if matched:
            matched.sort(key=lambda x: -x[0])  # highest priority first
            return matched[0][1]
        return list(DEFAULT_ROLES)

    # ── Discovery ────────────────────────────────────────────

    def get_origins(self) -> List[dict]:
        """Return available model origin types."""
        return [
            {
                "id": "llama-swap",
                "name": "Local (llama-swap)",
                "description": "Models registered in llama-swap",
            },
            {
                "id": "huggingface",
                "name": "HuggingFace",
                "description": "Download models from HuggingFace",
            },
            {
                "id": "trained",
                "name": "Base / Locally Trained",
                "description": "Base models or locally fine-tuned checkpoints",
            },
        ]

    def get_roles(self) -> List[dict]:
        """Return available model role types."""
        return [
            {"id": k, "name": v["name"], "description": v["desc"], "icon": v["icon"]}
            for k, v in ROLES.items()
        ]

    def get_models(self, origin: str = None, role: str = None) -> List[dict]:
        """List models, optionally filtered by origin and/or role."""
        all_models = []
        all_models.extend(self._list_llama_swap())
        all_models.extend(self._list_hf_models())
        all_models.extend(self._list_trained_models())

        if origin:
            all_models = [m for m in all_models if m["origin"] == origin]
        if role:
            all_models = [m for m in all_models if role in m.get("roles", [])]
        return all_models

    def _list_llama_swap(self) -> List[dict]:
        """Fetch models from llama-swap /v1/models."""
        try:
            req = urllib.request.Request(f"{self.llama_swap_url}/v1/models")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            models = []
            for m in data.get("data", []):
                mid = m["id"]
                loaded = self._check_loaded(mid)
                roles = self._infer_role(mid)
                models.append(
                    {
                        "id": f"ls:{mid}",
                        "origin": "llama-swap",
                        "name": mid,
                        "description": f"llama-swap model: {mid}",
                        "roles": roles,
                        "loaded": loaded,
                        "size_gb": 0,
                        "versions": [],
                    }
                )
            return models
        except Exception as e:
            logger.warning(f"Could not fetch llama-swap models: {e}")
            return []

    def _list_hf_models(self) -> List[dict]:
        """Scan HF directory for downloaded models, organized by category."""
        models = []
        if not HF_DIR.exists():
            return models
        for category_dir in sorted(HF_DIR.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith("."):
                continue
            category = category_dir.name
            for model_dir in sorted(category_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                name = model_dir.name
                size_gb = self._dir_size_gb(model_dir)
                roles = self._infer_role(name)
                models.append(
                    {
                        "id": f"hf:{category}/{name}",
                        "origin": "huggingface",
                        "name": name,
                        "category": category,
                        "description": f"HF model: {category}/{name}",
                        "path": str(model_dir),
                        "roles": roles,
                        "size_gb": round(size_gb, 2),
                        "loaded": False,
                        "versions": [],
                    }
                )
        return models

    def _list_trained_models(self) -> List[dict]:
        """Scan trained models directory for versioned checkpoints."""
        models = {}
        if not TRAINED_DIR.exists():
            return list(models.values())

        for model_dir in sorted(TRAINED_DIR.iterdir()):
            if not model_dir.is_dir() or model_dir.name.startswith("."):
                continue
            name = model_dir.name
            version_info = self._load_version_info(model_dir)
            versions = []
            for ver in version_info:
                versions.append(ver["version"])
                # Also check for subdirectories
            for sub in sorted(model_dir.iterdir()):
                if sub.is_dir() and re.match(r"^v?\d", sub.name):
                    versions.append(sub.name)

            size_gb = self._dir_size_gb(model_dir)
            roles = self._infer_role(name)
            info = models.get(
                name,
                {
                    "id": f"trained:{name}",
                    "origin": "trained",
                    "name": name,
                    "description": f"Locally trained model: {name}",
                    "path": str(model_dir),
                    "roles": roles,
                    "size_gb": 0,
                    "loaded": False,
                    "versions": [],
                },
            )
            info["size_gb"] = round(size_gb, 2)
            for v in versions:
                if v not in info["versions"]:
                    info["versions"].append(v)
            info["versions"].sort(reverse=True)
            models[name] = info

        return list(models.values())

    def _load_version_info(self, model_dir: Path) -> List[dict]:
        """Load version metadata from a trained model directory."""
        vi_path = model_dir / "versions.json"
        if vi_path.exists():
            try:
                return json.loads(vi_path.read_text())
            except Exception:
                pass
        return []

    def get_versions(self, model_id: str) -> List[dict]:
        """Get version list for a trained model."""
        if not model_id.startswith("trained:"):
            return []
        name = model_id[8:]  # strip "trained:"
        model_dir = TRAINED_DIR / name
        if not model_dir.exists():
            return []

        versions = self._load_version_info(model_dir)
        # Also scan subdirectories
        existing_versions = {v["version"] for v in versions}
        for sub in sorted(model_dir.iterdir()):
            if (
                sub.is_dir()
                and re.match(r"^v?\d", sub.name)
                and sub.name not in existing_versions
            ):
                versions.append(
                    {
                        "version": sub.name,
                        "created": datetime.fromtimestamp(
                            sub.stat().st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "note": "",
                        "path": str(sub),
                        "score": 0.0,
                    }
                )
        versions.sort(key=lambda v: v.get("created", ""), reverse=True)
        return versions

    # ── Model state ────────────────────────────────────────

    def _check_loaded(self, model_name: str) -> bool:
        """Check if a model exists in llama-swap's model list."""
        # Lightweight check: just verify model exists in the list.
        # Avoids hitting /v1/chat/completions which is slow per-model.
        try:
            req = urllib.request.Request(f"{self.llama_swap_url}/v1/models")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                for m in data.get("data", []):
                    if m["id"] == model_name:
                        return True
            return False
        except Exception:
            return False

    def get_status(self) -> dict:
        """Get system status: VRAM, running model, etc."""
        try:
            result = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            vram_used = vram_total = None
            for line in result.stdout.split("\n"):
                if "VRAM Total Memory (B)" in line:
                    parts = line.split(":")
                    try:
                        vram_total = int(parts[-1].strip())
                    except:
                        pass
                elif "VRAM Total Used Memory (B)" in line:
                    parts = line.split(":")
                    try:
                        vram_used = int(parts[-1].strip())
                    except:
                        pass
        except Exception:
            vram_used = None
            vram_total = None

        # Simplified VRAM from /sys (fallback)
        if vram_used is None or vram_total is None:
            try:
                used = int(
                    open("/sys/class/drm/card0/device/mem_info_vram_used")
                    .read()
                    .strip()
                )
                total = int(
                    open("/sys/class/drm/card0/device/mem_info_vram_total")
                    .read()
                    .strip()
                )
                vram_used = used
                vram_total = total
            except Exception:
                pass

        return {
            "vram_used_gb": round(vram_used / (1024**3), 1) if vram_used else 0,
            "vram_total_gb": round(vram_total / (1024**3), 1) if vram_total else 16,
            "vram_pct": round(vram_used / vram_total * 100, 1)
            if vram_used and vram_total
            else 0,
            "loaded_models": list(self.running_pids.keys()),
        }

    # ── Actions ────────────────────────────────────────────

    def launch_model(self, origin: str, name: str) -> dict:
        """Launch a model via llama-swap."""
        try:
            # Build the payload for llama-swap completion to trigger loading
            req = urllib.request.Request(
                f"{self.llama_swap_url}/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": name,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "stream": False,
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode())
                return {
                    "success": True,
                    "model": name,
                    "message": f"Model {name} loaded and responding",
                }
        except Exception as e:
            logger.error(f"Failed to launch {name}: {e}")
            return {
                "success": False,
                "model": name,
                "error": str(e),
            }

    def download_hf(self, repo_id: str, category: str = "downloaded") -> dict:
        """Download a model from HuggingFace."""
        try:
            from huggingface_hub import snapshot_download
        except ImportError:
            return {
                "success": False,
                "error": "huggingface_hub not installed. Run: pip install huggingface_hub",
            }

        try:
            target_dir = HF_DIR / category / repo_id.replace("/", "--")
            if target_dir.exists():
                return {
                    "success": False,
                    "error": f"Model already exists at {target_dir}",
                }

            logger.info(f"Downloading {repo_id} to {target_dir}...")
            target_dir.mkdir(parents=True, exist_ok=True)

            path = snapshot_download(
                repo_id=repo_id,
                local_dir=str(target_dir),
                local_dir_use_symlinks=False,
                resume_download=True,
                ignore_patterns=[
                    "*.safetensors",
                    "*.bin",
                ],  # skip full weights, get config+tokenizer
            )

            return {
                "success": True,
                "path": path,
                "message": f"Downloaded {repo_id} to {path}",
            }
        except Exception as e:
            logger.error(f"HF download failed: {e}")
            return {"success": False, "error": str(e)}

    def save_trained_version(
        self, model_name: str, version: str, note: str = "", score: float = 0.0
    ) -> dict:
        """Register a trained model version."""
        model_dir = TRAINED_DIR / model_name
        model_dir.mkdir(parents=True, exist_ok=True)

        vi_path = model_dir / "versions.json"
        versions = []
        if vi_path.exists():
            try:
                versions = json.loads(vi_path.read_text())
            except Exception:
                pass

        # Check if version exists
        for v in versions:
            if v["version"] == version:
                v["note"] = note
                v["score"] = score
                v["created"] = datetime.now(timezone.utc).isoformat()
                break
        else:
            versions.append(
                {
                    "version": version,
                    "created": datetime.now(timezone.utc).isoformat(),
                    "note": note,
                    "path": str(model_dir / version),
                    "score": score,
                }
            )

        vi_path.write_text(json.dumps(versions, indent=2))
        return {"success": True, "version": version}

    @staticmethod
    def _dir_size_gb(path: Path) -> float:
        """Calculate directory size in GB."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return total / (1024**3)


# ── Singleton ────────────────────────────────────────────────

_manager: Optional[ModelManager] = None


def get_manager() -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager


# ── CLI ──────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OpenTrader Model Manager")
    parser.add_argument(
        "--action", default="list", choices=["list", "status", "launch"]
    )
    parser.add_argument("--origin", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    mgr = get_manager()

    if args.action == "list":
        models = mgr.get_models(args.origin)
        if not models:
            print("No models found.")
            return
        print(f"{'Name':<40} {'Origin':<14} {'Roles':<24} {'Loaded':<8} {'Size':<8}")
        print("-" * 94)
        for m in models:
            loaded = "✓" if m.get("loaded") else " "
            size = f"{m.get('size_gb', 0):.1f}G" if m.get("size_gb") else "-"
            roles = ", ".join(m.get("roles", [])) if m.get("roles") else ""
            print(
                f"{m['name']:<40} {m['origin']:<14} {roles:<24} {loaded:<8} {size:<8}"
            )

    elif args.action == "status":
        st = mgr.get_status()
        print(
            f"VRAM: {st['vram_used_gb']}G / {st['vram_total_gb']}G ({st['vram_pct']}%)"
        )
        if st["loaded_models"]:
            print(f"Loaded: {', '.join(st['loaded_models'])}")

    elif args.action == "launch":
        if not args.model:
            print("--model required")
            return
        result = mgr.launch_model(args.origin or "llama-swap", args.model)
        print(f"Launch: {result.get('message', result.get('error', '?'))}")


if __name__ == "__main__":
    main()
