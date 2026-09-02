#!/usr/bin/env bash
# OpenTrader GPU Stack — Full restart with dual-GPU config
# Usage: scripts/restart-gpu-stack.sh [--with-harness] [--no-hugginghack]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Config ──────────────────────────────────────────────────────────
AMD_PORT=5802
CUDA_PORT=5803
HH_PORT=7860

CUDA_MODEL=/home/mrc/models/qwen2.5-7b-instruct/Qwen2.5-7B-Instruct-Q4_K_M.gguf
AMD_MODEL=/home/mrc/models/ternary-bonsai-27b/Ternary-Bonsai-27B-Q2_0.gguf
CUDA_SERVER=/home/mrc/src/prismml-llama.cpp/build/bin/llama-server
AMD_SERVER=/home/mrc/src/prismml-llama.cpp/build-hip/bin/llama-server

echo "=== OpenTrader GPU Stack Restart ==="
echo ""

# ── Stop all ────────────────────────────────────────────────────────
echo "[0] Stopping existing services..."
pkill -f "llama-server.*5802" 2>/dev/null && echo "  Stopped ternary-server (:5802)" || true
pkill -f "llama-server.*5803" 2>/dev/null && echo "  Stopped qwen-server (:5803)" || true
pkill -f "uvicorn app.main.*7860" 2>/dev/null && echo "  Stopped hugginghack (:7860)" || true
pkill -f "harness\\.py" 2>/dev/null && echo "  Stopped harness" || true
sleep 2
echo ""

# ── GPU1: AMD RX 7900 GRE (ROCm) → Ternary Bonsai 27B ──────────────
echo "[1] GPU1 AMD → Ternary Bonsai 27B Q2_0 on :$AMD_PORT"

if curl -s "http://127.0.0.1:$AMD_PORT/health" > /dev/null 2>&1; then
    echo "  Already running — skip"
else
    nohup "$AMD_SERVER" \
      --model "$AMD_MODEL" \
      --host 127.0.0.1 --port "$AMD_PORT" \
      -c 262144 --n-gpu-layers 99 \
      --flash-attn on \
      --cache-type-k q4_0 --cache-type-v q4_0 \
      --parallel 1 --cont-batching \
      --threads 8 --jinja --metrics \
      --reasoning-format deepseek --reasoning-budget 512 \
      > /tmp/llama-hip-$AMD_PORT.log 2>&1 &
    echo "  PID: $! | Log: /tmp/llama-hip-$AMD_PORT.log"
fi

# ── GPU0: NVIDIA RTX 3070 (CUDA) → Qwen2.5-7B ──────────────────────
echo "[2] GPU0 RTX 3070 → Qwen2.5-7B Q4_K_M on :$CUDA_PORT"

if curl -s "http://127.0.0.1:$CUDA_PORT/health" > /dev/null 2>&1; then
    echo "  Already running — skip"
else
    CUDA_VISIBLE_DEVICES=0 nohup "$CUDA_SERVER" \
      --model "$CUDA_MODEL" \
      --host 127.0.0.1 --port "$CUDA_PORT" \
      -c 24576 --n-gpu-layers 99 \
      --cache-type-k q8_0 --cache-type-v q8_0 \
      --parallel 1 --cont-batching \
      --threads 8 --batch-size 2048 --ubatch-size 512 \
      --jinja --metrics --alias qwen2.5-7b-q4 \
      > /tmp/llama-cuda-$CUDA_PORT.log 2>&1 &
    echo "  PID: $! | Log: /tmp/llama-cuda-$CUDA_PORT.log"
fi

# ── HuggingHack: Model discovery API ────────────────────────────────
WITH_HH=true
if [ "${1:-}" = "--no-hugginghack" ] || [ "${2:-}" = "--no-hugginghack" ]; then
    WITH_HH=false
fi

if $WITH_HH; then
    echo "[3] HuggingHack model discovery on :$HH_PORT"
    if curl -s "http://127.0.0.1:$HH_PORT/api/health" > /dev/null 2>&1; then
        echo "  Already running — skip"
    else
        MODEL_STORAGE=/home/mrc/models \
        DATA_DIR="$PROJECT_DIR/tools/hugginghack/data" \
          nohup python3 -m uvicorn app.main:app \
            --app-dir "$PROJECT_DIR/tools/hugginghack/backend" \
            --host 127.0.0.1 --port $HH_PORT \
            > /tmp/hugginghack.log 2>&1 &
        echo "  PID: $! | http://127.0.0.1:$HH_PORT/api/health"
    fi
fi

# ── Wait for servers ────────────────────────────────────────────────
echo ""
echo "Waiting for servers to be ready..."

for i in $(seq 1 60); do
    AMD_OK=$(curl -s "http://127.0.0.1:$AMD_PORT/health" 2>/dev/null || echo "")
    CUDA_OK=$(curl -s "http://127.0.0.1:$CUDA_PORT/health" 2>/dev/null || echo "")
    HH_OK=true
    if $WITH_HH; then
        HH_OK=$(curl -s "http://127.0.0.1:$HH_PORT/api/health" 2>/dev/null | grep -q '"status":"ok"' && echo "ok" || echo "")
    fi

    if [ "$AMD_OK" = '{"status":"ok"}' ] && [ "$CUDA_OK" = '{"status":"ok"}' ] && { ! $WITH_HH || [ -n "$HH_OK" ]; }; then
        echo "All servers ready! ($i seconds)"
        break
    fi
    sleep 1
done

# ── Status ──────────────────────────────────────────────────────────
echo ""
echo "=== GPU STATUS ==="
echo "GPU0 (RTX 3070):"
nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu --format=csv,noheader 2>/dev/null || echo "  nvidia-smi unavailable"
echo "GPU1 (RX 7900 GRE):"
rocm-smi --showmeminfo vram --json 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)['card0']
    used = int(d['VRAM Total Used Memory (B)'])/1e9
    total = int(d['VRAM Total Memory (B)'])/1e9
    print(f'  VRAM: {used:.1f}GB / {total:.1f}GB')
except: print('  rocm-smi unavailable')
" 2>/dev/null || echo "  rocm-smi unavailable"

echo ""
echo "=== ENDPOINTS ==="
echo "  Ternary Bonsai 27B → http://127.0.0.1:$AMD_PORT/v1  (harness + subagents, 262K ctx)"
echo "  Qwen2.5-7B         → http://127.0.0.1:$CUDA_PORT/v1  (architect agent, 24K ctx)"
if $WITH_HH; then
    echo "  HuggingHack        → http://127.0.0.1:$HH_PORT       (model discovery API)"
fi
echo "  RAG (CodeSage)     → MCP (needs /new session to activate)"
echo ""
echo "Model tools:"
echo "  python3 $PROJECT_DIR/scripts/hf_models.py search \"query\""
echo "  python3 $PROJECT_DIR/scripts/hf_models.py download org/repo --gguf Q4_K_M"
echo "  python3 $PROJECT_DIR/scripts/hf_models.py list"

# ── Harness (optional) ──────────────────────────────────────────────
if [ "${1:-}" = "--with-harness" ] || [ "${2:-}" = "--with-harness" ]; then
    echo ""
    echo "[4] Starting harness on Ternary Bonsai..."
    cd "$PROJECT_DIR"
    setsid python3 harness.py --live --exchange kraken --stage 2 \
      --cash 100 --max-daily-trades 500 --parallel-debate \
      --llama-host http://127.0.0.1:$AMD_PORT \
      </dev/null >>/tmp/harness.log 2>&1 &
    disown
    echo "  Harness PID: $! | Log: /tmp/harness.log"
fi

echo ""
echo "Done. Both GPUs active. OpenCode needs /new to pick up config changes."
