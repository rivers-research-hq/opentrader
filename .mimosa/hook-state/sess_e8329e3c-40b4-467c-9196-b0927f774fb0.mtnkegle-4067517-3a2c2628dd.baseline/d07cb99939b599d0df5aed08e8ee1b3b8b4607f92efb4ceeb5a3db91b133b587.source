#!/usr/bin/env bash
# Activate RTX 3070 as the primary CUDA compute accelerator
# Usage: source scripts/activate-rtx3070.sh

export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_HOME=/opt/cuda
export PATH="/opt/cuda/bin:$PATH"
export LD_LIBRARY_PATH="/opt/cuda/lib64:/opt/cuda/nvvm/lib64:$LD_LIBRARY_PATH"

# Point to CUDA conda env
export CONDA_ENV="cuda-rtx3070"
export PYTHONNOUSERSITE=1

nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv,noheader 2>/dev/null

echo "[RTX3070] CUDA accelerator activated"
echo "  Conda env : cuda-rtx3070"
echo "  CUDA      : $(nvcc --version 2>/dev/null | grep release | awk '{print $5,$6}')"
echo "  PyTorch   : CUDA 12.4 (2.6.0)"
echo "  Use       : conda activate cuda-rtx3070 && PYTHONNOUSERSITE=1 python3 ..."
