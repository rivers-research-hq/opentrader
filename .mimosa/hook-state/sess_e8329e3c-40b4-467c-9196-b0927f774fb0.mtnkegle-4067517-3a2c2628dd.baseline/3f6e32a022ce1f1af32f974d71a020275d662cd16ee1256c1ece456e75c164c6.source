import json
from pathlib import Path

import pytest

from app.config import Settings, repository_path, validate_repo_id
from app.database import Database
from app.downloads import DownloadManager
from app.indexer import LocalModelIndexer


def test_repo_id_validation_rejects_path_traversal():
    assert validate_repo_id("google/gemma-2b") == "google/gemma-2b"
    for value in ("../etc", "owner/../../secret", "single-name", "/absolute/model", "owner/model/extra"):
        with pytest.raises(ValueError):
            validate_repo_id(value)


def test_indexer_discovers_manually_copied_model(tmp_path: Path):
    storage = tmp_path / "models"
    data = tmp_path / "data"
    model = storage / "acme" / "tiny-model"
    model.mkdir(parents=True)
    (model / "config.json").write_text(
        json.dumps({"model_type": "llama", "architectures": ["LlamaForCausalLM"]}),
        encoding="utf-8",
    )
    (model / "model.safetensors").write_bytes(b"safe-weights")

    settings = Settings(model_storage=storage.resolve(), data_dir=data.resolve())
    database = Database(settings.database_path)
    database.initialize()
    indexer = LocalModelIndexer(settings, database)

    result = indexer.scan()

    assert result["count"] == 1
    indexed = database.get_local_model("acme/tiny-model")
    assert indexed is not None
    assert indexed["relative_path"] == "acme/tiny-model"
    assert indexed["config"]["model_type"] == "llama"
    assert indexed["managed"] is False


def test_indexer_marks_pickle_compatible_files(tmp_path: Path):
    storage = tmp_path / "models"
    data = tmp_path / "data"
    model = storage / "unsafe" / "legacy"
    model.mkdir(parents=True)
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "pytorch_model.bin").write_bytes(b"not-executed")

    settings = Settings(model_storage=storage.resolve(), data_dir=data.resolve())
    database = Database(settings.database_path)
    database.initialize()
    indexer = LocalModelIndexer(settings, database)
    indexer.scan()

    details = indexer.files_for_model("unsafe/legacy")
    assert details is not None
    assert details["unsafe_file_count"] == 1
    assert details["files"][0]["unsafe_serialization"] is True


def test_cancelled_download_keeps_partial_files_and_resume_metadata(tmp_path: Path):
    storage = tmp_path / "models"
    data = tmp_path / "data"
    target = storage / "acme" / "large-model"
    target.mkdir(parents=True)
    (target / "weights.safetensors.incomplete").write_bytes(b"partial-data")

    settings = Settings(model_storage=storage.resolve(), data_dir=data.resolve())
    database = Database(settings.database_path)
    database.initialize()
    created = "2026-07-23T12:00:00+00:00"
    database.create_download(
        {
            "id": "cancel-me",
            "repo_id": "acme/large-model",
            "revision": "main",
            "status": "downloading",
            "total_bytes": 100,
            "downloaded_bytes": 0,
            "progress": 0,
            "speed_bps": 0,
            "error": None,
            "target_path": str(target),
            "payload_json": json.dumps({"mode": "full"}),
            "metadata_json": "{}",
            "created_at": created,
            "updated_at": created,
            "completed_at": None,
        }
    )
    manager = DownloadManager(settings, database, object(), object())

    class RunningProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    process = RunningProcess()
    manager._processes["cancel-me"] = process  # type: ignore[assignment]

    cancelled = manager.cancel("cancel-me")
    manager.shutdown()

    assert cancelled is not None
    assert process.terminated is True
    assert cancelled["status"] == "cancelled"
    assert cancelled["downloaded_bytes"] >= len(b"partial-data")
    assert (target / "weights.safetensors.incomplete").is_file()
    manifest = json.loads((target / ".hugginghack.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "cancelled"
