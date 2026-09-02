#!/bin/bash
# Benchmark v2: run each Qwen3.8 agent prompt on opentrader, capture output + timing.
set -u
OUTDIR="/home/mrc/opentrader/data/benchmark-q38"
mkdir -p "$OUTDIR"

run_agent() {
  local agent="$1"
  local task="$2"
  local out="$OUTDIR/v2-${agent}.txt"
  echo "=== RUNNING $agent ==="
  start=$(date +%s)
  cd /home/mrc/opentrader
  timeout 600 opencode run --agent "$agent" --auto "$task" >"$out" 2>&1
  local rc=$?
  end=$(date +%s)
  echo "--- $agent exit=$rc in $((end-start))s ---"
  tail -4 "$out" 2>/dev/null
  echo
}

run_agent "builder" "Do a SAFE READ-ONLY audit: list files in /home/mrc/opentrader, find the harness entrypoint, and report in 3 sentences what its main loop does. DO NOT edit anything."

run_agent "architect" "READ-ONLY infrastructure check. Run nvidia-smi and rocm-smi to report VRAM on each GPU. curl http://127.0.0.1:5804/health. Report which model is on :5804. Do not start or stop anything."

run_agent "supervisor" "Portfolio risk check (READ-ONLY): read /home/mrc/opentrader/data/paper_state.json. Report cash, positions, portfolio_value, cycle, and whether the timestamp looks stale vs today 2026-08-16. Flag red flags. Do not modify anything."

run_agent "modelfixer" "Diagnose: Qwen3.8 agentic server runs on :5804 as systemd user service qwen38-agentic. Verify health: systemctl --user status qwen38-agentic, curl :5804/health, tail /home/mrc/opentrader/data/qwen38-agentic.log for errors. Report findings. Do not restart anything."

echo "=== DONE ==="
echo "=== qwen-worker via task delegation (from builder) ==="
cd /home/mrc/opentrader
timeout 400 opencode run --agent builder --auto "Delegate ONE task to the qwen-worker subagent via the task tool: ask it to read /home/mrc/opentrader/data/paper_state.json and report cycle + cash. Then report the subagent's answer." > /home/mrc/opentrader/data/benchmark-q38/v2-qwen-worker-delegated.txt 2>&1
echo "--- qwen-worker-delegated exit=$? ---"
tail -6 /home/mrc/opentrader/data/benchmark-q38/v2-qwen-worker-delegated.txt 2>/dev/null
echo
echo "=== manager delegation (manager is cloud openrouter, skip) ==="
echo "DONE"
