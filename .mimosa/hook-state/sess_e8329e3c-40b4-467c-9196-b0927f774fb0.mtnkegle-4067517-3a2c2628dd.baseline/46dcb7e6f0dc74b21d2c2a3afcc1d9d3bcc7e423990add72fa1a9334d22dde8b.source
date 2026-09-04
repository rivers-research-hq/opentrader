#!/usr/bin/env bash
# GPU Handoff Protocol — compact context from active server to disk
# Usage: scripts/gpu-handoff.sh [port] [target-context]
#   Default: hits port 5802, produces handoff for 16384 token target
#   The handoff is saved to logs/handoff-<timestamp>.md
#   Paste it into a fresh architect session on the new GPU.

PORT="${1:-5802}"
TARGET_CTX="${2:-16384}"
HANDOFF_FILE="/home/mrc/opentrader/logs/handoff-$(date +%Y%m%d-%H%M%S).md"

# 25% of target context for the handoff (leaves 75% for new work)
MAX_TOKENS=$((TARGET_CTX / 4))

echo "=== GPU HANDOFF: port=${PORT} → target_ctx=${TARGET_CTX} ==="
echo "Handoff file: $HANDOFF_FILE"
echo "Max tokens: $MAX_TOKENS"

# Send compaction request to source GPU
curl -s --max-time 300 "http://127.0.0.1:${PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"messages\": [{
      \"role\": \"user\",
      \"content\": \"PRODUCE A HANDOFF DOCUMENT. You are moving to a GPU with only ${TARGET_CTX} tokens of context. Summarize EVERYTHING into a dense document under ${MAX_TOKENS} tokens. Include:\\n\\n1. CURRENT STATE: What you were doing, what's in progress\\n2. BUGS FOUND: Every bug identified, its location (file:line), root cause\\n3. FIXES APPLIED: What code changed, git diff summaries\\n4. FILES READ: Every file read and what you learned\\n5. DECISIONS MADE: Architectural choices, trade-offs\\n6. NEXT STEPS: Prioritized list of exactly what to do next\\n7. VRAM STATE: Current GPU usage on both GPUs\\n8. MODELS: What's deployed, where, restart commands\\n\\nBe dense. No fluff. Every token counts.\"
    }],
    \"max_tokens\": ${MAX_TOKENS},
    \"temperature\": 0.3
  }" | python3 -c "
import sys, json
r = json.load(sys.stdin)
content = r['choices'][0]['message'].get('content','') or r['choices'][0]['message'].get('reasoning_content','')
if not content.strip():
    print('ERROR: Empty handoff. Server may be busy or dead.')
    sys.exit(1)
with open('${HANDOFF_FILE}', 'w') as f:
    f.write(content)
print(f'Saved {len(content.split())} words to ${HANDOFF_FILE}')
print('')
print(content)
"

echo ""
echo "To resume: cat $HANDOFF_FILE | paste into fresh architect session"
