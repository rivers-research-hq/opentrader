#!/usr/bin/env bash
# qwen38-serve.sh — OOM-proof launcher for llama-server serving Qwen3.8-27B.
#
# Pre-flight: computes the VRAM/RAM budget from the RESOLVED flags and refuses
# to start (exit non-zero, logged) if the model + KV cache + compute buffer
# exceed the GPU/RAM budget. On pass, execs llama-server so it runs inside the
# caller's cgroup (systemd MemoryMax= / MemorySwapMax=0 still apply).
#
# Budget constants sourced from docs/agents/research/qwen38-27b-kv-budget.md.
# Weights are measured from the actual file via stat (NOT the research note's
# HF lfs.size, which is stale by ~280 MiB).
set -euo pipefail

# ---- budget constants (MiB) ----
STATE_MIB=152        # Gated DeltaNet fixed recurrent state (48 layers, fp32)
COMPUTE_MIB=1536     # compute buffer + ROCm/CUDA context/graph + cross-GPU copy overhead
VRAM_MARGIN_MIB=512  # safety headroom below measured free VRAM
RAM_FLOOR_MIB=4096   # refuse if the box has less than this much RAM available

# KV bytes/token by cache dtype (16 full-attn layers × 2 × 4 KV-heads × 256 dim)
declare -A KV_BYTES=(
  [q8_0]=32768
  [q4_0]=16384
  [f16]=65536
)

log() { printf '[qwen38-preflight] %s\n' "$*" >&2; }

# ---- parse llama-server args ----
MODEL=""; CTX=""; KVTYPE="q8_0"
prev=""
for a in "$@"; do
  case "$prev" in
    --model) MODEL="$a"; prev=""; continue ;;
    --ctx-size|-c) CTX="$a"; prev=""; continue ;;
    --cache-type-k) KVTYPE="$a"; prev=""; continue ;;
    "") ;;
  esac
  case "$a" in
    --model) prev="--model" ;;
    --ctx-size|-c) prev="--ctx-size" ;;
    --cache-type-k) prev="--cache-type-k" ;;
  esac
done

if [[ -z "$MODEL" || -z "$CTX" ]]; then
  log "FATAL: could not resolve --model and --ctx-size from args: $*"
  exit 1
fi

if [[ -z "${KV_BYTES[$KVTYPE]:-}" ]]; then
  log "FATAL: unsupported KV dtype '$KVTYPE' (supported: q8_0, q4_0, f16)"
  exit 1
fi

# KV offload: --no-kv-offload moves the KV cache to system RAM.
KV_OFFLOAD=1
for a in "$@"; do
  [ "$a" = "--no-kv-offload" ] && KV_OFFLOAD=0
done

# ---- compute budget from resolved flags ----
WEIGHT_BYTES=$(stat -c %s "$MODEL")
WEIGHTS_MIB=$(( WEIGHT_BYTES / 1048576 ))
KV_MIB=$(( CTX * KV_BYTES[$KVTYPE] / 1048576 ))
if [ "$KV_OFFLOAD" = "1" ]; then
  VRAM_KV_MIB=$KV_MIB
else
  VRAM_KV_MIB=0
fi
TOTAL_VRAM_MIB=$(( WEIGHTS_MIB + VRAM_KV_MIB + STATE_MIB + COMPUTE_MIB ))

# ---- measure free VRAM on all GPUs (GRE via rocm-smi + any NVIDIA via nvidia-smi) ----
# Dual-GPU builds split layers across both cards, so the budget is the SUM of
# free VRAM. Single-GPU behavior is preserved when nvidia-smi is absent/busy-free.
VRAM_INFO=$(rocm-smi --showmeminfo vram 2>/dev/null) || true
VRAM_TOTAL=$(printf '%s\n' "$VRAM_INFO" | awk '/VRAM Total Memory \(B\)/{print $NF; exit}')
VRAM_USED=$(printf '%s\n' "$VRAM_INFO" | awk '/VRAM Total Used Memory \(B\)/{print $NF; exit}')
if [[ -z "${VRAM_TOTAL:-}" || -z "${VRAM_USED:-}" ]]; then
  log "FATAL: could not read VRAM from rocm-smi; refusing to guess"
  exit 1
fi
VRAM_FREE_MIB=$(( (VRAM_TOTAL - VRAM_USED) / 1048576 ))

NVIDIA_FREE_MIB=0
NVIDIA_INFO=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null) || true
if [[ -n "${NVIDIA_INFO:-}" ]]; then
  # Reserve 512 MiB per NVIDIA card for desktop/display use.
  while read -r FREE; do
    [[ -n "$FREE" ]] && NVIDIA_FREE_MIB=$(( NVIDIA_FREE_MIB + FREE - 512 ))
  done <<< "$NVIDIA_INFO"
  (( NVIDIA_FREE_MIB < 0 )) && NVIDIA_FREE_MIB=0
fi

RAM_AVAIL_MIB=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)

log "weights=${WEIGHTS_MIB}MiB  kv(${KVTYPE}@ctx${CTX})=${KV_MIB}MiB  state=${STATE_MIB}MiB  compute=${COMPUTE_MIB}MiB  kv_offload=${KV_OFFLOAD}"
log "amd_free=${VRAM_FREE_MIB}MiB  nvidia_free_usable=${NVIDIA_FREE_MIB}MiB  margin=${VRAM_MARGIN_MIB}MiB  ram_avail=${RAM_AVAIL_MIB}MiB"

# ---- gate: VRAM (combined pool) ----
TOTAL_FREE_MIB=$(( VRAM_FREE_MIB + NVIDIA_FREE_MIB ))
if (( TOTAL_VRAM_MIB > TOTAL_FREE_MIB - VRAM_MARGIN_MIB )); then
  log "REFUSING: total VRAM ${TOTAL_VRAM_MIB}MiB exceeds combined free ${TOTAL_FREE_MIB}MiB minus ${VRAM_MARGIN_MIB}MiB margin"
  exit 2
fi

# ---- gate: RAM (includes KV if offloaded to RAM) ----
if (( RAM_AVAIL_MIB < RAM_FLOOR_MIB + KV_MIB )); then
  log "REFUSING: only ${RAM_AVAIL_MIB}MiB RAM available (need ${KV_MIB}MiB KV + ${RAM_FLOOR_MIB}MiB floor)"
  exit 2
fi

log "PASS: budget fits. exec llama-server"
exec "$@"
