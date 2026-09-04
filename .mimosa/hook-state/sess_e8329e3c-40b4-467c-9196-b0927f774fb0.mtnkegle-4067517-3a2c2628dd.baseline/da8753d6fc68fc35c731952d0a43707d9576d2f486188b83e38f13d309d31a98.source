#!/usr/bin/env bash
# run_test.sh — Run a quick harness test
# Usage: ./scripts/run_test.sh [harness options...]
#
# Defaults:
#   --symbol BTC/USDT  --cash 100000  --agent heuristic
#   --bars 200         --max-cycles 30  --interval 0.01
#
# Examples:
#   ./scripts/run_test.sh --agent heuristic --max-cycles 50
#   ./scripts/run_test.sh --agent trading_agent --model opentrader-agent --no-model
#   ./scripts/run_test.sh --exchange live --backtest --max-cycles 50
#   ./scripts/run_test.sh --fast-model hermes-3-llama-3.1-8b --interval 0.5

set -euo pipefail
cd "$(dirname "$0")/.."

exec python harness.py \
    --symbol BTC/USDT \
    --cash "${CASH:-100000}" \
    --agent "${AGENT:-heuristic}" \
    --bars "${BARS:-200}" \
    --max-cycles "${CYCLES:-30}" \
    --interval "${INTERVAL:-0.01}" \
    --state-dir "${STATE_DIR:-./data}" \
    "$@"
