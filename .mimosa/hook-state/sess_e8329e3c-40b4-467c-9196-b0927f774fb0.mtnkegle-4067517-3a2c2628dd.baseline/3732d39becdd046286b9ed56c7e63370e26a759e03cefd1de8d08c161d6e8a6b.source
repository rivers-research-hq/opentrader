#!/bin/bash
# OpenTrader Overnight Report — generated at $(date '+%Y-%m-%d %H:%M:%S %Z')
# Target: 10:30 UTC+5 = 05:30 UTC

PROJECT="/home/mrc/opentrader"
LOG="/tmp/opentrader_harness.log"
HISTORY="$PROJECT/data/history"

echo "============================================="
echo "  OpenTrader Overnight Report"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')  (UTC+5: $(date -d '+5 hours' '+%H:%M'))"
echo "============================================="
echo ""

# ── Process health ──
echo "── Process Health ──"
for name in "harness.py" "llama-swap" "dashboard.py" "ollama"; do
    if pgrep -f "$name" > /dev/null; then
        pid=$(pgrep -f "$name" | head -1)
        mem_kb=$(ps -p "$pid" -o rss= 2>/dev/null | tr -d ' ')
        mem_mb=$((mem_kb / 1024))
        echo "  🟢 $name (PID $pid, ${mem_mb}MB)"
    else
        echo "  🔴 $name — NOT RUNNING"
    fi
done
echo ""

# ── GPU/VRAM ──
if command -v rocm-smi &> /dev/null; then
    echo "── GPU ──"
    rocm-smi --showuse --showmeminfo vram 2>/dev/null | grep -E '(VRAM|GPU)' | head -6
    echo ""
fi

# ── Latest cycle ──
latest=$(ls -1t "$HISTORY"/cycle_*.json 2>/dev/null | head -1)
if [ -n "$latest" ]; then
    cycle_num=$(basename "$latest" .json | grep -oP '\d+')
    echo "── Portfolio (cycle $cycle_num) ──"

    # Extract key fields with python
    python3 -c "
import json
with open('$latest') as f:
    s = json.load(f)
tv = s.get('total_value', s.get('portfolio_value', 0))
cash = s.get('cash', 0)
print(f'  Total Value:  \${tv:,.2f}')
print(f'  Cash:         \${cash:,.2f}')
pos = s.get('positions', {})
for k,v in pos.items():
    qty = v.get('qty', 0) if isinstance(v, dict) else v
    print(f'  {k}:         {qty:.4f}')
metrics = s.get('metrics', {})
acc = metrics.get('signal_accuracy', {})
if acc:
    print(f'  Accuracy:     {acc.get(\"pct\",\"?\")}')
pct = s.get('pnl_pct', s.get('pnl', 0))
print(f'  PnL:          {pct:+.4f}%')
"
    echo ""
else
    echo "  ⚠️ No cycle state files found"
    echo ""
fi

# ── Recent log activity ──
echo "── Last 20 Log Lines ──"
tail -20 "$LOG" 2>/dev/null | grep -v '^$'
echo ""

# ── Error count ──
errors=$(grep -c 'ERROR\|CRITICAL\|Traceback' "$LOG" 2>/dev/null || echo 0)
echo "── Errors ──"
echo "  Total errors in log: $errors"
if [ "$errors" -gt 0 ]; then
    echo "  Last 5 errors:"
    grep 'ERROR\|CRITICAL\|Traceback' "$LOG" 2>/dev/null | tail -5
fi
echo ""

# ── Risk / Exposure ──
python3 "$PROJECT/report_risk.py" 2>/dev/null || echo "  (risk report skipped)"

echo ""
echo "============================================="
echo "  Report complete"
echo "============================================="
