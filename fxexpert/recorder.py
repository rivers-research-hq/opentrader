"""Record FX expert training and gate results as durable evidence.

History rows are append-only evidence. Writes are locked and atomic at the
record level; duplicate tags are rejected so a rerun cannot silently create a
second claim for the same generation.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import gate


DEFAULT_HISTORY = Path(__file__).resolve().parent.parent / "data" / "fx_expert" / "history.jsonl"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _existing_tags(path: Path) -> set[str]:
    if not path.exists():
        return set()
    tags: set[str] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("tag") is not None:
            tags.add(str(row["tag"]))
    return tags


def record_generation(tag: str, out_dir: Path | str = gate.OUT_DIR,
                      history_path: Path | str = DEFAULT_HISTORY,
                      *, gate_result: dict[str, Any] | None = None,
                      hp: dict[str, Any] | None = None,
                      train_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate and append one generation row, refusing duplicate tags.

    The row's PF is re-derived from the prediction artifacts by
    ``gate.evaluate``; callers cannot supply a conflicting metric.
    """
    out_dir = Path(out_dir)
    history_path = Path(history_path)
    train_path = out_dir / f"train_g{tag}.json"
    if train_result is None:
        train_result = json.loads(train_path.read_text())
    if hp is None:
        hp = train_result.get("hp", {})
    if gate_result is None:
        gate_result = gate.evaluate(tag, out_dir=out_dir, write=False)

    model = gate_result.get("model", {})
    aggregate = train_result.get("aggregate", {})
    folds = train_result.get("folds", [])
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tag": str(tag),
        "hp": _jsonable(hp),
        "params": train_result.get("params"),
        "ic_mean": aggregate.get("ic_mean"),
        "fold_ics": [f.get("ic_oos") for f in folds],
        "folds_positive": aggregate.get("folds_positive"),
        "pf": model.get("pf"),
        "sharpe": model.get("sharpe"),
        "maxdd": model.get("maxdd"),
        "n_pairdays": model.get("n_pairdays"),
        "gate": gate_result.get("gate", {}).get("verdict"),
        "gate_reasons": gate_result.get("gate", {}).get("reasons", []),
        "promoted": False,
        "registered": False,
        "warm_from": train_result.get("warm_from"),
        "secs": train_result.get("secs"),
    }
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            if str(tag) in _existing_tags_from_file(f):
                raise ValueError(f"history already contains tag {tag}")
            f.seek(0, os.SEEK_END)
            f.write(json.dumps(_jsonable(row), allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return row


def _existing_tags_from_file(f) -> set[str]:
    f.seek(0)
    tags: set[str] = set()
    for line in f:
        if line.strip():
            row = json.loads(line)
            if row.get("tag") is not None:
                tags.add(str(row["tag"]))
    return tags
