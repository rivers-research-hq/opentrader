#!/usr/bin/env python3
"""PyTorch ROCm Environment Guardian — ensures AMD GPUs get HIP-accelerated torch.

CUDA→ROCm shim: on import, detects whether PyTorch was compiled for CUDA
instead of ROCm, and auto-reinstalls the correct ROCm wheels. Prevents
the recurring problem where any `pip install` of a package depending on
torch pulls in the +cu128 PyPI build instead of the +rocm7.2 build.

Idempotent: fixes only once per boot. Uses a lock file for concurrent safety.

Usage as module (import before training):
    from training.torch_guard import ensure_rocm
    ensure_rocm()  # no-op if already fixed, reimports torch if newly fixed

Usage as MCP server:
    python -m training.torch_guard mcp  # exposes tools via stdin/stdout JSON-RPC

Usage as CLI:
    python -m training.torch_guard check   # report status only
    python -m training.torch_guard fix     # attempt repair
    python -m training.torch_guard status  # print JSON status
"""
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("torch_guard")

FIX_LOCK = Path("/tmp/torch_guard_fix.lock")
FIX_APPLIED = Path("/tmp/torch_guard_fix_applied")
FIX_RETRY_MAX = 3
ROCM_INDEX_URL = "https://download.pytorch.org/whl/rocm7.2"
REQUIRED_PACKAGES = ["torch", "torchvision", "torchaudio"]


def _detect_amd_gpu() -> bool:
    """Check if an AMD ROCm-capable GPU is present."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True, text=True, timeout=10,
        )
        return "GPU[" in result.stdout and "VRAM" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    for path in ["/dev/kfd", "/dev/dri/renderD128"]:
        if os.path.exists(path):
            return True
    return False


def _check_torch_rocm() -> dict:
    """Check current PyTorch ROCm/HIP status without importing torch."""
    result = {
        "torch_version": None,
        "build": None,
        "hip_available": False,
        "cuda_available": False,
        "gpu_detected": _detect_amd_gpu(),
        "needs_fix": False,
    }
    try:
        import torch
        result["torch_version"] = torch.__version__
        if hasattr(torch.version, "hip") and torch.version.hip:
            result["build"] = "rocm"
            result["hip_available"] = torch.cuda.is_available()
        elif hasattr(torch.version, "cuda") and torch.version.cuda:
            result["build"] = "cuda"
            result["cuda_available"] = torch.cuda.is_available()
        else:
            result["build"] = "cpu"

        if result["gpu_detected"] and not result["hip_available"]:
            result["needs_fix"] = True
    except ImportError:
        result["build"] = "not_installed"
        if result["gpu_detected"]:
            result["needs_fix"] = True
    except Exception as e:
        result["error"] = str(e)

    return result


def _apply_fix() -> bool:
    """Install ROCm PyTorch wheels. Returns True on success."""
    if FIX_LOCK.exists():
        # Wait for another process to finish
        for _ in range(30):
            time.sleep(2)
            if not FIX_LOCK.exists():
                break
        if FIX_LOCK.exists():
            logger.error("Torch guard fix lock held too long — aborting")
            return False

    FIX_LOCK.touch()
    try:
        # Use disk-backed temp dir (tmpfs is too small for 6 GB torch wheel)
        disk_tmp = Path("/home/mrc/.cache/torch_guard_tmp")
        disk_tmp.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "TMPDIR": str(disk_tmp), "TMP": str(disk_tmp)}

        logger.info("Installing ROCm PyTorch from %s (tmp=%s)", ROCM_INDEX_URL, disk_tmp)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"]
            + REQUIRED_PACKAGES
            + ["--index-url", ROCM_INDEX_URL, "--upgrade", "--force-reinstall",
               "--resume-retries", "5"],
            capture_output=True, text=True, timeout=1800, env=env,
        )
        if result.returncode != 0:
            logger.error("ROCm PyTorch install failed: %s", result.stderr[-500:])
            return False

        FIX_APPLIED.touch()
        logger.info("ROCm PyTorch installed successfully")
        return True
    finally:
        FIX_LOCK.unlink(missing_ok=True)


def ensure_rocm(max_retries: int = FIX_RETRY_MAX) -> bool:
    """Ensure PyTorch has ROCm/HIP support. Auto-fixes if needed.

    Returns True if ROCm is available (was already or newly fixed).
    Idempotent — only fixes once per boot session.
    """
    status = _check_torch_rocm()

    if not status["needs_fix"]:
        if status["hip_available"]:
            logger.debug("PyTorch ROCm already active: %s", status["torch_version"])
        elif not status["gpu_detected"]:
            logger.debug("No AMD GPU detected — skipping ROCm fix")
        else:
            logger.debug("PyTorch OK: %s (build=%s)", status["torch_version"], status["build"])
        return status["hip_available"] or not status["gpu_detected"]

    if FIX_APPLIED.exists():
        logger.info("ROCm fix already applied this boot — checking result")
        status2 = _check_torch_rocm()
        return status2["hip_available"]

    logger.warning(
        "AMD GPU detected but PyTorch %s (build=%s) has no HIP support. "
        "Auto-fixing...",
        status["torch_version"] or "?", status["build"],
    )

    for attempt in range(1, max_retries + 1):
        if _apply_fix():
            # Verify fix by re-importing
            status = _check_torch_rocm()
            if status["hip_available"]:
                logger.info("ROCm fix verified: torch %s, HIP available", status["torch_version"])
                return True
            else:
                logger.warning("Fix applied but verification failed (attempt %d/%d)", attempt, max_retries)

    logger.error("Failed to fix PyTorch ROCm after %d attempts", max_retries)
    return False


# ── MCP Server Mode ──────────────────────────────────────────

def _mcp_handle(method: str, params: dict = None) -> dict:
    """Handle a single MCP JSON-RPC request."""
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "torch_guard_check",
                    "description": "Check if PyTorch has ROCm/HIP support for AMD GPU",
                },
                {
                    "name": "torch_guard_fix",
                    "description": "Fix PyTorch by reinstalling ROCm wheels. Idempotent.",
                },
                {
                    "name": "torch_guard_status",
                    "description": "Return full environment status as JSON",
                },
            ]
        }
    elif method == "tools/call":
        tool = params.get("name", "")
        if tool == "torch_guard_check":
            return {"content": [{"type": "text", "text": json.dumps(_check_torch_rocm())}]}
        elif tool == "torch_guard_fix":
            ok = ensure_rocm()
            return {"content": [{"type": "text", "text": json.dumps({
                "fixed": ok, "status": _check_torch_rocm(),
            })}]}
        elif tool == "torch_guard_status":
            return {"content": [{"type": "text", "text": json.dumps(_check_torch_rocm())}]}
        else:
            return {"error": f"Unknown tool: {tool}"}
    else:
        return {"error": f"Unknown method: {method}"}


def _mcp_serve():
    """Run as MCP server via stdin/stdout JSON-RPC."""
    import select
    logger.info("torch_guard MCP server starting")
    buffer = ""
    while True:
        if select.select([sys.stdin], [], [], 1.0)[0]:
            chunk = sys.stdin.read(4096)
            if not chunk:
                break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                    response = _mcp_handle(
                        request.get("method", ""),
                        request.get("params", {}),
                    )
                    response["jsonrpc"] = "2.0"
                    response["id"] = request.get("id")
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    err = {"jsonrpc": "2.0", "error": str(e), "id": None}
                    sys.stdout.write(json.dumps(err) + "\n")
                    sys.stdout.flush()


# ── CLI ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PyTorch ROCm Environment Guardian")
    parser.add_argument("action", nargs="?", default="check",
                        choices=["check", "fix", "status", "mcp"])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [torch_guard] %(levelname)s %(message)s")

    if args.action == "mcp":
        _mcp_serve()
    elif args.action == "status":
        print(json.dumps(_check_torch_rocm(), indent=2))
    elif args.action == "check":
        status = _check_torch_rocm()
        if status["needs_fix"]:
            print("FIX NEEDED: AMD GPU detected but no HIP support")
            print(json.dumps(status, indent=2))
            sys.exit(1)
        else:
            print("OK: PyTorch %s (build=%s, HIP=%s)" % (
                status["torch_version"], status["build"], status["hip_available"]))
    elif args.action == "fix":
        ok = ensure_rocm()
        if ok:
            print("FIXED: PyTorch ROCm is now available")
        else:
            print("FAILED: Could not fix PyTorch ROCm")
            sys.exit(1)


if __name__ == "__main__":
    main()
