#!/bin/bash
# Ptolemy-S3 training launcher
cd /home/mrc/opentrader
exec python3 -u training/finetune_cycle.py \
  --state-dir data \
  --version Ptolemy-S3 \
  --data data/training/training_data_merged_v2.jsonl \
  --epochs 3 \
  --lora-r 16 \
  --batch-size 1 \
  --grad-accum 4 \
  --max-seq-length 2048
