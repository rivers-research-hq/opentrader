from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings, repository_path, validate_repo_id
from .database import Database
from .hub_service import HubService
from .indexer import LocalModelIndexer, directory_stats


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadCancelled(Exception):
    pass


class DownloadManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        hub: HubService,
        indexer: LocalModelIndexer,
    ):
        self.settings = settings
        self.database = database
        self.hub = hub
        self.indexer = indexer
        self.executor = ThreadPoolExecutor(
            max_workers=settings.max_concurrent_downloads,
            thread_name_prefix="hugginghack-download",
        )
        self._submitted: set[str] = set()
        self._cancel_events: dict[str, threading.Event] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()

    def queue(
        self,
        repo_id: str,
        revision: str = "main",
        allow_patterns: list[str] | None = None,
        ignore_patterns: list[str] | None = None,
        mode: str = "full",
    ) -> dict[str, Any]:
        validated = validate_repo_id(repo_id)
        active = self.database.find_active_download(validated)
        if active:
            return active
        target = repository_path(validated)
        created = now_iso()
        payload = {
            "allow_patterns": [value for value in (allow_patterns or []) if value.strip()],
            "ignore_patterns": [value for value in (ignore_patterns or []) if value.strip()],
            "mode": mode,
        }
        record = {
            "id": uuid.uuid4().hex,
            "repo_id": validated,
            "revision": revision.strip() or "main",
            "status": "queued",
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "progress": 0,
            "speed_bps": 0,
            "error": None,
            "target_path": str(target),
            "payload_json": json.dumps(payload),
            "metadata_json": "{}",
            "created_at": created,
            "updated_at": created,
            "completed_at": None,
        }
        download = self.database.create_download(record)
        self._submit(download["id"])
        return download

    def _submit(self, download_id: str) -> None:
        with self._lock:
            if download_id in self._submitted:
                return
            self._submitted.add(download_id)
            self._cancel_events[download_id] = threading.Event()
        self.executor.submit(self._run, download_id)

    def cancel(self, download_id: str) -> dict[str, Any] | None:
        download = self.database.get_download(download_id)
        if not download:
            return None
        if download["status"] not in {"queued", "preparing", "downloading"}:
            raise ValueError(f"Download is already {download['status']}.")

        cancelled_at = now_iso()
        with self._lock:
            cancel_event = self._cancel_events.setdefault(download_id, threading.Event())
            cancel_event.set()
            process = self._processes.get(download_id)
            if process and process.poll() is None:
                process.terminate()

        target = Path(download["target_path"]) if download.get("target_path") else None
        if target and target.is_dir():
            partial_bytes, _, _ = directory_stats(target)
            manifest_path = target / ".hugginghack.json"
            try:
                manifest_path.write_text(
                    json.dumps(
                        {
                            "status": "cancelled",
                            "repo_id": download["repo_id"],
                            "revision": download["revision"],
                            "cancelled_at": cancelled_at,
                            "partial_bytes": partial_bytes,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
        else:
            partial_bytes = int(download.get("downloaded_bytes") or 0)

        return self.database.update_download(
            download_id,
            status="cancelled",
            downloaded_bytes=partial_bytes,
            speed_bps=0,
            error=None,
            updated_at=cancelled_at,
            completed_at=cancelled_at,
        )

    def resume_unfinished(self) -> None:
        for download in self.database.unfinished_downloads():
            self.database.update_download(
                download["id"],
                status="queued",
                error=None,
                updated_at=now_iso(),
            )
            self._submit(download["id"])

    def _monitor(
        self,
        download_id: str,
        target: Path,
        total_bytes: int,
        stop: threading.Event,
        cancel_event: threading.Event,
    ) -> None:
        last_bytes = 0
        last_time = time.monotonic()
        speed = 0.0
        while not stop.wait(1.25):
            if cancel_event.is_set():
                return
            current, _, _ = directory_stats(target, include_cache=True)
            current_time = time.monotonic()
            elapsed = max(current_time - last_time, 0.001)
            instant_speed = max(0, current - last_bytes) / elapsed
            speed = instant_speed if speed == 0 else speed * 0.6 + instant_speed * 0.4
            progress = min(99.5, current * 100 / total_bytes) if total_bytes else 0
            self.database.update_download(
                download_id,
                status="downloading",
                downloaded_bytes=current,
                progress=round(progress, 2),
                speed_bps=round(speed, 2),
                updated_at=now_iso(),
            )
            last_bytes = current
            last_time = current_time

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise DownloadCancelled()

    def _download_snapshot(
        self,
        download_id: str,
        download: dict[str, Any],
        target: Path,
        cancel_event: threading.Event,
    ) -> None:
        payload = download.get("payload") or {}
        command = [
            sys.executable,
            "-m",
            "app.download_worker",
            "--repo-id",
            download["repo_id"],
            "--revision",
            download["revision"],
            "--target",
            str(target),
            "--endpoint",
            self.settings.hf_endpoint,
            "--allow-patterns",
            json.dumps(payload.get("allow_patterns") or []),
            "--ignore-patterns",
            json.dumps(payload.get("ignore_patterns") or []),
            "--workers",
            str(self.settings.download_workers_per_job),
        ]
        environment = os.environ.copy()
        environment["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        if self.settings.hf_token:
            environment["HF_TOKEN"] = self.settings.hf_token

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as error_output:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=error_output,
                text=True,
                env=environment,
            )
            with self._lock:
                self._processes[download_id] = process
            try:
                while process.poll() is None:
                    if cancel_event.wait(0.25):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        raise DownloadCancelled()
                if process.returncode != 0:
                    error_output.seek(0)
                    message = error_output.read().strip()
                    raise RuntimeError(message or f"Download worker exited with code {process.returncode}.")
            finally:
                with self._lock:
                    self._processes.pop(download_id, None)

    def _run(self, download_id: str) -> None:
        with self._lock:
            cancel_event = self._cancel_events.setdefault(download_id, threading.Event())
        try:
            download = self.database.get_download(download_id)
            if not download:
                return
            self._raise_if_cancelled(cancel_event)
            repo_id = validate_repo_id(download["repo_id"])
            target = repository_path(repo_id)
            target.mkdir(parents=True, exist_ok=True)
            self.database.update_download(
                download_id,
                status="preparing",
                error=None,
                updated_at=now_iso(),
            )
            self._raise_if_cancelled(cancel_event)
            details = self.hub.model_details(repo_id, download["revision"])
            self._raise_if_cancelled(cancel_event)
            total_bytes = int(details.get("total_bytes") or 0)
            self.database.update_download(
                download_id,
                total_bytes=total_bytes,
                metadata_json=json.dumps(
                    {
                        "pipeline_tag": details.get("pipeline_tag"),
                        "library_name": details.get("library_name"),
                        "license": details.get("license"),
                        "file_count": len(details.get("files") or []),
                        "gated": details.get("gated"),
                    }
                ),
                updated_at=now_iso(),
            )
            manifest_path = target / ".hugginghack.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "status": "downloading",
                        "repo_id": repo_id,
                        "revision": download["revision"],
                        "source_url": details.get("source_url"),
                        "started_at": download["created_at"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            stop = threading.Event()
            monitor = threading.Thread(
                target=self._monitor,
                args=(download_id, target, total_bytes, stop, cancel_event),
                name=f"hugginghack-progress-{download_id[:8]}",
                daemon=True,
            )
            monitor.start()
            try:
                self._download_snapshot(download_id, download, target, cancel_event)
            finally:
                stop.set()
                monitor.join(timeout=3)
            self._raise_if_cancelled(cancel_event)
            final_size, file_count, _ = directory_stats(target)
            completed_at = now_iso()
            manifest_path.write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "repo_id": repo_id,
                        "revision": download["revision"],
                        "sha": details.get("sha"),
                        "downloaded_at": completed_at,
                        "source_url": details.get("source_url"),
                        "pipeline_tag": details.get("pipeline_tag"),
                        "library_name": details.get("library_name"),
                        "license": details.get("license"),
                        "tags": details.get("tags") or [],
                        "gated": details.get("gated"),
                        "total_bytes": final_size,
                        "file_count": file_count,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            final_size, _, _ = directory_stats(target)
            self.indexer.index_path(target)
            self.database.update_download(
                download_id,
                status="complete",
                total_bytes=total_bytes or final_size,
                downloaded_bytes=final_size,
                progress=100,
                speed_bps=0,
                error=None,
                updated_at=completed_at,
                completed_at=completed_at,
            )
        except DownloadCancelled:
            current = self.database.get_download(download_id)
            if current and current["status"] != "cancelled":
                cancelled_at = now_iso()
                target = Path(current["target_path"]) if current.get("target_path") else None
                partial_bytes = directory_stats(target)[0] if target and target.is_dir() else 0
                self.database.update_download(
                    download_id,
                    status="cancelled",
                    downloaded_bytes=partial_bytes,
                    speed_bps=0,
                    error=None,
                    updated_at=cancelled_at,
                    completed_at=cancelled_at,
                )
        except Exception as error:
            current = self.database.get_download(download_id)
            if current and current["status"] == "cancelled":
                return
            message = str(error).strip() or error.__class__.__name__
            if "gated" in message.lower() or "401" in message or "403" in message:
                message = (
                    f"{message} Accept the model terms on Hugging Face and configure "
                    "a read-only HF_TOKEN in .env."
                )
            self.database.update_download(
                download_id,
                status="failed",
                speed_bps=0,
                error=message[:2000],
                updated_at=now_iso(),
                completed_at=now_iso(),
            )
        finally:
            with self._lock:
                self._submitted.discard(download_id)
                self._cancel_events.pop(download_id, None)
                self._processes.pop(download_id, None)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=False)
