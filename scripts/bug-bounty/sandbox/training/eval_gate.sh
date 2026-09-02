#!/bin/bash
# OpenTrader Evaluation Gate — DeepEval candidates with dedicated llama-server
# 1. SIGSTOP the harness to free VRAM
# 2. For each untested candidate: spawn llama-server, run DeepEval, kill server
# 3. SIGCONT the harness
# 4. Chain into deploy gate if scores improved
#
# Safe for cron: uses lockfile to prevent concurrent runs; exits immediately
# if no untested candidates are found (polling is cheap).
set -e

PROJECT=/home/mrc/opentrader
DEEP_EVAL_PORT=5805
LOCKFILE="/tmp/opentrader_eval_gate.lock"
LLAMA_BIN="/home/mrc/src/modelai-llama.cpp/build-wmma/bin/llama-server"

cd "$PROJECT"

# ── Lockfile to prevent concurrent cron overlap ──
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "[eval] Locked — another eval_gate is running. Exiting."
    exit 0
fi

# ── Training guard: yield if training pipeline is active ──
TRAINING_LOCK="$PROJECT/data/training.lock"
if [ -f "$TRAINING_LOCK" ]; then
    echo "[eval] Training lock present — skipping (training in progress)"
    exit 0
fi

echo "[eval] === Deep Evaluation Gate ==="

# ── 1. Find harness PID and pause it ──
HARNESS_PID=$(pgrep -f "harness.py" | head -1 || true)
if [ -n "$HARNESS_PID" ]; then
    echo "[eval] Pausing harness (PID $HARNESS_PID)..."
    kill -SIGSTOP "$HARNESS_PID"
    echo "[eval] Harness paused — VRAM will be freed"
    HARNESS_STOPPED=true
    trap 'if [ "$HARNESS_STOPPED" = "true" ] && [ -n "$HARNESS_PID" ]; then kill -SIGCONT "$HARNESS_PID" 2>/dev/null || true; echo "[eval] Harness resumed via trap"; fi' EXIT INT TERM
    sleep 2
else
    echo "[eval] No harness process found — continuing"
fi

# ── 2. Kill any existing llama-server on our eval port ──
EXISTING_PID=$(pgrep -f "llama-server.*:$DEEP_EVAL_PORT" | head -1 || true)
if [ -n "$EXISTING_PID" ]; then
    echo "[eval] Killing existing llama-server on :$DEEP_EVAL_PORT (PID $EXISTING_PID)..."
    kill "$EXISTING_PID" 2>/dev/null || true
    sleep 2
fi

# ── 3. Find untested candidates ──
python3 -u << 'PYEOF'
import json, sys
from pathlib import Path

PROJECT = Path("/home/mrc/opentrader")
sys.path.insert(0, str(PROJECT))

reg = json.load(open(PROJECT / "data" / "adapter_registry.json"))
reports_dir = PROJECT / "data" / "eval" / "reports"

active_version = None
candidates = []

for v, e in reg.items():
    if e.get("status") == "active":
        active_version = v
    elif e.get("status") in ("completed", "pending", "rolled_back", "superseded"):
        has_deep = len(list(reports_dir.glob(f"{v}_deep_*.json"))) > 0 if reports_dir.exists() else False
        if not has_deep:
            candidates.append(v)

print(f"[eval] Active: {active_version}")
print(f"[eval] Untested candidates: {len(candidates)}")
if candidates:
    print(f"[eval] Candidates: {', '.join(candidates)}")

# Write candidates list to temp file for shell loop
Path("/tmp/deep_eval_candidates.txt").write_text("\n".join(candidates))
PYEOF

CANDIDATES=$(cat /tmp/deep_eval_candidates.txt 2>/dev/null || echo "")
rm -f /tmp/deep_eval_candidates.txt

if [ -z "$CANDIDATES" ]; then
    echo "[eval] No untested candidates — resuming harness and exiting"
    if [ -n "$HARNESS_PID" ]; then
        kill -SIGCONT "$HARNESS_PID"
        echo "[eval] Harness resumed"
    fi
    exit 0
fi

# ── 4. Evaluate each candidate ──
for VERSION in $CANDIDATES; do
    echo ""
    echo "[eval] === Evaluating $VERSION ==="

    # Spawn dedicated llama-server
    echo "[eval] Starting llama-server on :$DEEP_EVAL_PORT for $VERSION..."

    # Look up base and LoRA paths from registry
    BASE_MODEL=$(python3 -c "
import json
reg = json.load(open('$PROJECT/data/adapter_registry.json'))
e = reg.get('$VERSION', {})
print(e.get('base_model', ''))
")
    GGUF_PATH=$(python3 -c "
import json
reg = json.load(open('$PROJECT/data/adapter_registry.json'))
e = reg.get('$VERSION', {})
print(e.get('gguf_path', ''))
")

    if [ -z "$BASE_MODEL" ]; then
        echo "[eval] WARNING: $VERSION has no base_model — skipping"
        continue
    fi

    # Resolve base GGUF path
    if [ -f "/home/mrc/models/$BASE_MODEL" ]; then
        BASE_GGUF="/home/mrc/models/$BASE_MODEL"
    elif [ -f "/home/mrc/models/$BASE_MODEL/$BASE_MODEL" ]; then
        BASE_GGUF="/home/mrc/models/$BASE_MODEL/$BASE_MODEL"
    elif [ -f "/home/mrc/models/qwen2.5-7b-instruct/$BASE_MODEL" ]; then
        BASE_GGUF="/home/mrc/models/qwen2.5-7b-instruct/$BASE_MODEL"
    else
        echo "[eval] WARNING: Cannot find base GGUF for $BASE_MODEL — skipping $VERSION"
        continue
    fi

    LORA_PATH="$PROJECT/$GGUF_PATH"
    if [ ! -f "$LORA_PATH" ]; then
        echo "[eval] WARNING: LoRA GGUF not found at $LORA_PATH — running base only"
        LORA_FLAG=""
    else
        LORA_FLAG="--lora $LORA_PATH"
    fi

    export LD_LIBRARY_PATH="/home/mrc/src/modelai-llama.cpp/build-wmma/bin:/opt/rocm/lib:/opt/rocm/hip/lib:${LD_LIBRARY_PATH}"

    $LLAMA_BIN \
        --model "$BASE_GGUF" \
        $LORA_FLAG \
        --alias "$VERSION" \
        --host 127.0.0.1 --port $DEEP_EVAL_PORT \
        --ctx-size 8192 \
        --n-gpu-layers 99 \
        --cache-type-k q8_0 --cache-type-v q8_0 \
        --jinja \
        --parallel 1 --cont-batching \
        --threads 8 --batch-size 4096 --ubatch-size 1024 \
        --temp 0.3 --top-p 0.95 --top-k 64 \
        --repeat-penalty 1.0 \
        --n-predict 2048 \
        > /dev/null 2>&1 &

    SERVER_PID=$!
    echo "[eval] llama-server PID: $SERVER_PID"

    # Wait for /health
    echo "[eval] Waiting for server to be ready..."
    for i in $(seq 1 60); do
        if curl -sf "http://127.0.0.1:$DEEP_EVAL_PORT/health" > /dev/null 2>&1; then
            echo "[eval] Server ready after ${i}s"
            break
        fi
        if [ $i -eq 60 ]; then
            echo "[eval] ERROR: Server failed to start within 60s"
            kill "$SERVER_PID" 2>/dev/null || true
            continue 2
        fi
        sleep 1
    done

    # Run DeepEval
    echo "[eval] Running DeepEval for $VERSION..."
    python3 -m training.eval_deploy evaluate "$VERSION" --port $DEEP_EVAL_PORT

    echo "[eval] Evaluation complete for $VERSION"

    # Kill server
    echo "[eval] Stopping llama-server..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "[eval] Server stopped"

    # Wait for VRAM to free
    echo "[eval] Waiting for VRAM to free..."
    sleep 5
    if command -v rocm-smi &> /dev/null; then
        rocm-smi --showmeminfo vram 2>/dev/null | head -10 || true
    fi
    echo ""
done

# ── 5. Resume harness ──
echo "[eval] === Evaluation sweep complete ==="
if [ -n "$HARNESS_PID" ]; then
    echo "[eval] Resuming harness (PID $HARNESS_PID)..."
    kill -SIGCONT "$HARNESS_PID"
    HARNESS_STOPPED=false
    echo "[eval] Harness resumed"
fi

# ── 6. Chain into deploy gate ──
echo "[eval] Chaining into deploy gate..."
if [ -f "$PROJECT/training/deploy_gate.sh" ]; then
    bash "$PROJECT/training/deploy_gate.sh" || echo "[eval] deploy_gate failed (non-fatal)"
fi

echo "[eval] Done"
