#!/usr/bin/env bash
# local_sweep — run a list of candidate configs sequentially on the GRE.
#
# The GRE holds one model at a time, so candidates are serialised: for each row
# it launches the candidate on the scratch port, benches it, runs the acceptance
# gate, then tears down. Results land in data/local/<name>/.
#
#   scripts/local_sweep.sh <planfile>
#
# Planfile: tab-separated, '#' comments allowed. Columns:
#   name  model  ctx  n-cpu-moe  kv  draft  draft_n_max  extra_flags
# Leave draft empty for none; extra_flags is passed through to llama-server.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLAN="${1:?usage: local_sweep.sh <planfile>}"
[ -f "$PLAN" ] || { echo "no such plan: $PLAN"; exit 1; }

while IFS=$'\t' read -r name model ctx ncmoe kv draft dnmax extra; do
  case "$name" in ''|'#'*) continue;; esac
  echo "=================== $(date +%H:%M:%S) $name ==================="
  args=(--ctx "$ctx" --n-cpu-moe "$ncmoe" --kv "$kv")
  [ -n "$draft" ] && args+=(--draft "$draft" --draft-n-max "${dnmax:-3}")
  # shellcheck disable=SC2086
  scripts/local_candidate.sh "$name" "$model" "${args[@]}" -- $extra
  rc=$?
  if [ $rc -ne 0 ]; then echo "[sweep] $name FAILED TO START (rc=$rc)"; continue; fi
  .venv/bin/python3 scripts/llama_bench.py --label "$name" --url "http://127.0.0.1:5809/v1/chat/completions" \
    --gen 200 > "data/local/$name/bench.json" 2>&1
  scripts/local_validate.sh "$name" 5809 "$ctx" > "data/local/$name/gate.log" 2>&1
  echo "[sweep] $name verdict: $( .venv/bin/python3 -c "import json;print(json.load(open('data/local/$name/validate.json'))['verdict'])" 2>/dev/null || echo UNKNOWN )"
  scripts/local_candidate_stop.sh "$name"
  echo
done < "$PLAN"
echo "[sweep] done"