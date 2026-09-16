#!/usr/bin/env bash
# local_coder — the local coding workhorse (Qwen3-Coder-30B-A3B UD-Q5_K_XL, llama.cpp :5808).
#
# Puts the repo venv first on PATH so `python3`, `pip` and `pytest` resolve to the
# project's own environment. Without this the model finds a pytest-less interpreter,
# tries to `pip install pytest`, never sees the real test output, and invents a
# result — the failure that made the first benchmark run useless.
#
# After the model replies, the output is piped through `scripts/local_coder_verify.py`
# which re-runs the PROOF commands the model reported and checks them against actual
# file-system state. If the model claimed "tests pass" but they do not, the run is
# rejected. This is how we catch fabrication.
#
#   scripts/local_coder.sh "<task>"                  # fresh session, run a task
#   scripts/local_coder.sh --dir <path> "<task>"     # run against a specific tree
#   scripts/local_coder.sh --title foo "<task>"      # label the session
#
# Fresh session every call (no -c/-s), so no context leaks between tasks.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$REPO/.venv/bin:$PATH"
export PYTHONDONTWRITEBYTECODE=1

TMPOUT=$(mktemp /tmp/coder-XXXXXX.out)
trap 'rm -f "$TMPOUT"' EXIT

VERIFIER="$REPO/.venv/bin/python3 $REPO/scripts/local_coder_verify.py"

opencode run \
  --agent local-coder \
  --model "${LOCAL_CODER_MODEL:-local-worker/qwen3-coder-30b-a3b-ud}" \
  --auto \
  "$@" 2>&1 | tee "$TMPOUT"
RC=${PIPESTATUS[0]}

echo ""
echo "--- verification ---"
if "$REPO/.venv/bin/python3" "$REPO/scripts/local_coder_verify.py" < "$TMPOUT"; then
  echo "Result: accepted (proofs re-derived)"
else
  echo "Result: REJECTED (proofs did not match actual output)"
  RC=1
fi
exit $RC