#!/usr/bin/env bash
# local_validate — the acceptance gate for a local worker.
# A model is not "up" until this writes a passing artifact (AGENTS.md rule:
# every job must name a recent artifact it produced).
#
#   scripts/local_validate.sh <model-name> [port]
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?usage: local_validate.sh <model-name> [port] [served_ctx]}"
PORT="${2:-5808}"
CTX="${3:-65536}"
# never ask for more context than the server holds: the long probe is
# capped at 80%% of served ctx (recorded in the artifact)
LONG=$(( CTX * 8 / 10 )); [ "$LONG" -gt 70000 ] && LONG=70000
URL="http://127.0.0.1:${PORT}/v1/chat/completions"
OUT="$REPO/data/local/$NAME"; mkdir -p "$OUT"
STAMP="$(date +%Y-%m-%dT%H:%M:%S)"
echo "[validate] $NAME on :$PORT -> $OUT"

curl -s -m 10 "http://127.0.0.1:${PORT}/v1/models" | grep -q '"id"' \
  || { echo "[validate] FAIL: server not answering on $PORT"; echo "{\"model\":\"$NAME\",\"ts\":\"$STAMP\",\"verdict\":\"FAIL\",\"reason\":\"server down\"}" > "$OUT/validate.json"; exit 1; }
echo "[validate] server up"

QWEN_EVAL_URL="$URL" "$REPO/.venv/bin/python3" "$HOME/qwen38-eval/eval.py" > "$OUT/eval.txt" 2>&1
# grep -c prints the count even when it exits 1 (no matches), so do not append
# `|| echo 0` — that emits "0\n0" and breaks the integer test below.
PASS=$(grep -c '^\[PASS\]' "$OUT/eval.txt" 2>/dev/null); PASS=${PASS:-0}
FAIL=$(grep -c '^\[FAIL\]' "$OUT/eval.txt" 2>/dev/null); FAIL=${FAIL:-0}
echo "[validate] eval suite: $PASS pass / $FAIL fail"

"$REPO/.venv/bin/python3" "$REPO/scripts/needle_test.py" --url "$URL" --target-tokens 8000  --label short > "$OUT/needle-short.json" 2>&1
"$REPO/.venv/bin/python3" "$REPO/scripts/needle_test.py" --url "$URL" --target-tokens "$LONG" --label long  > "$OUT/needle-long.json" 2>&1

# A crashed/timed-out eval suite emits zero verdict lines. Treat that as its own
# verdict, not as "0 pass" — otherwise an instrument failure reads as a bad model
# (the exact confusion this gate exists to prevent).
TOTAL=$((PASS + FAIL))
if [ "$TOTAL" -eq 0 ]; then
  VERDICT=ERROR
elif [ "$FAIL" -eq 0 ] && [ "$PASS" -ge 30 ]; then
  VERDICT=PASS
else
  VERDICT=FAIL
fi
# Build validate.json in python. The old shell heredoc embedded a quoted grep
# capture inside a JSON string ("needle_short":""recall": "10/10""), so the
# artifact was unparseable — the same broken-instrument class this gate exists
# to catch.
"$REPO/.venv/bin/python3" - "$OUT" "$NAME" "$STAMP" "$PORT" "$CTX" "$LONG" "$VERDICT" "$PASS" "$FAIL" <<'PY'
import json, pathlib, sys
out, name, stamp, port, ctx, long_tok, verdict, passed, failed = sys.argv[1:10]

def recall(fn):
    """needle_test.py writes one JSON object, possibly among other text."""
    text = pathlib.Path(out, fn).read_text(errors="replace")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "recall" in obj:
            return obj["recall"]
    return None

doc = {"model": name, "ts": stamp, "port": int(port), "served_ctx": int(ctx),
       "needle_long_target_tokens": int(long_tok), "verdict": verdict,
       "eval_pass": int(passed), "eval_fail": int(failed),
       "needle_short": recall("needle-short.json"),
       "needle_long": recall("needle-long.json")}
pathlib.Path(out, "validate.json").write_text(json.dumps(doc, indent=1) + "\n")
print(json.dumps(doc))
PY
echo "[validate] $NAME -> $VERDICT ($PASS pass, $FAIL fail)"; cat "$OUT/validate.json"
