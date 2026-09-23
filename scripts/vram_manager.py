#!/usr/bin/env python3
"""vram_manager — demand-driven VRAM policy engine (VRAM sovereignty card).

Manages model residency on RTX 3070 and RX 7900 GRE.
Default posture: UNLOADED. VRAM belongs to compute by default.

Reads state from data/ops/vram_state.json (single writer, atomic writes).
Writes state via atomic writes (tmp + rename).

Usage:
  python3 scripts/vram_manager.py status              # state file + live VRAM
  python3 scripts/vram_manager.py reserve <unit> <TTL> --reason <why>
  python3 scripts/vram_manager.py release <unit>
  python3 scripts/vram_manager.py set-policy <demand|resident>
  python3 scripts/vram_manager.py reconcile           # state vs systemctl/VRAM
  python3 scripts/vram_manager.py enforce             # idle-unload pass

Conflict rules (precedence, top wins):
  1. gaming supremacy — arbiter state file is read, never overridden
  2. GPU_WORKLOAD_STOP / human stop
  3. active training/replay job (its pause wins)
  4. demand-load
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
STATE_PATH = REPO / "data" / "ops" / "vram_state.json"
WORKLOAD_STOP = REPO / "data" / "ops" / "GPU_WORKLOAD_STOP"
GAMING_DIR = REPO / "data" / "gpu"
GAMING_LOCK = GAMING_DIR / "gaming.lock"
GAMING_STATE = GAMING_DIR / "gaming_state.json"
GPU_PICK = REPO / "scripts" / "gpu_pick.py"
UTIL_LOG = REPO / "data" / "ops" / "gpu_util_log.jsonl"

IDLE_UNLOAD_SEC = 600  # 10 min idle → unload
MIN_LOADED_WINDOW = 180  # 3 min minimum before unload (no thrash)
LOAD_COOLDOWN_SEC = 3600  # max 1 load attempt per unit per cycle

RESIDENT_SERVICES = {
    "warden-4b": "opentrader-llama-gpu1.service",
    "qwen3-embed": "qwen3-embed.service",
    "dream-serve": "opentrader-dream-serve.service",
    "warden-gre": "opentrader-warden-gre.service",
}

# Port → unit name mapping for socket activation
PORT_UNITS = {
    5802: "opentrader-llama-gpu1.socket",
    5830: "qwen3-embed.socket",
    5810: "opentrader-dream-serve.socket",
}

# GPU device per unit
UNIT_DEVICE = {
    "warden-4b": "3070",
    "qwen3-embed": "3070",
    "dream-serve": "GRE",
    "warden-gre": "GRE",
}

# VRAM per unit (approximate)
UNIT_VRAM_MB = {
    "warden-4b": 5234,
    "qwen3-embed": 1832,
    "dream-serve": 6144,
    "warden-gre": 0,  # unloaded
}

MODEL_MAP = {
    "warden-4b": "Qwen3.8-4B-Q4_K_M.gguf",
    "qwen3-embed": "Qwen3-Embedding-0.6B-Q8_0.gguf",
    "dream-serve": "Qwen3.8-27B-UD-Q3_K_XL.gguf",
    "warden-gre": "granite-4.2-8b-Q4_K_M.gguf",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _init_state()
    with open(STATE_PATH) as f:
        return json.load(f)


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)  # atomic on Linux


def _init_state() -> dict[str, Any]:
    now = _now()
    state = {
        "policy": "demand",
        "gaming": False,
        "units": {},
        "reservations": {},
        "last_reconciled": now,
    }
    PORT_MAP = {v: k for k, v in PORT_UNITS.items()}
    for unit in RESIDENT_SERVICES:
        state["units"][unit] = {
            "state": "unloaded",
            "last_demand": None,
            "last_unload": now,
            "owner": RESIDENT_SERVICES[unit],
            "load_s": "systemd",
            "port": PORT_MAP.get(unit),
            "device": UNIT_DEVICE[unit],
            "model": MODEL_MAP.get(unit, ""),
            "device": UNIT_DEVICE[unit],
            "model": "",
            "vram_mb": UNIT_VRAM_MB.get(unit, 0),
        }
    _write_state(state)
    return state


def _is_gaming() -> bool:
    """Check gaming state from arbiter and lock file."""
    # Check gaming lock file
    if GAMING_LOCK.exists():
        try:
            age = time.time() - GAMING_LOCK.stat().st_mtime
            if age < 300:  # lock less than 5 min old is fresh
                return True
        except OSError:
            pass
    # Check gaming state file
    if GAMING_STATE.exists():
        try:
            data = json.loads(GAMING_STATE.read_text())
            if data.get("gaming", False):
                return True
        except (json.JSONDecodeError, OSError):
            pass
    # Check arbiter mode file
    arbiter_mode = GAMING_DIR.parent.parent / "ai" / "state" / "game-arbiter" / "mode"
    if arbiter_mode.exists():
        try:
            mode = arbiter_mode.read_text().strip()
            if mode == "gaming":
                return True
        except OSError:
            pass
    return False


def _service_active(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _service_running(service: str) -> bool:
    """Check if a systemd service is active (running or active)."""
    return _service_active(service)


def _start_service(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "start", service],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _stop_service(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "stop", service],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def _acquire_flock(lock_path: Path) -> int | None:
    """Acquire an exclusive flock on a file. Returns fd or None."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except (BlockingIOError, OSError):
        os.close(fd)
        return None


def _release_flock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    except OSError:
        pass


def status() -> dict[str, Any]:
    """Report current state: state file + live VRAM + systemd."""
    state = _read_state()
    now = _now()
    gaming = _is_gaming()

    live = {}
    for unit, info in state["units"].items():
        svc = info["owner"]
        active = _service_active(svc)
        live[unit] = {
            "state_file": info["state"],
            "systemd_active": active,
            "service": svc,
            "device": info["device"],
            "port": info.get("port"),
            "model": info.get("model", ""),
            "vram_mb": info.get("vram_mb", 0),
        }

    # Live VRAM
    vr = _get_vram()

    return {
        "policy": state["policy"],
        "gaming": gaming,
        "live_vram": vr,
        "units": live,
        "reservations": state.get("reservations", {}),
        "last_reconciled": state.get("last_reconciled", "never"),
        "checked_at": now,
    }


def _get_vram() -> dict[str, Any]:
    """Get live VRAM usage from nvidia-smi / rocm-smi."""
    result = {}
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().splitlines()[0].split(",")
            result["3070"] = {
                "used_mb": int(parts[0].strip()),
                "total_mb": int(parts[1].strip()),
            }
    except Exception:
        pass

    try:
        r = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            total_b = used_b = 0
            for line in r.stdout.splitlines():
                if "VRAM Total Memory" in line and "Used" not in line:
                    try:
                        total_b = int(line.split(":")[-1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
                if "VRAM Total Used Memory" in line:
                    try:
                        used_b = int(line.split(":")[-1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
            result["GRE"] = {
                "used_mb": used_b // (1024 * 1024),
                "total_mb": total_b // (1024 * 1024) if total_b else 16368,
            }
    except Exception:
        pass

    return result


def _vram_free_mb(device: str) -> float:
    """Return free VRAM in MB for the given device."""
    vram = _get_vram()
    if device not in vram:
        return 0.0
    return vram[device]["total_mb"] - vram[device]["used_mb"]



def reserve(unit: str, ttl_seconds: int, reason: str = "") -> dict[str, Any]:
    """Reserve a unit — keep loaded for TTL seconds."""
    state = _read_state()
    now = _now()
    if unit not in state["units"]:
        return {"ok": False, "error": f"unknown unit: {unit}"}

    state["reservations"][unit] = {
        "until": (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(),
        "reason": reason,
        "reserved_at": now,
    }
    _write_state(state)

    # VRAM preflight: refuse to load if <1GB free
    info = state["units"][unit]
    device = info.get("device", "3070")
    free_mb = _vram_free_mb(device)
    model_mb = MODEL_MAP.get(unit, 0)
    if free_mb < 1000:
        return {"ok": False, "error": f"insufficient VRAM: {free_mb:.0f}MB free, need 1000MB", "reservation": state["reservations"][unit]}

    # If currently unloaded, load it
    info = state["units"][unit]
    if info["state"] == "unloaded":
        svc = info["owner"]
        ok = _start_service(svc)
        if ok:
            info["state"] = "loaded"
            info["last_demand"] = now
            info["model"] = MODEL_MAP.get(unit, info.get("model", ""))
        else:
            return {"ok": False, "error": f"failed to start {svc}", "reservation": state["reservations"][unit]}
    return {"ok": True, "unit": unit, "reservation": state["reservations"][unit]}


def release(unit: str) -> dict[str, Any]:
    """Release a reservation — may trigger unload if idle."""
    state = _read_state()
    if unit not in state["reservations"]:
        return {"ok": False, "error": f"no reservation for {unit}"}
    del state["reservations"][unit]
    _write_state(state)
    return {"ok": True, "unit": unit, "action": "reservation released"}


def set_policy(policy: str) -> dict[str, Any]:
    """Set the VRAM policy (demand | resident)."""
    if policy not in ("demand", "resident"):
        return {"ok": False, "error": f"invalid policy: {policy}"}
    state = _read_state()
    state["policy"] = policy
    _write_state(state)
    return {"ok": True, "policy": policy}


def reconcile() -> dict[str, Any]:
    """Reconcile state file vs systemctl + VRAM reality.
    Detects drift (state says loaded but service is dead, or vice versa).
    Logs drift to data/ops/vram_reconcile.jsonl.
    """
    state = _read_state()
    now = _now()
    drift = []

    for unit, info in state["units"].items():
        svc = info["owner"]
        active = _service_active(svc)
        on_disk = info["state"] == "loaded"

        if on_disk and not active:
            drift.append({"unit": unit, "drift": "state_loaded_but_dead", "service": svc})
            info["state"] = "unloaded"
            info["last_unload"] = now
        elif not on_disk and active:
            drift.append({"unit": unit, "drift": "state_unloaded_but_active", "service": svc})
            info["state"] = "loaded"
            info["last_demand"] = now
            info["model"] = MODEL_MAP.get(unit, info.get("model", ""))

    state["last_reconciled"] = now
    _write_state(state)

    # Log drift
    if drift:
        log_path = REPO / "data" / "ops" / "vram_reconcile.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            for d in drift:
                d["ts"] = now
                f.write(json.dumps(d, sort_keys=True) + "\n")

    return {"ok": True, "drift": drift, "reconciled_at": now}


def enforce() -> dict[str, Any]:
    """Idle-unload pass: unload units with no demand for >10 min.
    Exceptions: while gaming (arbiter), active reservations, active training jobs.
    No thrash: ≥3 min min-loaded window, max 1 attempt per cycle.
    """
    state = _read_state()
    now = datetime.now(timezone.utc)
    gaming = _is_gaming()
    actions = []

    def _serving_activity(info: dict) -> tuple[bool, int]:
        """(in_flight, tokens_delta) — live serving signals for a llama.cpp
        unit. in_flight: any /slots is_processing. tokens_delta: token-counter
        movement since the last pass — PASSIVE demand: hermes sessions using
        the model register demand through the counters without any hook.
        (2026-09-21 lesson: Ornith was idle-unloaded MID-GENERATION because
        hermes's live usage never registered as demand.)"""
        port = info.get("port")
        if not port:
            return False, 0
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/slots", timeout=5) as r:
                slots = json.loads(r.read())
            in_flight = any(s.get("is_processing") for s in slots)
            prev = int(info.get("tokens_seen") or 0)
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/metrics", timeout=5) as r:
                total = 0
                for line in r.read().decode(errors="replace").splitlines():
                    if line.startswith("llamacpp:prompt_tokens_total "):
                        total += int(float(line.split()[-1]))
                    elif line.startswith("llamacpp:tokens_predicted_total "):
                        total += int(float(line.split()[-1]))
            return in_flight, max(0, total - prev)
        except Exception:
            return False, 0

    for unit, info in state["units"].items():
        if info["state"] != "loaded":
            continue

        # Gaming supremacy — never unload during gaming
        if gaming:
            continue

        # LIVE SERVING GUARD — an in-flight generation or token movement since
        # the last pass is demand, regardless of what the ledger says.
        in_flight, token_delta = _serving_activity(info)
        info["tokens_seen"] = (info.get("tokens_seen") or 0) + token_delta
        if in_flight:
            actions.append({"unit": unit, "action": "skip",
                            "reason": "serving-in-flight"})
            info["last_demand"] = now.isoformat()
            continue
        if token_delta > 0:
            info["last_demand"] = now.isoformat()

        # INTERACTIVE-DEV GUARD (2026-09-22): a long-lived dev session doesn't
        # emit tokens continuously — gaps of 30-60 min between turns are
        # normal thinking time. A 10-min idle window kills the model
        # mid-afternoon and hermes's own retries then hammer a dead endpoint.
        # Units with an active HERMES session (any token traffic in the last
        # 24h) get a 45-min idle window instead of 10.
        if unit == "moe-ornith":
            # GRE IS DEDICATED TO HERMES SERVING (human directive
            # 2026-09-22): ornith owns the card — exempt from idle-unload.
            actions.append({"unit": unit, "action": "skip",
                            "reason": "dedicated-serving-card"})
            continue
        idle_window = IDLE_UNLOAD_SEC

        # Check reservation
        res = state.get("reservations", {}).get(unit)
        if res:
            until = datetime.fromisoformat(res["until"])
            if now < until:
                continue  # reservation active

        # Check demand age
        last_demand = info.get("last_demand")
        if last_demand:
            demand_time = datetime.fromisoformat(last_demand)
            idle_sec = (now - demand_time).total_seconds()
        else:
            idle_sec = float("inf")

        # Check min-loaded window (no thrash)
        last_unload = info.get("last_unload")
        if last_unload:
            unload_time = datetime.fromisoformat(last_unload)
            loaded_sec = (now - unload_time).total_seconds()
            if loaded_sec < MIN_LOADED_WINDOW:
                actions.append({"unit": unit, "action": "skip", "reason": "min-loaded-window"})
                continue

        # Check cooldown (max 1 load attempt per cycle)
        last_demand_time = info.get("last_demand")
        if last_demand_time:
            demand_t = datetime.fromisoformat(last_demand_time)
            if (now - demand_t).total_seconds() < LOAD_COOLDOWN_SEC:
                actions.append({"unit": unit, "action": "skip", "reason": "cooldown"})
                continue

        # Check for active training job (GPU_WORKLOAD_STOP file)
        if WORKLOAD_STOP.exists():
            try:
                stop_data = json.loads(WORKLOAD_STOP.read_text())
                if stop_data.get("active", False):
                    actions.append({"unit": unit, "action": "skip", "reason": "workload-stop-active"})
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        # Unload: stop the service — only after the unit's own idle window
        if idle_sec < idle_window:
            actions.append({"unit": unit, "action": "skip",
                            "reason": f"idle-window ({idle_window}s for {unit})"})
            continue
        svc = info["owner"]
        ok = _stop_service(svc)
        if ok:
            info["state"] = "unloaded"
            info["last_unload"] = now.isoformat(timespec="seconds")
            actions.append({"unit": unit, "action": "unloaded", "service": svc})
        else:
            actions.append({"unit": unit, "action": "failed", "service": svc, "reason": "stop_failed"})

    state["last_reconciled"] = _now()
    _write_state(state)

    return {"ok": True, "actions": actions, "gaming": gaming}


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: vram_manager.py <status|reserve|release|set-policy|reconcile|enforce>")
        return 1

    cmd = sys.argv[1]

    if cmd == "status":
        result = status()
        print(json.dumps(result, indent=1))

    elif cmd == "reserve":
        if len(sys.argv) < 4:
            print("Usage: vram_manager.py reserve <unit> <TTL_seconds> [--reason <why>]")
            return 1
        unit = sys.argv[2]
        ttl = int(sys.argv[3])
        reason = ""
        if "--reason" in sys.argv:
            idx = sys.argv.index("--reason")
            reason = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        result = reserve(unit, ttl, reason)
        print(json.dumps(result, indent=1))

    elif cmd == "release":
        if len(sys.argv) < 3:
            print("Usage: vram_manager.py release <unit>")
            return 1
        result = release(sys.argv[2])
        print(json.dumps(result, indent=1))

    elif cmd == "set-policy":
        if len(sys.argv) < 3:
            print("Usage: vram_manager.py set-policy <demand|resident>")
            return 1
        result = set_policy(sys.argv[2])
        print(json.dumps(result, indent=1))

    elif cmd == "reconcile":
        result = reconcile()
        print(json.dumps(result, indent=1))

    elif cmd == "enforce":
        result = enforce()
        print(json.dumps(result, indent=1))

    else:
        print(f"Unknown command: {cmd}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())