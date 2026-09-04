#!/usr/bin/env python3
"""Live GPU activity signal — probes the actual serving ports (wayfinder #114).

Replaces the journal-based gate (`launches_in()` on
`opentrader-llama-gpu1.service`), which is vacuous: the unit is disabled and
its journal is always empty, so the gate never fired.

Signal source: the llama-server that actually serves the harness, probed via
its `/slots` endpoint (same mechanism as `training/idle_trainer.py`):

- `server_busy(port)`  — True when the server has a processing slot
  (active inference), or when it is unreachable (fail-closed: an unknown
  state must not be treated as quiet).
- `server_quiet(port, seconds)` — True only when the server is reachable
  and idle for the whole window.

Also exposes `vram_free_gb()` for the VRAM preflight (GPU0 via nvidia-smi,
GPU1 via rocm-smi) so training never loads into an oversubscribed card.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from urllib.request import Request, urlopen

logger = logging.getLogger("opentrader.gpu_activity")

# Physical serving ports (what the harness actually talks to through gpu_sync).
GPU0_PORT = 5803  # qwen2.5-7b-instruct on NVIDIA RTX 3070 (research-fast tier)
GPU1_PORT = 5802  # qwythos-9b-mtp on AMD RX 7900 GRE (deep tier)

MIN_GPU1_FREE_GB = 6.0  # 4-bit QLoRA 7B base + grads needs ~5-6GB


def _slots_active(port: int, timeout: float = 3.0) -> int:
    """Return the number of processing slots on a llama-server; -1 if unknown."""
    req = Request(f"http://127.0.0.1:{port}/slots", method="GET")
    with urlopen(req, timeout=timeout) as resp:
        slots = json.loads(resp.read().decode())
    if isinstance(slots, list):
        return sum(
            1 for s in slots
            if s.get("state") == 1 or s.get("state") == "processing"
        )
    if isinstance(slots, dict):
        return len(slots.get("slots", []))
    return -1


def server_reachable(port: int, timeout: float = 3.0) -> bool:
    try:
        req = Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def server_busy(port: int, timeout: float = 3.0) -> bool:
    """True if the serving server has an active inference or is unreachable.

    Fail-closed: an unreachable server (server down, or a request in flight
    that made the server's HTTP layer respond slowly) must never be treated
    as "quiet", because a training task could then load onto a live card.
    """
    try:
        active = _slots_active(port, timeout)
    except Exception as e:
        logger.debug(f"port {port}: slots probe failed -> busy: {e}")
        return True
    if active < 0:
        return True
    return active > 0


def server_quiet(port: int, seconds: float = 10.0, poll: float = 1.0) -> bool:
    """True only if the server is reachable AND idle for the whole window."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if server_busy(port):
            return False
        time.sleep(poll)
    return not server_busy(port)


def vram_free_gb(which: str) -> float:
    """Free VRAM in GiB. which: 'gpu0' (nvidia-smi) or 'gpu1' (rocm-smi).

    Returns 0.0 if the query fails — a zero preflight fails the gate, so
    tasks never run on a card whose headroom is unknown.
    """
    if which == "gpu0":
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            return float(r.stdout.strip().splitlines()[0]) / 1024.0
        except Exception as e:
            logger.warning(f"nvidia-smi preflight failed: {e}")
            return 0.0
    # gpu1 — rocm-smi
    try:
        r = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(r.stdout)
        for card_id, card in data.items():
            if not str(card_id).startswith("card"):
                continue
            used = int(card["VRAM Total Used Memory (B)"])
            total = int(card["VRAM Total Memory (B)"])
            return (total - used) / (1024 ** 3)
    except Exception as e:
        logger.warning(f"rocm-smi preflight failed: {e}")
    return 0.0
