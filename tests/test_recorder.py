import json
from pathlib import Path

import pytest

from fxexpert import recorder


def test_existing_tags_reads_append_only_history(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_text(json.dumps({"tag": "x"}) + "\n" + json.dumps({"tag": 7}) + "\n")
    assert recorder._existing_tags(history) == {"x", "7"}


def test_record_generation_rejects_duplicate_tag(tmp_path, monkeypatch):
    history = tmp_path / "history.jsonl"
    history.write_text(json.dumps({"tag": "x"}) + "\n")
    train_dir = tmp_path / "artifacts"
    train_dir.mkdir()
    (train_dir / "train_gx.json").write_text(json.dumps({"tag": "x", "hp": {}}))
    monkeypatch.setattr(recorder.gate, "evaluate", lambda *args, **kwargs: {"model": {}, "gate": {}})
    with pytest.raises(ValueError, match="already contains tag x"):
        recorder.record_generation("x", train_dir, history)


def test_jsonable_converts_numpy_scalars():
    import numpy as np

    result = recorder._jsonable({"x": np.int64(3), "ys": [np.float64(1.5)]})
    assert result == {"x": 3, "ys": [1.5]}
