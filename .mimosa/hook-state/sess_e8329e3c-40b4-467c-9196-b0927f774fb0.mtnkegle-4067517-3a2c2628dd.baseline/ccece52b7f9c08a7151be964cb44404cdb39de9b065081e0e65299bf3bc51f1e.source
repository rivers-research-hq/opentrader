#!/usr/bin/env bash
# Start Ternary Bonsai 27B on RTX 3070 (port 5802)
# Run this before starting opencode if the server isn't running.

BINARY=/home/mrc/src/prismml-llama.cpp/build/bin/llama-server
MODEL=/home/mrc/models/ternary-bonsai-27b/Ternary-Bonsai-27B-Q2_0.gguf
PORT=5802

if curl -s --max-time 2 http://127.0.0.1:${PORT}/health > /dev/null 2>&1; then
    echo "Ternary Bonsai already running on port ${PORT}"
    exit 0
fi

echo "Starting Ternary Bonsai 27B on RTX 3070..."
nohup env CUDA_VISIBLE_DEVICES=0 ${BINARY} \
    -m ${MODEL} \
    --host 127.0.0.1 --port ${PORT} \
    --ctx-size 4096 -ngl 99 \
    --cache-type-k q4_0 --cache-type-v q4_0 \
    --temp 0.7 --parallel 1 \
    > /tmp/ternary-bonsai.log 2>&1 &

sleep 6
if curl -s --max-time 5 http://127.0.0.1:${PORT}/health > /dev/null 2>&1; then
    echo "Ternary Bonsai started successfully on port ${PORT}"
else
    echo "ERROR: Failed to start. Check /tmp/ternary-bonsai.log"
    exit 1
fi
