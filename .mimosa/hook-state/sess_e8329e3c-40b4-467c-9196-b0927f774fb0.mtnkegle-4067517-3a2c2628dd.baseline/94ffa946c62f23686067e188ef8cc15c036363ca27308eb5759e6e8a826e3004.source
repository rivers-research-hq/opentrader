#!/usr/bin/env bash
# Launch the rule-based paper shadow alongside the LLM harness (A/B).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/shadow_aab
setsid nohup /home/mrc/rocm_venv/bin/python3 -u -m setup_search.shadow_live \
  --interval 1800 >> data/shadow_aab/shadow.log 2>&1 < /dev/null &
echo "shadow PID=$!"
