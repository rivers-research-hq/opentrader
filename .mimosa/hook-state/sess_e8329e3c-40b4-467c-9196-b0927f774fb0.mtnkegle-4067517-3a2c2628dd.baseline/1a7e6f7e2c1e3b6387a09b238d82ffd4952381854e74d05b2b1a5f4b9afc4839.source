from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .config import settings, validate_repo_id
from .database import Database
from .downloads import DownloadManager
from .hub_service import HubService
from .indexer import LocalModelIndexer


database = Database(settings.database_path)
hub = HubService(settings)
indexer = LocalModelIndexer(settings, database)
downloads = DownloadManager(settings, database, hub, indexer)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    database.initialize()
    await run_in_threadpool(indexer.scan)
    downloads.resume_unfinished()
    yield
    downloads.shutdown()


app = FastAPI(
    title="HuggingHack API",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class DownloadRequest(BaseModel):
    repo_id: str
    revision: str = Field(default="main", max_length=200)
    allow_patterns: list[str] = Field(default_factory=list, max_length=50)
    ignore_patterns: list[str] = Field(default_factory=list, max_length=50)
    mode: Literal["full", "safetensors", "gguf", "metadata", "custom"] = "full"

    @field_validator("repo_id")
    @classmethod
    def repo_is_valid(cls, value: str) -> str:
        return validate_repo_id(value)

    @field_validator("allow_patterns", "ignore_patterns")
    @classmethod
    def patterns_are_bounded(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            item = value.strip()
            if len(item) > 200:
                raise ValueError("File patterns must be 200 characters or fewer.")
            if item:
                cleaned.append(item)
        return cleaned


@app.get("/api/health")
def health() -> dict:
    settings.ensure_directories()
    usage = shutil.disk_usage(settings.model_storage)
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "storage": {
            "path": str(settings.model_storage),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "writable": os_access_writable(settings.model_storage),
        },
        "hf_token_configured": bool(settings.hf_token),
        "hf_endpoint": settings.hf_endpoint,
    }


def os_access_writable(path: Path) -> bool:
    try:
        probe = path / ".hugginghack-write-test"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@app.get("/api/hub/models")
async def search_hub_models(
    search: Annotated[str, Query(max_length=200)] = "",
    sort: Literal["trending", "downloads", "updated", "likes"] = "trending",
    task: Annotated[str, Query(max_length=100)] = "",
    library: Annotated[str, Query(max_length=100)] = "",
    app_filter: Annotated[str, Query(alias="app", max_length=100)] = "",
    parameters: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> dict:
    try:
        items = await run_in_threadpool(
            hub.search_models,
            search,
            sort,
            task,
            library,
            app_filter,
            parameters,
            limit,
        )
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Hugging Face Hub request failed: {error}") from error
    local_ids = {model["repo_id"] for model in database.list_local_models()}
    for item in items:
        item["local"] = item["id"] in local_ids
    return {"items": items, "count": len(items)}


@app.get("/api/hub/models/{repo_id:path}")
async def hub_model(repo_id: str, revision: str = "main") -> dict:
    try:
        validated = validate_repo_id(repo_id)
        details = await run_in_threadpool(hub.model_details, validated, revision)
        details["model_card"] = await run_in_threadpool(hub.read_model_card, validated, revision)
        details["local"] = database.get_local_model(validated) is not None
        return details
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Unable to load model: {error}") from error


@app.get("/api/downloads")
def list_downloads() -> dict:
    items = database.list_downloads()
    return {"items": items, "active": sum(item["status"] in {"queued", "preparing", "downloading"} for item in items)}


@app.get("/api/downloads/{download_id}")
def get_download(download_id: str) -> dict:
    download = database.get_download(download_id)
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return download


@app.post("/api/downloads", status_code=202)
def start_download(request: DownloadRequest) -> dict:
    try:
        return downloads.queue(
            request.repo_id,
            request.revision,
            request.allow_patterns,
            request.ignore_patterns,
            request.mode,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/downloads/{download_id}/cancel")
def cancel_download(download_id: str) -> dict:
    try:
        download = downloads.cancel(download_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not download:
        raise HTTPException(status_code=404, detail="Download not found")
    return download


@app.get("/api/local-models")
def local_models(query: Annotated[str, Query(max_length=200)] = "") -> dict:
    items = database.list_local_models(query)
    return {
        "items": items,
        "count": len(items),
        "total_bytes": sum(item["size_bytes"] for item in items),
    }


@app.post("/api/local-models/scan")
async def scan_local_models() -> dict:
    return await run_in_threadpool(indexer.scan)


@app.get("/api/local-models/{repo_id:path}")
def local_model(repo_id: str) -> dict:
    try:
        validated = validate_repo_id(repo_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    result = indexer.files_for_model(validated)
    if not result:
        raise HTTPException(status_code=404, detail="Local model not found")
    return result


app_directory = Path(__file__).resolve().parent
static_directory = next(
    (
        candidate
        for candidate in (
            app_directory.parent / "static",
            app_directory.parent.parent / "frontend" / "dist",
        )
        if (candidate / "index.html").is_file()
    ),
    None,
)
if static_directory is not None:
    app.mount("/", StaticFiles(directory=static_directory, html=True), name="frontend")
