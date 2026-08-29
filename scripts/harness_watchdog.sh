#!/bin/bash
# Harness Watchdog — launches and auto-restarts the OpenTrader harness.
# Keeps the harness alive through crashes, OOM kills, and segfaults.
#
# Usage:
#   ./harness_watchdog.sh                # default config
#   ./harness_watchdog.sh --symbols BTC/USDT,ETH/USDT --max-cycles 0
#
# Logs to: data/watchdog_harness.log
# Uses exponential backoff (1s → 60s max) between restarts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/data/watchdog_harness.log"
MAX_BACKOFF=60
MIN_BACKOFF=1
MAX_CONSECUTIVE_CRASHES=20

# RUNWAY defaults (2026-08-05): validated rule config is the trader,
# paper on real prices, risk config frozen, no LLM.
HARNESS_ARGS=(
    --exchange finnhub
    --no-synthetic
    --stage 3
    --symbols "AAPL,MSFT,NVDA,AMD,AMZN,GOOGL,META,JPM,XOM,JNJ,PG,KO,DIS,CSCO,WMT,NFLX,BTC/USDT,ETH/USDT,SOL/USDT"
    --no-universe
    --cash 500
    --max-cycles 0
    --max-daily-trades 30
    --no-model
    --rule-primary
    --pin-risk
    --interval 60
    "${@}"
)

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "====== Harness Watchdog started ======"
log "Args: ${HARNESS_ARGS[*]}"

backoff=$MIN_BACKOFF
crash_count=0

while true; do
    if [ $crash_count -ge $MAX_CONSECUTIVE_CRASHES ]; then
        log "FATAL: $MAX_CONSECUTIVE_CRASHES consecutive crashes — giving up"
        exit 1
    fi

    log "Launching harness (attempt #$((crash_count + 1)))..."
    log "  backoff=${backoff}s"

    set +e
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_MAX_THREADS=1 \
    setsid python3 "$SCRIPT_DIR/harness.py" "${HARNESS_ARGS[@]}" >> "$LOG_FILE" 2>&1
    exit_code=$?
    set -e

    log "Harness exited with code $exit_code"

    if [ $exit_code -eq 0 ] || [ $exit_code -eq 130 ] || [ $exit_code -eq 143 ]; then
        log "Clean exit (SIGINT/SIGTERM or normal) — stopping watchdog"
        exit 0
    fi

    crash_count=$((crash_count + 1))
    log "Crash $crash_count — restarting in ${backoff}s"

    sleep $backoff
    backoff=$((backoff * 2))
    if [ $backoff -gt $MAX_BACKOFF ]; then
        backoff=$MAX_BACKOFF
    fi
done
