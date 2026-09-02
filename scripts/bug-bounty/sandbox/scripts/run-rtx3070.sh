#!/usr/bin/env bash
# Run a Python script on the RTX 3070
# Usage: scripts/run-rtx3070.sh path/to/script.py [args...]

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <script.py> [args...]"
    exit 1
fi

SCRIPT="$1"
shift

export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export PYTHONNOUSERSITE=1

exec conda run -n cuda-rtx3070 python3 "$SCRIPT" "$@"
