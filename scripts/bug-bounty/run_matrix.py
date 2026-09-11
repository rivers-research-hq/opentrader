#!/usr/bin/env python3
"""Run the Qwen3.8 bug-finding benchmark across (ctx_size x n_gpu_layers x
reasoning_budget) combos.

For each combo:
  1. Back up the live qwen38-agentic.service, patch it with the combo's flags.
  2. Restart the service, wait for /health.
  3. Re-seed a fresh bug-bounty sandbox (every run sees the same bugs).
  4. Run the bug-hunt agent via `opencode run`, streaming the transcript.
  5. Early-exit the moment all ground-truth bugs are detected; otherwise run to
     timeout and score partial findings.
  6. Restore the live service on exit.

Usage:
  python3 scripts/bug-bounty/run_matrix.py [--ctx 32768] [--layers 75,99]
                                          [--budget 1024,2048] [--timeout 3600]
                                          [--workers 1]

Outputs to data/benchmark-q38/bug-bounty/<combo>/.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/home/mrc/opentrader")
HERE = Path(__file__).resolve().parent
SEED = HERE / "seed.py"
SERVICE = Path(os.path.expanduser("~/.config/systemd/user/qwen38-agentic.service"))
OUT_ROOT = REPO / "data" / "benchmark-q38" / "bug-bounty"
OPENCODE = "/home/mrc/.opencode/bin/opencode"
# Sandbox lives OUTSIDE the repo so the agent cannot read the seed definitions
# in scripts/bug-bounty/bugs/. The manifest (ground truth) lives in a separate
# directory the agent is never pointed at.
SANDBOX = Path("/tmp/opencode/bb-sandbox")
MANIFEST = Path("/tmp/opencode/bb-meta/manifest.json")

import scoring  # noqa: E402  (shared detection; HERE on sys.path)
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

SERVICE_BAK = None  # set in main()


def backup_service() -> None:
    global SERVICE_BAK
    SERVICE_BAK = SERVICE.read_text()


def restore_service() -> None:
    if SERVICE_BAK is None:
        return
    SERVICE.write_text(SERVICE_BAK)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "qwen38-agentic.service"],
                   check=False)


def patch_service(ctx: int, layers: int, budget: int) -> None:
    """Rewrite the unit file to the given ctx/layers/budget, keeping the real
    KV-in-RAM blocker (--no-kv-offload)."""
    src = SERVICE.read_text()
    src = re.sub(r"--ctx-size \d+", f"--ctx-size {ctx}", src)
    src = re.sub(r"--n-gpu-layers \d+", f"--n-gpu-layers {layers}", src)
    src = re.sub(r"--reasoning-budget \d+", f"--reasoning-budget {budget}", src)
    if "--no-kv-offload" not in src:
        src = src.replace("--n-gpu-layers %d" % layers,
                          "--n-gpu-layers %d --no-kv-offload" % layers)
    SERVICE.write_text(src)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "qwen38-agentic.service"],
                   check=True)


def wait_health(timeout: float = 180.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = subprocess.run(["curl", "-s", "http://127.0.0.1:5804/health"],
                                 capture_output=True, text=True, timeout=5).stdout
            if "ok" in out:
                return True
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    return False


def vram_free_gib() -> float:
    try:
        total = int(open("/sys/class/drm/card1/device/mem_info_vram_total").read())
        used = int(open("/sys/class/drm/card1/device/mem_info_vram_used").read())
        return (total - used) / 1073741824.0
    except Exception:
        return float("nan")


def seed_sandbox() -> Path:
    sandbox = SANDBOX
    shutil.rmtree(sandbox, ignore_errors=True)
    subprocess.run([sys.executable, str(SEED), str(sandbox), str(MANIFEST)],
                   check=True)
    return sandbox


def run_agent(sandbox: Path, timeout: int, ground: dict, model: str,
              poll_every: float = 5.0) -> dict:
    """Run the bug-hunt agent, streaming transcript to disk. Early-exits when
    every ground-truth bug is detected. Returns rc/seconds/found/reason."""
    out_dir = sandbox / "hunt_output"
    out_dir.mkdir(exist_ok=True)
    transcript = out_dir / "transcript.txt"
    prompt = HUNT_PROMPT.format(sandbox=str(sandbox))
    start = time.time()
    proc = subprocess.Popen(
        cwd=str(sandbox), stdout=guarded_open(transcript, "w"), stderr=subprocess.STDOUT,
        text=True,
    )
    found = {}
    reason = "timeout"
    rc = 124
    while time.time() - start < timeout:
        if proc.poll() is not None:
            rc = proc.returncode
            reason = "exit"
            break
        # Score whatever has streamed so far; early-exit when all found.
        try:
            text = transcript.read_text()
        except FileNotFoundError:
            text = ""
        found = scoring.scan_transcript(text, ground)
        if scoring.all_found(found, ground):
            reason = "found-all"
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            rc = proc.returncode
            break
        time.sleep(poll_every)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    # Final read of the transcript.
    text = transcript.read_text() if transcript.exists() else ""
    found = scoring.scan_transcript(text, ground)
    return {
        "rc": rc, "seconds": round(time.time() - start, 1),
        "reason": reason, "found": found,
        "n_found": len(found), "n_ground": len(ground),
        "fp": scoring.false_positives(text, ground),
    }


HUNT_PROMPT = """You are a bug hunter on a COPY of the opentrader trading system at {sandbox}.

Read the code there and find REAL bugs. Two historical defects were re-introduced
into this copy. Your job is to find them by reading source and reasoning, NOT by
running the full harness (it needs live exchanges).

For EACH bug you find, output a line exactly in this format:
FOUNDBUG <bug-id-hint>: <file>:<function> - <one-line root cause>

Hint the likely bug id from this list (it may be one of these):
- rank-dead (cross-sectional rank silently disabled)
- future-bar (future-dated daily bar not filtered -> crash-loop risk)

If you find OTHER real bugs beyond these, list them too. If you find nothing
that clearly qualifies, say so. Do not modify any file. Report what you find.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ctx", default="32768",
                    help="ctx sizes; 8K/16K are context-starved for this agent, "
                         "keep >=32768 for a meaningful test")
    ap.add_argument("--layers", default="75,99")
    ap.add_argument("--budget", default="1024,2048",
                    help="reasoning budgets; the matrix axis that actually moves "
                         "wall-clock and (likely) bug-finding depth")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--skip", default="")
    ap.add_argument("--model", default="qwen38/qwen38-agentic",
                    help="opencode model id; qwen38* patches/restarts its own "
                         "service, anything else (e.g. qwen9b/... ) leaves the "
                         "server untouched")
    args = ap.parse_args()

    backup_service()
    try:
        combos = [(int(c), int(l), int(b))
                  for c in args.ctx.split(",")
                  for l in args.layers.split(",")
                  for b in args.budget.split(",")]
        results = []
        for idx, (ctx, layers, budget) in enumerate(combos):
            combo_id = f"ctx{ctx}_l{layers}_b{budget}"
            if combo_id in [s.strip() for s in args.skip.split(",")]:
                print(f"[skip] {combo_id}")
                continue
            print(f"=== [{idx+1}/{len(combos)}] {combo_id} "
                  f"model={args.model} ===", flush=True)
            if args.model.startswith("qwen38"):
                # Only the 27B runner patches/restarts its own service; the 9B
                # server (:5802) is left untouched (it may serve live traffic).
                patch_service(ctx, layers, budget)
                if not wait_health():
                    print(f"[FAIL] {combo_id}: server not healthy after restart")
                    results.append({"ctx": ctx, "layers": layers,
                                    "budget": budget, "ok": False})
                    continue
                time.sleep(5)
            free_before = vram_free_gib()
            seed_sandbox()
            ground = scoring.load_ground(MANIFEST)
            run = run_agent(SANDBOX, args.timeout, ground, args.model)
            free_after = vram_free_gib()

            combo_dir = OUT_ROOT / combo_id
            combo_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SANDBOX / "hunt_output" / "transcript.txt",
                         combo_dir / "transcript.txt")
            meta = {
                "model": args.model,
                "ctx": ctx, "layers": layers, "budget": budget,
                "rc": run["rc"], "seconds": run["seconds"],
                "reason": run["reason"], "found": run["found"],
                "n_found": run["n_found"], "n_ground": run["n_ground"],
                "fp": run["fp"],
                "vram_free_before_gib": round(free_before, 2),
                "vram_free_after_gib": round(free_after, 2),
            }
            (combo_dir / "meta.json").write_text(json.dumps(meta, indent=2))
            results.append({**meta, "ok": True})
            print(f"--- {combo_id}: {run['reason']} rc={run['rc']} "
                  f"in {meta['seconds']}s found={run['found']}", flush=True)

        (OUT_ROOT / "matrix.json").write_text(json.dumps(results, indent=2))
        print("\n=== MATRIX COMPLETE ===")
        print(json.dumps(results, indent=2))
    finally:
        if args.model.startswith("qwen38"):
            print("restoring original service config ...", flush=True)
            restore_service()
            wait_health(timeout=120)
            print("original service restored and healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
