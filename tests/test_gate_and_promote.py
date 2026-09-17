import importlib.util
import json
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "gate_and_promote", Path(__file__).parents[1] / "scripts" / "gate_and_promote.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_evaluate_candidate_writes_pending_wrc_report(tmp_path, monkeypatch):
    out_dir = tmp_path / "artifacts"
    out_dir.mkdir()
    (out_dir / "train_gx.json").write_text(json.dumps({"tag": "x", "hp": {}}))
    gate_result = {"model": {"pf": 1.1}, "gate": {"verdict": "ELIGIBLE", "reasons": []}}
    monkeypatch.setattr(MODULE.gate, "evaluate", lambda *args, **kwargs: gate_result)
    report = MODULE.evaluate_candidate("x", out_dir, tmp_path / "history.jsonl", tmp_path / "reports")
    assert report["recommendation"] == "SHADOW_ELIGIBLE"
    assert report["wrc"]["status"] == "PENDING_POPULATION"
    assert (tmp_path / "reports" / "gate_and_promote_x.json").exists()
