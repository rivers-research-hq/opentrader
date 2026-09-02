#!/usr/bin/env python3
"""LoRA adapter loader for llama-server — hot-loads trained adapters.

Two strategies:
  1. Hot-load via llama-server /lora-adapters API (if available, v2.0+)
  2. Graceful restart with --lora flag (fallback)

Loads the most recently trained adapter from the adapter registry or
from a specific path. Validates that the adapter exists and the server
is reachable before attempting.

Usage:
  # Load latest adapter from registry
  python3 scripts/load_adapter.py

  # Load specific adapter path
  python3 scripts/load_adapter.py --path models/finetune/RL-V1/adapter

  # List currently loaded adapters
  python3 scripts/load_adapter.py --list

  # Unload all adapters
  python3 scripts/load_adapter.py --unload
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("opentrader.load_adapter")

DEFAULT_HOST = "http://127.0.0.1:5802"
DEFAULT_STATE_DIR = str(PROJECT_ROOT / "data")


def _api_get(url: str, timeout: int = 10) -> Optional[dict]:
    """GET request to llama-server API."""
    try:
        req = Request(url, method="GET")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _api_post(url: str, data: dict, timeout: int = 10) -> Optional[dict]:
    """POST request to llama-server API."""
    try:
        body = json.dumps(data).encode()
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def check_hotload_supported(host: str = DEFAULT_HOST) -> bool:
    """Check if llama-server supports /lora-adapters API."""
    result = _api_get(f"{host}/lora-adapters")
    return result is not None and isinstance(result, list)


def list_adapters(host: str = DEFAULT_HOST) -> List[dict]:
    """List currently loaded LoRA adapters."""
    result = _api_get(f"{host}/lora-adapters")
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return []


def hotload_adapter(adapter_path: str, host: str = DEFAULT_HOST,
                    scale: float = 1.0) -> Optional[dict]:
    """Hot-load a LoRA adapter via /lora-adapters POST."""
    data = {
        "path": adapter_path,
        "scale": scale,
    }
    result = _api_post(f"{host}/lora-adapters", data)
    if result:
        logger.info(f"Hot-loaded adapter: {adapter_path}")
    else:
        logger.warning(f"Hot-load failed for {adapter_path}")
    return result


def unload_adapters(host: str = DEFAULT_HOST) -> bool:
    """Unload all LoRA adapters."""
    current = list_adapters(host)
    if not current:
        return True
    success = True
    for adapter in current:
        adapter_id = adapter.get("id", adapter.get("path", ""))
        if adapter_id:
            try:
                req = Request(
                    f"{host}/lora-adapters/{adapter_id}",
                    method="DELETE",
                )
                with urlopen(req, timeout=10):
                    pass
            except Exception as e:
                logger.warning(f"Failed to unload adapter {adapter_id}: {e}")
                success = False
    return success


def find_latest_adapter(state_dir: str = DEFAULT_STATE_DIR) -> Optional[str]:
    """Find the most recently trained adapter from the registry."""
    registry_path = Path(state_dir) / "adapter_registry.json"
    if not registry_path.exists():
        return None
    try:
        reg = json.loads(registry_path.read_text())
        # Find newest adapter with a valid path
        candidates = []
        for version, entry in reg.items():
            path = entry.get("path", "")
            if path and Path(path).exists():
                created = entry.get("created_at", "")
                candidates.append((created, path, version))
        if candidates:
            candidates.sort(reverse=True)
            best = candidates[0]
            logger.info(f"Latest adapter: {best[2]} at {best[1]} (created {best[0]})")
            return best[1]
    except Exception as e:
        logger.warning(f"Could not read adapter registry: {e}")
    return None


def load_adapter(adapter_path: str = None, host: str = DEFAULT_HOST,
                 state_dir: str = DEFAULT_STATE_DIR, force_restart: bool = False) -> bool:
    """Load a LoRA adapter into the llama-server.

    Tries hot-load first, then falls back to restart.
    """
    if adapter_path is None:
        adapter_path = find_latest_adapter(state_dir)
    if adapter_path is None:
        logger.error("No adapter found to load")
        return False

    path = Path(adapter_path)
    if not path.exists():
        logger.error(f"Adapter path does not exist: {adapter_path}")
        return False

    # Strategy 1: Hot-load
    if not force_restart and check_hotload_supported(host):
        result = hotload_adapter(str(path.resolve()), host)
        if result:
            return True
        logger.warning("Hot-load returned but failed; trying restart...")

    # Strategy 2: Restart with --lora
    return _restart_with_lora(str(path.resolve()), host)


def _restart_with_lora(adapter_path: str, host: str = DEFAULT_HOST) -> bool:
    """Gracefully restart llama-server with LoRA adapter.

    Finds the running llama-server process, stops it, restarts with --lora.
    This is a destructive operation — all active sessions lose their connection.
    """
    import shlex

    # Find the current process
    try:
        result = subprocess.run(
            ["pgrep", "-af", f"llama-server.*{host.split(':')[-1]}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.warning("Could not find llama-server process")
            return False

        cmdline = result.stdout.strip()
        pid_match = cmdline.split(None, 1)
        if len(pid_match) < 1:
            return False

        pid = int(pid_match[0])
        logger.info(f"Found llama-server PID {pid} on {host}")

        # Stop existing server
        os.kill(pid, signal.SIGTERM)
        time.sleep(3)

        # Check it stopped
        try:
            os.kill(pid, 0)
            logger.warning("Server didn't stop gracefully, force-killing...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(2)
        except OSError:
            pass  # Already stopped

        # Parse old command line, add --lora
        cmd_parts = shlex.split(cmdline)
        # Remove any existing --lora flags
        cmd_parts = [p for p in cmd_parts if not p.startswith("--lora")]
        # Remove the --port arg and its value (we'll re-add it)
        new_parts = []
        skip_next = False
        for i, part in enumerate(cmd_parts):
            if skip_next:
                skip_next = False
                continue
            if part == "--port" or part == "--host":
                skip_next = True
                continue
            if part.startswith("--port=") or part.startswith("--host="):
                continue
            new_parts.append(part)

        # Add LoRA
        new_parts.append(f"--lora={adapter_path}")

        # Remove the executable path (first arg) and the path arg (--model value)
        # We need to reconstruct properly
        exe = new_parts[0]
        # Find model path
        model_idx = None
        for i, p in enumerate(new_parts):
            if p == "--model" or p == "-m":
                model_idx = i
                break
        if model_idx and model_idx + 1 < len(new_parts):
            model_path = new_parts[model_idx + 1]
        else:
            logger.error("Could not find model path in command line")
            return False

        # Reconstruct command: exe -m model_path [other args] --lora ...
        # Filter out executable from args
        final_args = [exe, "-m", model_path]
        for i, p in enumerate(new_parts):
            if i == 0:  # skip exe
                continue
            if i == model_idx or i == model_idx + 1:  # skip --model and its value
                continue
            final_args.append(p)

        logger.info(f"Restarting: {' '.join(final_args[:5])} ...")

        # Start new server
        log_file = f"/tmp/llama-{host.split(':')[-1]}-lora.log"
        with open(log_file, "w") as log:
            subprocess.Popen(
                final_args,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        # Wait for it to be reachable
        for _ in range(20):
            time.sleep(2)
            if _api_get(f"{host}/health"):
                logger.info(f"Server restarted with adapter: {adapter_path}")
                return True

        logger.error("Server did not come back after restart")
        return False

    except Exception as e:
        logger.error(f"Restart failed: {e}", exc_info=True)
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="LoRA adapter loader for llama-server"
    )
    parser.add_argument("--path", help="Path to LoRA adapter directory")
    parser.add_argument("--host", default=DEFAULT_HOST, help="llama-server URL")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument("--list", action="store_true", help="List loaded adapters")
    parser.add_argument("--unload", action="store_true", help="Unload all adapters")
    parser.add_argument("--force-restart", action="store_true", help="Force server restart")
    parser.add_argument("--scale", type=float, default=1.0, help="LoRA scaling factor")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if args.list:
        adapters = list_adapters(args.host)
        if not adapters:
            print("No adapters loaded.")
            # Check if API is supported at all
            if not check_hotload_supported(args.host):
                print("(server does not support /lora-adapters API)")
        else:
            for a in adapters:
                print(json.dumps(a, indent=2))
        return

    if args.unload:
        ok = unload_adapters(args.host)
        print(f"Unloaded: {'OK' if ok else 'FAILED'}")
        return

    success = load_adapter(
        adapter_path=args.path,
        host=args.host,
        state_dir=args.state_dir,
        force_restart=args.force_restart,
    )
    print(f"Load: {'OK' if success else 'FAILED'}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
