#!/usr/bin/env python3
"""Tests for the #255 history-reproducibility guard.

The g124-g136 window proved a gate-code change can silently invalidate
history.jsonl rows mid-search: ten recorded PFs stopped reproducing from
their own stored preds. The loop now re-derives the model PF from the written
preds (fxexpert.gate.rescore) and refuses to record a row that does not
match. These tests pin that guard.

Run as a script:  .venv/bin/python3 tests/test_history_reproducibility.py
Run under pytest: .venv/bin/python3 -m pytest tests/test_history_reproducibility.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402

OUT = REPO / "data" / "fx_expert"

# The ten stale tags from data/fx_expert/history_stale_scope.json (issue #255).
STALE_TAGS = ("124", "125", "128", "130", "131", "132", "133", "134", "135", "136")


def test_rescore_matches_recorded_pf_on_reproducible_generations():
    """For generations outside the stale window, rescore (disk artifacts ->
    positions -> daily series -> PF) must equal the recorded gate PF exactly."""
    for tag in ("139", "140", "151", "185"):
        if not (OUT / f"preds_g{tag}.npz").exists():
            continue
        recorded = json.loads((OUT / f"gate_g{tag}.json").read_text())["model"]["pf"]
        assert fxgate.rescore(tag) == recorded, tag


def test_rescore_is_current_code_on_the_stale_window():
    """On the ten stale tags the recorded PFs are wrong, but rescore and a
    read-only evaluate re-run must agree exactly — both are current code on
    the same artifacts. (The stale recorded values live in the sidecar, not
    here: re-stamping them must not break this test.)"""
    for tag in STALE_TAGS:
        if not (OUT / f"preds_g{tag}.npz").exists():
            continue
        assert fxgate.rescore(tag) == fxgate.evaluate(tag, write=False)["model"]["pf"], tag


def test_write_false_still_leaves_gate_files_untouched():
    p = OUT / "gate_g124.json"
    if not p.exists():
        return
    before = p.read_bytes()
    fxgate.evaluate("124", write=False)
    assert p.read_bytes() == before


def _run_one_generation(tmp_path, monkeypatch, rescored_pf):
    """Drive loop.main for one generation with training/gate mocked and
    HISTORY/STATE redirected to tmp_path. Returns (history_rows, state)."""
    from fxexpert import data as fxdata
    from fxexpert import loop, train as fxtrain

    monkeypatch.setattr(fxdata, "build", lambda: None)
    monkeypatch.setattr(fxtrain, "load_panel", lambda: None)
    monkeypatch.setattr(fxtrain, "run_generation",
                        lambda tag, hp, warm_tag=None, seed=0, panel=None:
                        {"aggregate": {"ic_mean": 0.01, "folds_positive": 2},
                         "folds": [{"ic_oos": 0.01}, {"ic_oos": 0.02},
                                   {"ic_oos": 0.005}],
                         "params": dict(hp), "warm_from": None})
    model = {"pf": 1.2345, "sharpe": 0.5, "maxdd": -0.1, "n_pairdays": 5000}
    monkeypatch.setattr(fxgate, "evaluate",
                        lambda tag, out_dir=None, write=True:
                        {"model": model, "model_alt_rule": model,
                         "gate": {"verdict": "ELIGIBLE", "reasons": []}})
    monkeypatch.setattr(fxgate, "rescore", lambda tag, out_dir=None: rescored_pf)

    hist, state = tmp_path / "history.jsonl", tmp_path / "loop_state.json"
    monkeypatch.setattr(loop, "HISTORY", hist)
    monkeypatch.setattr(loop, "STATE", state)
    loop.main(generations=1, do_register=False)
    rows = [json.loads(l) for l in hist.read_text().splitlines() if l.strip()]
    return rows, json.loads(state.read_text())


def test_loop_refuses_row_that_does_not_reproduce(tmp_path, monkeypatch):
    rows, state = _run_one_generation(tmp_path, monkeypatch, rescored_pf=2.0)
    assert len(rows) == 1
    r = rows[0]
    assert "row refused" in r["error"]
    assert r["pf"] == 1.2345 and r["rescored_pf"] == 2.0
    # nothing downstream consumed the unverifiable score
    assert state["bandit"] == {}
    assert state["best"] is None
    assert state["experts_registered"] == []
    assert state["generation"] == 1  # the run advances, loudly


def test_loop_records_row_that_reproduces(tmp_path, monkeypatch):
    rows, state = _run_one_generation(tmp_path, monkeypatch, rescored_pf=1.2345)
    assert len(rows) == 1
    r = rows[0]
    assert "error" not in r
    assert r["pf"] == 1.2345 and r["gate"] == "ELIGIBLE"
    assert state["bandit"] and state["generation"] == 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            if name.startswith("test_loop_"):
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    class _MP:
                        def __init__(self):
                            self._undo = []
                        def setattr(self, obj, k, v):
                            self._undo.append((obj, k, getattr(obj, k)))
                            setattr(obj, k, v)
                        def undo(self):
                            for obj, k, v in reversed(self._undo):
                                setattr(obj, k, v)
                    mp = _MP()
                    try:
                        fn(Path(td), mp)
                    finally:
                        mp.undo()
            else:
                fn()
            print(f"ok  {name}")
    print("all history-reproducibility tests passed")
