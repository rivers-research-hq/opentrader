#!/usr/bin/env python3
"""Adapter Registry — tracks every trained LoRA adapter across MoT versions.

Each adapter is a persistent record with:
  - Version string (cartographer name + tier + index, e.g. Ptolemy-S1)
  - Path to saved LoRA weights (HuggingFace safetensors)
  - Training metadata (score, cycles, examples at training time)
  - Lifecycle status (pending / active / rolled_back / retired)
  - Post-activation performance tracking (win rate, return, cycles run)
  - Lineage (previous version, reason for rollback)

The registry is used by:
  - finetune_cycle.py — registers new adapters on training completion
  - harness.py — checks for new adapters, auto-activates, tracks perf
  - dashboard.py — displays adapter lineage and promote/rollback controls
"""

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.adapter_registry")

REGISTRY_FILE = "adapter_registry.json"
ACTIVE_SYMLINK = "current_adapter"
BASE_MODEL_CONFIG_DIR = "models/base_model_config"  # cached HF config for HF inference


@dataclass
class AdapterRecord:
    version: str
    path: str                          # path to saved LoRA weights dir
    created_at: str = ""                # ISO timestamp
    base_model: str = ""               # base GGUF filename for deep_eval
    gguf_path: str = ""                # relative path to LoRA GGUF for deep_eval
    eval_score: float = 0.0            # latest deep_eval weighted_score
    deep_eval_skipped: str = ""        # reason if deep_eval cannot run
    status: str = "pending"            # pending | active | rolled_back | retired
    training_score: float = 0.0        # MoT score at training time
    training_cycles: int = 0           # total cycles when trained
    training_examples: int = 0         # number of training examples used
    previous_version: str = ""
    renamed_from: str = ""
    activated_at: Optional[str] = None
    deactivated_at: Optional[str] = None
    rollback_reason: str = ""
    performance: Dict = None            # {win_rate, avg_return, cycles_completed}

    def __post_init__(self):
        if self.performance is None:
            self.performance = {
                "win_rate": None,
                "avg_return": None,
                "cycles_completed": 0,
                "avg_confidence": None,
            }


class AdapterRegistry:
    """Persistent registry of LoRA adapters trained across MoT versions."""

    def __init__(self, state_dir: str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, AdapterRecord] = {}
        self._load()

    def _path(self) -> Path:
        return self.state_dir / REGISTRY_FILE

    def _active_link(self) -> Path:
        return self.state_dir / ACTIVE_SYMLINK

    def _load(self) -> None:
        path = self._path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for k, v in data.items():
                    self._records[k] = AdapterRecord(**v)
                logger.info(f"Loaded {len(self._records)} adapter(s) from registry")
            except Exception as e:
                logger.warning(f"Failed to load adapter registry: {e}")

    def _save(self) -> None:
        data = {k: asdict(r) for k, r in self._records.items()}

        # Merge external fields that may have been added by eval_deploy
        # or manual patching (base_model, gguf_path, eval_score, deep_eval_skipped).
        # These fields are not managed by the harness — they come from eval_deploy
        # and manual configuration.  The in-memory defaults (empty strings, 0.0)
        # would otherwise overwrite externally-written values on every cycle.
        _MERGE_FIELDS = ("base_model", "gguf_path", "eval_score", "deep_eval_skipped")
        existing_path = self._path()
        if existing_path.exists():
            try:
                existing = json.loads(existing_path.read_text())
                for version, ext_fields in existing.items():
                    if version not in data:
                        continue
                    for field in _MERGE_FIELDS:
                        ext_val = ext_fields.get(field)
                        if ext_val is not None:
                            data[version][field] = ext_val
            except Exception:
                pass

        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self._path())

    # ── Query ───────────────────────────────────────────────────

    def list_adapters(self, include_retired: bool = False) -> List[AdapterRecord]:
        """Return all adapters, newest first."""
        records = list(self._records.values())
        if not include_retired:
            records = [r for r in records if r.status != "retired"]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records

    def get(self, version: str) -> Optional[AdapterRecord]:
        return self._records.get(version)

    def get_active(self) -> Optional[AdapterRecord]:
        """Return the currently active adapter, or None."""
        for r in self._records.values():
            if r.status == "active":
                return r
        return None

    def latest(self) -> Optional[AdapterRecord]:
        """Return the most recently created adapter (any status)."""
        records = sorted(
            self._records.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return records[0] if records else None

    def count(self) -> int:
        return len(self._records)

    # ── Registration ─────────────────────────────────────────────

    def register(self, version: str, path: str, training_score: float = 0.0,
                 training_cycles: int = 0, training_examples: int = 0,
                 previous_version: str = "") -> AdapterRecord:
        """Register a new adapter. If version exists with lineage, refuse."""
        existing = self._records.get(version)
        if existing and existing.previous_version:
            logger.warning(
                f"Refusing to re-register versioned adapter {version} "
                f"(lineage exists — prev={existing.previous_version}). "
                f"Use bump suffix."
            )
            # Update metadata on existing record but don't overwrite lineage
            existing.training_score = max(existing.training_score, training_score)
            existing.training_examples = training_examples or existing.training_examples
            self._save()
            return existing

        now = datetime.now(timezone.utc).isoformat()
        record = AdapterRecord(
            version=version,
            path=path,
            created_at=now,
            status="pending",
            training_score=training_score,
            training_cycles=training_cycles,
            training_examples=training_examples,
            previous_version=previous_version,
        )
        self._records[version] = record
        self._save()
        logger.info(f"Registered adapter: {version} at {path}")
        return record

    # ── Lifecycle ────────────────────────────────────────────────

    def promote(self, version: str) -> Optional[AdapterRecord]:
        """Promote an adapter to active. Deactivates previous active."""
        record = self._records.get(version)
        if not record:
            logger.warning(f"Cannot promote unknown adapter: {version}")
            return None

        # Deactivate current active
        current = self.get_active()
        if current and current.version != version:
            self._deactivate(current.version, f"superseded by {version}")

        # Activate
        now = datetime.now(timezone.utc).isoformat()
        record.status = "active"
        record.activated_at = now
        self._save()

        # Write symlink for other components to find
        self._write_active_symlink(record)

        logger.info(f"Promoted adapter: {version}")
        return record

    def rollback(self, version: str, reason: str = "performance regression") -> Optional[AdapterRecord]:
        """Rollback to a previous adapter version. Retires current."""
        target = self._records.get(version)
        if not target:
            logger.warning(f"Cannot rollback to unknown adapter: {version}")
            return None

        # Deactivate current
        current = self.get_active()
        if current:
            self._deactivate(current.version, reason)

        # Activate target (if not already active)
        if target.status != "active":
            target.status = "active"
            target.activated_at = datetime.now(timezone.utc).isoformat()
            self._write_active_symlink(target)

        self._save()
        logger.info(f"Rolled back to adapter: {version} (reason: {reason})")
        return target

    def retire(self, version: str, reason: str = "") -> None:
        """Soft-delete an adapter."""
        record = self._records.get(version)
        if record:
            record.status = "retired"
            record.rollback_reason = reason
            self._save()
            logger.info(f"Retired adapter: {version} ({reason})")

    def _deactivate(self, version: str, reason: str = "") -> None:
        record = self._records.get(version)
        if record and record.status == "active":
            record.status = "rolled_back"
            record.deactivated_at = datetime.now(timezone.utc).isoformat()
            record.rollback_reason = reason

    def _write_active_symlink(self, record: AdapterRecord) -> None:
        """Write a symlink pointing to the active adapter's directory."""
        link = self._active_link()
        target = Path(record.path)
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(target.resolve())
        except OSError:
            # Symlinks may not work everywhere; fall back to a text pointer
            link.write_text(str(target.resolve()))

    def _read_active_symlink(self) -> Optional[str]:
        """Read the active adapter path from symlink/pointer file."""
        link = self._active_link()
        if not link.exists():
            return None
        try:
            if link.is_symlink():
                return str(link.resolve())
            return link.read_text().strip()
        except Exception:
            return None

    # ── Performance Tracking ─────────────────────────────────────

    def update_performance(self, version: str, win_rate: float = None,
                           avg_return: float = None,
                           avg_confidence: float = None) -> None:
        """Update performance metrics for an active adapter."""
        record = self._records.get(version)
        if not record:
            return
        p = record.performance
        if win_rate is not None:
            # Rolling average
            old = p.get("win_rate") or 0
            n = p.get("cycles_completed", 0)
            p["win_rate"] = (old * n + win_rate) / (n + 1) if n > 0 else win_rate
        if avg_return is not None:
            old = p.get("avg_return") or 0
            n = p.get("cycles_completed", 0)
            p["avg_return"] = (old * n + avg_return) / (n + 1) if n > 0 else avg_return
        if avg_confidence is not None:
            old = p.get("avg_confidence") or 0
            n = p.get("cycles_completed", 0)
            p["avg_confidence"] = (old * n + avg_confidence) / (n + 1) if n > 0 else avg_confidence
        p["cycles_completed"] = p.get("cycles_completed", 0) + 1
        self._save()

    def get_adapter_for_dashboard(self) -> Dict:
        """Return structured data for the dashboard adapter panel."""
        active = self.get_active()
        all_adapters = self.list_adapters(include_retired=False)
        return {
            "active_version": active.version if active else None,
            "active_status": active.status if active else "none",
            "active_performance": active.performance if active else {},
            "adapter_count": self.count(),
            "adapters": [
                {
                    "version": r.version,
                    "status": r.status,
                    "created_at": r.created_at,
                    "training_score": r.training_score,
                    "training_examples": r.training_examples,
                    "performance": r.performance,
                    "previous_version": r.previous_version,
                }
                for r in all_adapters[:20]  # newest 20
            ],
        }


