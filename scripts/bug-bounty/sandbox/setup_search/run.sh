#!/usr/bin/env bash
# Launcher for the GPU1 setup-search loop. Detached, restart-safe, logs to
# data/setup_search/loop.log. Stops the live paper harness first so GPU1's
# compute is dedicated to the search.
set -euo pipefail

cd "$(dirname "$0")/.."

# Free GPU1 for the search (paper harness is flat/no-op anyway; state persists).
systemctl --user stop opentrader-harness.service 2>/dev/null || true
sleep 2

mkdir -p data/setup_search
echo "starting setup-search loop: $(date -Is)" >> data/setup_search/loop.log

setsid nohup /home/mrc/rocm_venv/bin/python3 -u -m setup_search.loop \
  --iters 4000 --max-hours 12 --plateau 150 \
  --data-period 2y --mutants 4 --scientist-every 1 \
  --val-pct 0.25 --random-restart-every 25 \
  >> data/setup_search/loop.log 2>&1 < /dev/null &
echo "PID=$!" >> data/setup_search/loop.log
echo "launched PID $! — tail -f data/setup_search/loop.log"

echo "PID=$!" >> data/setup_search/loop.log
echo "launched PID $! — tail -f data/setup_search/loop.log"
