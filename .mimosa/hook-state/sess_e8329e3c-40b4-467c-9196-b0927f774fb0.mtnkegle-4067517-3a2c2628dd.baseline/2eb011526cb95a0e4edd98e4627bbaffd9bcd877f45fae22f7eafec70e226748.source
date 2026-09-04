#!/bin/bash
# OpenTrader Training Pipeline — runs off-hours, non-blocking
# Cron: 0 2 * * *  (daily at 2am)
set -eE  # -E: trap ERR fires even in functions

PROJECT=/home/mrc/opentrader
LOCK="$PROJECT/data/training.lock"
DATA="$PROJECT/data/training/training_data_combined.jsonl"
LAST_TRAINED="$PROJECT/data/training/last_trained_count"

# Always release lock on exit (error, interrupt, or success)
cleanup() { rm -f "$LOCK"; }
trap cleanup EXIT

cd "$PROJECT"

# Check if training is already running
if [ -f "$LOCK" ]; then
    echo "[train] Lock exists — training already running, skipping"
    exit 0
fi

# Check data volume
COUNT=$(wc -l < "$DATA" 2>/dev/null || echo 0)
LAST=$(cat "$LAST_TRAINED" 2>/dev/null || echo 0)
MIN_EXAMPLES=20
DELTA=$((COUNT - LAST))

echo "[train] Data: $COUNT examples (delta: +$DELTA since last training)"

if [ $DELTA -lt $MIN_EXAMPLES ]; then
    echo "[train] Not enough new data (need $MIN_EXAMPLES, have $DELTA) — skipping"
    exit 0
fi

# Acquire lock
touch "$LOCK"
echo "[train] Lock acquired — starting training"

# Read current active version, bump patch number
ACTIVE=$(python3 -c "
import json
reg = json.load(open('data/adapter_registry.json'))
for v, e in reg.items():
    if e.get('status') == 'active':
        parts = v.split('-')
        if len(parts) >= 2 and parts[1].startswith('S'):
            num = int(parts[1][1:])
            print(f'Ptolemy-S{num+1}')
            break
" 2>/dev/null || echo "Ptolemy-S4")

# Combine real + synthetic data if synthetic exists
COMBINED="data/training/training_data_combined.jsonl"
if [ -f "data/training/synthetic_scenarios.jsonl" ]; then
    python3 -c "
import json
real = open('data/training/training_data_combined.jsonl').readlines()
syn = open('data/training/synthetic_scenarios.jsonl').readlines()
seen = set()
merged = []
for line in real + syn:
    d = json.loads(line)
    key = d.get('conversations', d.get('messages', [{}]))[1]['content'][:100] if len(d.get('conversations', d.get('messages', []))) > 1 else str(d)[:100]
    if key not in seen:
        seen.add(key)
        if 'messages' in d: d['conversations'] = d.pop('messages')
        merged.append(d)
with open('data/training/training_data_merged.jsonl', 'w') as f:
    for d in merged: f.write(json.dumps(d) + '\n')
print(f'Merged: {len(merged)} examples')
    "
    COMBINED="data/training/training_data_merged.jsonl"
fi

# Find GPU-capable Python with Unsloth
GPU_PYTHON=python3
for candidate in ~/rocm_venv/bin/python3 ~/rocm_venv/bin/python; do
    if [ -x "$candidate" ]; then
        GPU_PYTHON="$candidate"
        break
    fi
done
echo "[train] Using Python: $GPU_PYTHON"

echo "[train] Training version: $ACTIVE, data: $COMBINED ($(wc -l < $COMBINED) examples)"

# Run training
$GPU_PYTHON -u training/finetune_cycle.py \
    --state-dir data \
    --version "$ACTIVE" \
    --data "$COMBINED" \
    --epochs 1 \
    --lora-r 16 \
    --batch-size 1 \
    --grad-accum 4 \
    --max-seq-length 1024 \
    > data/training/train_pipeline.log 2>&1

RC=$?

if [ $RC -eq 0 ]; then
    echo "$COUNT" > "$LAST_TRAINED"
    echo "[train] Training complete: $ACTIVE"
else
    echo "[train] Training failed (rc=$RC)"
fi
