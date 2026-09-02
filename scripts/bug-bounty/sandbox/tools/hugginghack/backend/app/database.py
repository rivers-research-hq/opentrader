from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


DOWNLOAD_FIELDS = {
    "status",
    "total_bytes",
    "downloaded_bytes",
    "progress",
    "speed_bps",
    "error",
    "target_path",
    "metadata_json",
    "updated_at",
    "completed_at",
}


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    repo_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                    progress REAL NOT NULL DEFAULT 0,
                    speed_bps REAL NOT NULL DEFAULT 0,
                    error TEXT,
                    target_path TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_downloads_status
                    ON downloads(status, updated_at DESC);

                CREATE TABLE IF NOT EXISTS local_models (
                    repo_id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    modified_at TEXT NOT NULL,
                    downloaded_at TEXT,
                    revision TEXT,
                    sha TEXT,
                    pipeline_tag TEXT,
                    library_name TEXT,
                    license TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    source_url TEXT,
                    managed INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_local_models_modified
                    ON local_models(modified_at DESC);
                """
            )

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("payload_json", "metadata_json", "tags_json", "config_json"):
            if key in result:
                raw = result.pop(key)
                output_key = key.removesuffix("_json")
                try:
                    result[output_key] = json.loads(raw or "{}")
                except (TypeError, json.JSONDecodeError):
                    result[output_key] = {} if key != "tags_json" else []
        if "managed" in result:
            result["managed"] = bool(result["managed"])
        return result

    def create_download(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO downloads (
                    id, repo_id, revision, status, total_bytes, downloaded_bytes,
                    progress, speed_bps, error, target_path, payload_json,
                    metadata_json, created_at, updated_at, completed_at
                ) VALUES (
                    :id, :repo_id, :revision, :status, :total_bytes, :downloaded_bytes,
                    :progress, :speed_bps, :error, :target_path, :payload_json,
                    :metadata_json, :created_at, :updated_at, :completed_at
                )
                """,
                record,
            )
        return self.get_download(record["id"])

    def update_download(self, download_id: str, **changes: Any) -> dict[str, Any] | None:
        safe_changes = {key: value for key, value in changes.items() if key in DOWNLOAD_FIELDS}
        if not safe_changes:
            return self.get_download(download_id)
        assignments = ", ".join(f"{key} = :{key}" for key in safe_changes)
        safe_changes["id"] = download_id
        with self._write_lock, self.connect() as connection:
            connection.execute(f"UPDATE downloads SET {assignments} WHERE id = :id", safe_changes)
        return self.get_download(download_id)

    def get_download(self, download_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM downloads WHERE id = ?", (download_id,)).fetchone()
        return self._decode_row(row)

    def list_downloads(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def find_active_download(self, repo_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM downloads
                WHERE repo_id = ? AND status IN ('queued', 'preparing', 'downloading')
                ORDER BY created_at DESC LIMIT 1
                """,
                (repo_id,),
            ).fetchone()
        return self._decode_row(row)

    def unfinished_downloads(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM downloads WHERE status IN ('queued', 'preparing', 'downloading')"
            ).fetchall()
        return [self._decode_row(row) for row in rows]

    def upsert_local_model(self, record: dict[str, Any]) -> None:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO local_models (
                    repo_id, relative_path, size_bytes, file_count, modified_at,
                    downloaded_at, revision, sha, pipeline_tag, library_name,
                    license, tags_json, config_json, source_url, managed
                ) VALUES (
                    :repo_id, :relative_path, :size_bytes, :file_count, :modified_at,
                    :downloaded_at, :revision, :sha, :pipeline_tag, :library_name,
                    :license, :tags_json, :config_json, :source_url, :managed
                )
                ON CONFLICT(repo_id) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    size_bytes = excluded.size_bytes,
                    file_count = excluded.file_count,
                    modified_at = excluded.modified_at,
                    downloaded_at = excluded.downloaded_at,
                    revision = excluded.revision,
                    sha = excluded.sha,
                    pipeline_tag = excluded.pipeline_tag,
                    library_name = excluded.library_name,
                    license = excluded.license,
                    tags_json = excluded.tags_json,
                    config_json = excluded.config_json,
                    source_url = excluded.source_url,
                    managed = excluded.managed
                """,
                record,
            )

    def list_local_models(self, query: str = "") -> list[dict[str, Any]]:
        with self.connect() as connection:
            if query:
                rows = connection.execute(
                    """
                    SELECT * FROM local_models
                    WHERE repo_id LIKE ? OR pipeline_tag LIKE ? OR library_name LIKE ?
                    ORDER BY modified_at DESC
                    """,
                    (f"%{query}%", f"%{query}%", f"%{query}%"),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM local_models ORDER BY modified_at DESC"
                ).fetchall()
        return [self._decode_row(row) for row in rows]

    def get_local_model(self, repo_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM local_models WHERE repo_id = ?", (repo_id,)
            ).fetchone()
        return self._decode_row(row)

    def prune_local_models(self, relative_paths: set[str]) -> None:
        with self._write_lock, self.connect() as connection:
            rows = connection.execute("SELECT relative_path FROM local_models").fetchall()
            stale = [row["relative_path"] for row in rows if row["relative_path"] not in relative_paths]
            connection.executemany(
                "DELETE FROM local_models WHERE relative_path = ?",
                ((path,) for path in stale),
            )

