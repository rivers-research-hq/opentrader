#!/usr/bin/env bash
# local_candidate — launch a candidate llama-server for A/B measurement.
#
# Runs on a scratch port against an explicit model + flags, so the live worker
# unit is never edited mid-experiment. The GRE holds one model at a time, so the
# live worker must be stopped first (this refuses to start if it is running).
#
#   scripts/local_candidate.sh <name> <model.gguf> [--ctx N] [--n-cpu-moe N] \
#       [--kv q8_0|q4_0] [--draft draft.gguf] [--draft-n-max N] \
#       [--cache-reuse N] [-- <extra llama-server flags>]
#
# Tear down with scripts/local_candidate_stop.sh <name>.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?usage: local_candidate.sh <name> <model.gguf> [flags]}"; shift
MODEL="${1:?model path}"; shift
PORT="${PORT:-5809}"
CTX=65536; NCMOE=0; KV=q8_0; DRAFT=""; DNMAX=3; CREUSE=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --ctx) CTX="$2"; shift 2;;
    --n-cpu-moe) NCMOE="$2"; shift 2;;
    --kv) KV="$2"; shift 2;;
    --draft) DRAFT="$2"; shift 2;;
    --draft-n-max) DNMAX="$2"; shift 2;;
    --cache-reuse) CREUSE="$2"; shift 2;;
    --) shift; EXTRA=("$@"); break;;
    *) EXTRA+=("$1"); shift;;
  esac
done
OUT="$REPO/data/local/$NAME"; mkdir -p "$OUT"
LOG="$OUT/server.log"
BIN=/home/mrc/src/llama.cpp/build/bin/llama-server

# Declare the device: this job wants the GRE, and the GRE yields to gaming.
"$REPO/.venv/bin/python3" "$REPO/scripts/gpu_pick.py" --want gre \
  || { echo "[candidate] GRE unavailable (gaming) — aborting"; exit 3; }

if systemctl --user is-active --quiet local-worker.service; then
  echo "[candidate] local-worker.service is running; the GRE fits one model."
  echo "[candidate] stop it first:  systemctl --user stop local-worker.service"
  exit 4
fi
if ss -ltn "sport = :$PORT" 2>/dev/null | grep -q ":$PORT"; then
  echo "[candidate] port $PORT already busy"; exit 5
fi

ARGS=(--model "$MODEL" --alias "$NAME" --host 127.0.0.1 --port "$PORT"
      --n-gpu-layers 99 --n-cpu-moe "$NCMOE" --ctx-size "$CTX" --ctx-checkpoints 4
      --flash-attn on --cache-type-k "$KV" --cache-type-v "$KV"
      --parallel 1 --cont-batching --threads 8 --jinja --metrics)
[ "$CREUSE" != 0 ] && ARGS+=(--cache-reuse "$CREUSE")
if [ -n "$DRAFT" ]; then
  ARGS+=(--spec-draft-model "$DRAFT" --spec-draft-ngl 99 --spec-draft-n-max "$DNMAX")
fi
ARGS+=("${EXTRA[@]}")

echo "[candidate] $NAME on :$PORT model=$(basename "$MODEL") ctx=$CTX ncmoe=$NCMOE kv=$KV draft=${DRAFT:-none}"
printf '%s\n' "${ARGS[@]}" > "$OUT/server.argv"
nohup "$BIN" "${ARGS[@]}" > "$LOG" 2>&1 &
PID=$!; echo "$PID" > "$OUT/server.pid"
echo "[candidate] pid $PID log $LOG"

for i in $(seq 1 240); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "[candidate] ready after ${i}s"; exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "[candidate] server exited — tail of $LOG:"; tail -25 "$LOG"; exit 6
  fi
  sleep 1
done
echo "[candidate] timed out waiting for readiness"; tail -25 "$LOG"; exit 7
