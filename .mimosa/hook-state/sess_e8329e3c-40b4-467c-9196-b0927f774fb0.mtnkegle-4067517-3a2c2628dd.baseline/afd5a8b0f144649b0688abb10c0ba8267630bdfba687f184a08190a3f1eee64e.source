from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(1, min(value, maximum))


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "HuggingHack")
    app_version: str = os.getenv("APP_VERSION", "1.0.0")
    model_storage: Path = Path(os.getenv("MODEL_STORAGE", "/models")).expanduser().resolve()
    data_dir: Path = Path(os.getenv("DATA_DIR", "/data")).expanduser().resolve()
    hf_endpoint: str = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    hf_token: str | None = os.getenv("HF_TOKEN") or None
    max_concurrent_downloads: int = _positive_int("MAX_CONCURRENT_DOWNLOADS", 2, 8)
    download_workers_per_job: int = _positive_int("DOWNLOAD_WORKERS_PER_JOB", 4, 16)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "hugginghack.sqlite3"

    @property
    def hub_cache_path(self) -> Path:
        return self.data_dir / "hub-cache"

    def ensure_directories(self) -> None:
        self.model_storage.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.hub_cache_path.mkdir(parents=True, exist_ok=True)


settings = Settings()


def validate_repo_id(repo_id: str) -> str:
    value = repo_id.strip()
    if not REPO_ID_PATTERN.fullmatch(value):
        raise ValueError("Repository ID must use the form owner/model-name.")
    return value


def repository_path(repo_id: str) -> Path:
    validated = validate_repo_id(repo_id)
    target = (settings.model_storage / validated).resolve()
    if settings.model_storage != target and settings.model_storage not in target.parents:
        raise ValueError("Repository path escapes the configured model storage.")
    return target

