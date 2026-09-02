from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import Settings
from .database import Database


WEIGHT_EXTENSIONS = {
    ".safetensors",
    ".gguf",
    ".bin",
    ".pt",
    ".pth",
    ".ckpt",
    ".onnx",
    ".h5",
    ".msgpack",
}
UNSAFE_EXTENSIONS = {".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt"}
CONFIG_FILES = {"config.json", "model_index.json", "tokenizer.json", "params.json"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def directory_stats(path: Path, include_cache: bool = False) -> tuple[int, int, float]:
    size = 0
    count = 0
    latest = path.stat().st_mtime if path.exists() else 0
    for root, directories, files in os.walk(path):
        directories[:] = [
            name for name in directories if include_cache or name not in {".cache", "__pycache__"}
        ]
        for name in files:
            file_path = Path(root) / name
            try:
                stat = file_path.stat()
            except (FileNotFoundError, PermissionError, OSError):
                continue
            size += stat.st_size
            count += 1
            latest = max(latest, stat.st_mtime)
    return size, count, latest


def parse_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


class LocalModelIndexer:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    def _candidates(self) -> Iterable[Path]:
        storage = self.settings.model_storage
        if not storage.exists():
            return
        for root, directories, files in os.walk(storage):
            path = Path(root)
            relative = path.relative_to(storage)
            directories[:] = [
                name
                for name in directories
                if name not in {".cache", "__pycache__"} and not name.startswith(".")
            ]
            if len(relative.parts) > 3:
                directories[:] = []
                continue
            file_set = set(files)
            has_manifest = ".hugginghack.json" in file_set
            has_config = bool(file_set & CONFIG_FILES)
            has_weight = any(Path(name).suffix.lower() in WEIGHT_EXTENSIONS for name in files)
            if has_manifest or has_config or has_weight:
                if has_manifest:
                    manifest = parse_json(path / ".hugginghack.json")
                    if manifest.get("status") not in {None, "complete"}:
                        directories[:] = []
                        continue
                yield path
                directories[:] = []

    def index_path(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        if self.settings.model_storage != resolved and self.settings.model_storage not in resolved.parents:
            raise ValueError("Model path escapes configured storage")
        relative = resolved.relative_to(self.settings.model_storage).as_posix()
        manifest = parse_json(resolved / ".hugginghack.json")
        config = parse_json(resolved / "config.json")
        repo_id = manifest.get("repo_id") or (
            relative if "/" in relative else f"local/{relative}"
        )
        size, file_count, latest = directory_stats(resolved)
        tags = manifest.get("tags") or []
        record = {
            "repo_id": repo_id,
            "relative_path": relative,
            "size_bytes": size,
            "file_count": file_count,
            "modified_at": datetime.fromtimestamp(latest, timezone.utc).isoformat(),
            "downloaded_at": manifest.get("downloaded_at"),
            "revision": manifest.get("revision"),
            "sha": manifest.get("sha"),
            "pipeline_tag": manifest.get("pipeline_tag") or config.get("model_type"),
            "library_name": manifest.get("library_name"),
            "license": manifest.get("license"),
            "tags_json": json.dumps(tags),
            "config_json": json.dumps(
                {
                    "architectures": config.get("architectures"),
                    "model_type": config.get("model_type"),
                    "torch_dtype": config.get("torch_dtype"),
                    "vocab_size": config.get("vocab_size"),
                }
            ),
            "source_url": manifest.get("source_url"),
            "managed": 1 if manifest else 0,
        }
        self.database.upsert_local_model(record)
        return self.database.get_local_model(repo_id)

    def scan(self) -> dict[str, Any]:
        indexed = []
        paths: set[str] = set()
        for candidate in self._candidates() or []:
            try:
                model = self.index_path(candidate)
            except (OSError, ValueError):
                continue
            if model:
                indexed.append(model)
                paths.add(model["relative_path"])
        self.database.prune_local_models(paths)
        return {"count": len(indexed), "models": indexed, "scanned_at": utc_now()}

    def files_for_model(self, repo_id: str, limit: int = 500) -> dict[str, Any] | None:
        model = self.database.get_local_model(repo_id)
        if not model:
            return None
        root = (self.settings.model_storage / model["relative_path"]).resolve()
        if self.settings.model_storage != root and self.settings.model_storage not in root.parents:
            raise ValueError("Indexed path escapes configured storage")
        files = []
        unsafe_count = 0
        for current, directories, names in os.walk(root):
            directories[:] = [name for name in directories if name != ".cache"]
            for name in names:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                try:
                    stat = path.stat()
                except (OSError, PermissionError):
                    continue
                suffix = path.suffix.lower()
                unsafe = suffix in UNSAFE_EXTENSIONS
                unsafe_count += int(unsafe)
                files.append(
                    {
                        "path": relative,
                        "size": stat.st_size,
                        "modified_at": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                        "unsafe_serialization": unsafe,
                    }
                )
                if len(files) >= limit:
                    break
            if len(files) >= limit:
                break
        files.sort(key=lambda item: (-item["size"], item["path"]))
        return {
            "model": model,
            "files": files,
            "unsafe_file_count": unsafe_count,
            "truncated": len(files) >= limit,
        }

