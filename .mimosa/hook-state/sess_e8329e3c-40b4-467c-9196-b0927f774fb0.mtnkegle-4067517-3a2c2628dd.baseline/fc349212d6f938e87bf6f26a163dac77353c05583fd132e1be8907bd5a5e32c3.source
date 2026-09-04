from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download

from .config import Settings, validate_repo_id


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _file_size(sibling: Any) -> int:
    direct = getattr(sibling, "size", None)
    if isinstance(direct, int):
        return direct
    lfs = getattr(sibling, "lfs", None)
    if isinstance(lfs, dict):
        return int(lfs.get("size") or 0)
    nested = getattr(lfs, "size", None)
    return int(nested or 0)


def _license_from_tags(tags: list[str]) -> str | None:
    return next((tag.split(":", 1)[1] for tag in tags if tag.startswith("license:")), None)


def _parameter_count(info: Any) -> int | None:
    safetensors = getattr(info, "safetensors", None)
    parameters = getattr(safetensors, "parameters", None)
    if isinstance(parameters, dict):
        values = [value for value in parameters.values() if isinstance(value, int)]
        return sum(values) if values else None
    if isinstance(safetensors, dict):
        raw = safetensors.get("parameters")
        if isinstance(raw, dict):
            values = [value for value in raw.values() if isinstance(value, int)]
            return sum(values) if values else None
    return None


class HubService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api = HfApi(
            endpoint=settings.hf_endpoint,
            token=settings.hf_token or False,
            library_name="hugginghack",
            library_version=settings.app_version,
        )

    @staticmethod
    def serialize_model(info: Any) -> dict[str, Any]:
        tags = list(getattr(info, "tags", None) or [])
        model_id = getattr(info, "id", None) or getattr(info, "modelId", None)
        return {
            "id": model_id,
            "author": getattr(info, "author", None)
            or (model_id.split("/", 1)[0] if model_id and "/" in model_id else None),
            "pipeline_tag": getattr(info, "pipeline_tag", None),
            "library_name": getattr(info, "library_name", None),
            "tags": tags,
            "downloads": int(getattr(info, "downloads", None) or 0),
            "downloads_all_time": int(getattr(info, "downloads_all_time", None) or 0),
            "likes": int(getattr(info, "likes", None) or 0),
            "trending_score": float(getattr(info, "trending_score", None) or 0),
            "last_modified": _iso(getattr(info, "last_modified", None)),
            "created_at": _iso(getattr(info, "created_at", None)),
            "private": bool(getattr(info, "private", False)),
            "gated": getattr(info, "gated", False),
            "sha": getattr(info, "sha", None),
            "license": _license_from_tags(tags),
            "parameter_count": _parameter_count(info),
        }

    def search_models(
        self,
        search: str = "",
        sort: str = "trending",
        task: str = "",
        library: str = "",
        app: str = "",
        parameters: str = "",
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        sort_map = {
            "trending": "trending_score",
            "downloads": "downloads",
            "updated": "last_modified",
            "likes": "likes",
        }
        filters = [value for value in (library,) if value]
        models = self.api.list_models(
            search=search or None,
            pipeline_tag=task or None,
            filter=filters or None,
            apps=app or None,
            num_parameters=parameters or None,
            sort=sort_map.get(sort, "trending_score"),
            limit=max(1, min(limit, 50)),
            full=True,
        )
        return [self.serialize_model(info) for info in models]

    def model_details(self, repo_id: str, revision: str = "main") -> dict[str, Any]:
        validated = validate_repo_id(repo_id)
        info = self.api.model_info(
            validated,
            revision=revision,
            files_metadata=True,
            securityStatus=True,
        )
        result = self.serialize_model(info)
        files = []
        for sibling in getattr(info, "siblings", None) or []:
            files.append(
                {
                    "path": getattr(sibling, "rfilename", ""),
                    "size": _file_size(sibling),
                    "blob_id": getattr(sibling, "blob_id", None),
                }
            )
        result.update(
            {
                "revision": revision,
                "files": files,
                "total_bytes": sum(item["size"] for item in files),
                "security_status": self._security_status(info),
                "source_url": f"{self.settings.hf_endpoint}/{validated}",
            }
        )
        return result

    @staticmethod
    def _security_status(info: Any) -> Any:
        value = getattr(info, "security_repo_status", None)
        if value is None:
            return None
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, (dict, list, str, int, float, bool)):
            return value
        return str(value)

    def read_model_card(self, repo_id: str, revision: str = "main") -> str | None:
        validated = validate_repo_id(repo_id)
        try:
            path = hf_hub_download(
                repo_id=validated,
                filename="README.md",
                revision=revision,
                cache_dir=self.settings.hub_cache_path,
                token=self.settings.hf_token or False,
                endpoint=self.settings.hf_endpoint,
            )
        except Exception:
            return None
        return Path(path).read_text(encoding="utf-8", errors="replace")[:120_000]

