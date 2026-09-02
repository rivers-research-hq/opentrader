#!/bin/bash
# OpenTrader Deployment Gate — promotes best evaluated candidate via DeepEval
# Candidate must beat active by ≥3.0 deep_eval points to promote.
# Cron: 0 8 * * *  (daily at 8am, before market open)
set -e

PROJECT=/home/mrc/opentrader
cd "$PROJECT"

echo "[deploy] === DeepEval Deployment Gate ==="

python3 -u << 'PYEOF'
import json, os, re, subprocess, sys
from pathlib import Path

PROJECT = Path("/home/mrc/opentrader")
sys.path.insert(0, str(PROJECT))

reg = json.load(open(PROJECT / "data" / "adapter_registry.json"))
reports_dir = PROJECT / "data" / "eval" / "reports"

# ── 1. Find active version and its latest deep_eval score ──
active_version = None
active_score = 0.0

for v, e in reg.items():
    if e.get("status") == "active":
        active_version = v
        # Load latest deep_eval report
        deep_reports = sorted(
            reports_dir.glob(f"{v}_deep_*.json"),
            key=os.path.getmtime, reverse=True,
        )
        if deep_reports:
            report = json.load(open(deep_reports[0]))
            active_score = report.get("weighted_score", 0.0)
        else:
            active_score = e.get("eval_score", 0.0)

print(f"[deploy] Active: {active_version} (deep_eval={active_score})")

# ── 2. Find best evaluated candidate via deep_eval reports ──
best_version = None
best_score = -1.0

for v, e in reg.items():
    if v == active_version:
        continue
    # Look for deep_eval report
    deep_reports = sorted(
        reports_dir.glob(f"{v}_deep_*.json"),
        key=os.path.getmtime, reverse=True,
    )
    if not deep_reports:
        continue
    report = json.load(open(deep_reports[0]))
    score = report.get("weighted_score", 0.0)
    if score > best_score:
        best_score = score
        best_version = v

if not best_version:
    print("[deploy] No candidates with deep_eval scores — nothing to promote")
    sys.exit(0)

print(f"[deploy] Best candidate: {best_version} (deep_eval={best_score})")

# ── 3. Check promotion threshold: must beat active by ≥3.0 ──
required = active_score + 3.0
if best_score < required:
    print(f"[deploy] Candidate {best_score} < active {active_score} + 3.0 = {required} — skipping")
    sys.exit(0)

# ── 4. Promote ──
print(f"[deploy] Promoting {best_version} (deep_eval={best_score}) over {active_version} (deep_eval={active_score})")
print(f"[deploy] Margin: {best_score - active_score:.1f} points >= 3.0 — PASS")

# Update registry
for v, e in reg.items():
    if e.get("status") == "active":
        e["status"] = "replaced"
reg[best_version]["status"] = "active"
reg[best_version]["eval_score"] = best_score

with open(PROJECT / "data" / "adapter_registry.json", "w") as f:
    json.dump(reg, f, indent=2)
print("[deploy] Registry updated")

# ── 5. Update llama-dynamic-ptolemy script ──
script = Path("/home/mrc/.local/bin/llama-dynamic-ptolemy")
if script.exists():
    entry = reg.get(best_version, {})
    base_name = entry.get("base_model", "")
    gguf_rel = entry.get("gguf_path", "")

    content = script.read_text()

    # Update MODEL
    candidates = [
        Path("/home/mrc/models") / base_name,
        Path("/home/mrc/models") / base_name / base_name,
        Path("/home/mrc/models/qwen2.5-7b-instruct") / base_name,
    ]
    base_path = None
    for c in candidates:
        if c.exists():
            base_path = c
            break
    if base_path:
        content = re.sub(r'^MODEL=".*"', f'MODEL="{base_path}"', content, flags=re.MULTILINE)

    # Update LORA
    if gguf_rel:
        lora_path = PROJECT / gguf_rel
        content = re.sub(r'^LORA=".*"', f'LORA="{lora_path}"', content, flags=re.MULTILINE)

    # Update alias
    content = re.sub(r'--alias\s+\S+', f'--alias {best_version}', content)

    script.write_text(content)
    print(f"[deploy] Updated llama-dynamic-ptolemy script for {best_version}")

    # Reload llama-swap
    try:
        result = subprocess.run(
            ["pgrep", "-f", "llama-swap"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                subprocess.run(["kill", "-SIGHUP", pid], capture_output=True, timeout=5)
                print(f"[deploy] llama-swap reloaded (PID {pid})")
    except Exception as e:
        print(f"[deploy] WARNING: llama-swap reload failed: {e}")

else:
    print(f"[deploy] WARNING: llama-dynamic-ptolemy script not found")

print(f"[deploy] Active: {best_version} (deep_eval={best_score}) — READY")
PYEOF
