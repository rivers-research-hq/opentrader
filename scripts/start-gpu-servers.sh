#!/usr/bin/env bash
# Parallel GPU Startup — Both GPUs work simultaneously
# GPU0 (RTX 3070, 8GB, CUDA): Qwen2.5-7B-Q4_K_M on :5803 → Architect (Opencode)
# GPU1 (RX 7900 GRE, 16GB, ROCm): Ternary Bonsai 27B-Q2_0 on :5802 → Trading Harness
#
# Usage: scripts/start-gpu-servers.sh [--with-harness]

set -e

AMD_PORT=5802
CUDA_PORT=5803
CUDA_MODEL=/home/mrc/models/qwen2.5-7b-instruct/Qwen2.5-7B-Instruct-Q4_K_M.gguf
AMD_MODEL=/home/mrc/models/ternary-bonsai-27b/Ternary-Bonsai-27B-Q2_0.gguf
CUDA_SERVER=/home/mrc/src/prismml-llama.cpp/build/bin/llama-server
AMD_SERVER=/home/mrc/src/prismml-llama.cpp/build-hip/bin/llama-server

echo "=== PARALLEL GPU STARTUP ==="
echo ""

# ── GPU0: NVIDIA RTX 3070 (CUDA) ──────────────────────────────────
echo "[GPU0] RTX 3070 → Qwen2.5-7B-Q4_K_M on :$CUDA_PORT"

if curl -s "http://127.0.0.1:$CUDA_PORT/health" > /dev/null 2>&1; then
    echo "  Already running — skip"
else
    echo "  Starting CUDA llama-server..."
    CUDA_VISIBLE_DEVICES=0 nohup "$CUDA_SERVER" \
      --model "$CUDA_MODEL" \
      --host 127.0.0.1 --port "$CUDA_PORT" \
      -c 24576 --n-gpu-layers 99 \
      --cache-type-k q8_0 --cache-type-v q8_0 \
      --parallel 1 --cont-batching \
      --threads 8 --batch-size 2048 --ubatch-size 512 \
      --jinja --metrics \
      --alias qwen2.5-7b-q4 \
      > /tmp/llama-cuda-$CUDA_PORT.log 2>&1 &
    echo "  PID: $! | Log: /tmp/llama-cuda-$CUDA_PORT.log"
fi

# ── GPU1: AMD RX 7900 GRE (ROCm) ──────────────────────────────────
echo "[GPU1] RX 7900 GRE → Ternary Bonsai 27B-Q2_0 on :$AMD_PORT"

if curl -s "http://127.0.0.1:$AMD_PORT/health" > /dev/null 2>&1; then
    echo "  Already running — skip"
else
    echo "  Starting ROCm llama-server..."
    nohup "$AMD_SERVER" \
      --model "$AMD_MODEL" \
      --host 127.0.0.1 --port "$AMD_PORT" \
      -c 262144 --n-gpu-layers 99 \
      --flash-attn on \
      --cache-type-k q4_0 --cache-type-v q4_0 \
      --parallel 1 --cont-batching \
      --threads 8 --jinja --metrics \
      --reasoning-format deepseek \
      --reasoning-budget 512 \
      > /tmp/llama-hip-$AMD_PORT.log 2>&1 &
    echo "  PID: $! | Log: /tmp/llama-hip-$AMD_PORT.log"
fi

# ── Wait for both servers ──────────────────────────────────────────
echo ""
echo "Waiting for servers to be ready..."

for i in $(seq 1 30); do
    CUDA_OK=$(curl -s "http://127.0.0.1:$CUDA_PORT/health" 2>/dev/null || echo "")
    AMD_OK=$(curl -s "http://127.0.0.1:$AMD_PORT/health" 2>/dev/null || echo "")
    
    if [ "$CUDA_OK" = '{"status":"ok"}' ] && [ "$AMD_OK" = '{"status":"ok"}' ]; then
        echo "Both servers ready! ($i seconds)"
        break
    fi
    sleep 1
done

# ── Status ─────────────────────────────────────────────────────────
echo ""
echo "=== GPU STATUS ==="
echo "GPU0 (RTX 3070):"
nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader 2>/dev/null || echo "  nvidia-smi failed"
echo "GPU1 (RX 7900 GRE):"
rocm-smi --showmeminfo vram --json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)['card0']
used = int(d['VRAM Total Used Memory (B)']) / 1e9
total = int(d['VRAM Total Memory (B)']) / 1e9
print(f'  VRAM: {used:.1f}GB / {total:.1f}GB used')
" 2>/dev/null || echo "  rocm-smi failed"

echo ""
echo "Server endpoints:"
echo "  Architect  → http://127.0.0.1:$CUDA_PORT (Qwen2.5-7B-Q4, CUDA)"
echo "  Harness    → http://127.0.0.1:$AMD_PORT (Ternary Bonsai 27B, ROCm)"
echo ""

# ── HuggingHack: Model discovery API ──────────────────────────────────
HH_PORT=7860
echo "Starting HuggingHack model discovery on :$HH_PORT..."
if curl -s "http://127.0.0.1:$HH_PORT/api/health" > /dev/null 2>&1; then
    echo "  Already running — skip"
else
    MODEL_STORAGE=/home/mrc/models DATA_DIR=/home/mrc/opentrader/tools/hugginghack/data \
      nohup python3 -m uvicorn app.main:app \
        --app-dir /home/mrc/opentrader/tools/hugginghack/backend \
        --host 127.0.0.1 --port $HH_PORT \
        > /tmp/hugginghack.log 2>&1 &
    echo "  PID: $! | http://127.0.0.1:$HH_PORT/api/health"
fi
echo ""

# ── Optional: Start harness ────────────────────────────────────────
if [ "${1:-}" = "--with-harness" ]; then
    echo "Starting harness on AMD model..."
    cd /home/mrc/opentrader
    setsid python3 harness.py --live --exchange alpaca-paper --stage 3 \
      --cash 100 --llama-host http://127.0.0.1:5802 --max-cycles 0 \
      --debate-mode adir --parallel-debate --interval 10 \
      </dev/null >>/tmp/harness.log 2>&1 &
    disown
    echo "Harness PID: $!"
fi

echo "Done. Both GPUs active in parallel."
