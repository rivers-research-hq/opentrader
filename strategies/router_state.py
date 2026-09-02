"""Single-writer module for the harness-monitored router state (#155).

data/live_router_state.json is read by the harness every cycle (attribution,
RegimeRouter monitoring). Before #155 it had three direct writers
(seed_router.py, evolve_weights.py, lanes.py) with no locking and mixed
regime keys. As of 2026-08-29:

- THIS MODULE is the sole writer API. Callers never open() the path for
  writing; they call write_router_state(), which merges, stamps a schema
  header, and writes atomically (unique tmp name + os.replace — the same
  pattern as state/manager.py::_write_state, so concurrent harness reads
  never see a torn file).
- seed_router.py deliberately does NOT write the live file: it emits
  live_router_state_seed.json, an artifact the operator applies manually.
- Regime keys are 'up'/'down' only (harness maps bull/bear -> up/down at
  attribution; any other key is invisible to the router).

Declared in data/MANIFEST.json (runtime-state tier).
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = PROJECT / "data" / "live_router_state.json"

SCHEMA = "live_router_state/2"


def _resolve(state_dir=None) -> Path:
    if state_dir is None:
        return DEFAULT_PATH
    return Path(state_dir) / "live_router_state.json"


def read_router_state(state_dir=None) -> dict:
    """Read the router state; {} if missing or corrupt (never raises)."""
    p = _resolve(state_dir)
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Per-writer temp file + atomic replace (state/manager.py pattern)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=1)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_router_state(state: dict, state_dir=None, merge: bool = False) -> dict:
    """Write the router state. Returns the written state.

    merge=True: shallow-merge the given keys over the existing state (the
    accrual pattern — lanes adds track evidence without clobbering weights).
    merge=False: `state` IS the full document (the evolve_weights pattern,
    which has already read+reconciled).
    """
    p = _resolve(state_dir)
    out = dict(state)
    if merge:
        out = {**read_router_state(state_dir), **state}
    out["schema"] = SCHEMA
    out["updated"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(p, out)
    return out
