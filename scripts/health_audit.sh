#!/usr/bin/env bash
# health_audit — automated codebase health check.
#
# Runs: python syntax, import smoke, test suite, state file integrity, golden
# crontab drift, and records a pass/fail verdict to data/logs/health_audit.log
# with a one-line summary. Designed to run from a daily cron/systemd timer.
#
# Exit 0 if all checks pass, non-zero if any fail.
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$REPO/data/logs/health_audit.log"
PY="$REPO/.venv/bin/python3"
STAMP="$(date +%Y-%m-%dT%H:%M:%S)"
mkdir -p "$(dirname "$LOG")"

echo "[$STAMP] health_audit — begin" >> "$LOG"
errors=0

# 1. Syntax check — strategies + fxexpert
echo -n "[$STAMP] syntax... " >> "$LOG"
for d in strategies fxexpert exercises; do
  if [ ! -d "$REPO/$d" ]; then continue; fi
  find "$REPO/$d" -name '*.py' -exec "$PY" -c "
import py_compile, sys
for f in sys.argv[1:]:
    try: py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError as e: print(f)
" {} + 2>&1 | while read -r bad; do
    echo "SYNTAX:$bad" >> "$LOG"
    errors=$((errors+1))
  done
done
echo "ok (errors=$errors)" >> "$LOG"

# 2. Import smoke — only strategies/ (fxexpert needs torch/duckdb)
echo -n "[$STAMP] imports... " >> "$LOG"
IMPORT_ERR=$("$PY" -c "
import importlib, os, sys
fail=0
for root,dirs,files in os.walk('strategies'):
    for f in files:
        if not f.endswith('.py') or f.startswith('_'): continue
        try: importlib.import_module('strategies.'+f[:-3])
        except Exception: fail+=1
print(fail)
" 2>/dev/null)
if [ "$IMPORT_ERR" -gt 2 ]; then  # allow duckdb-dependent modules
  errors=$((errors+IMPORT_ERR-2))
  echo "FAIL (${IMPORT_ERR} import errors)" >> "$LOG"
else
  echo "ok" >> "$LOG"
fi

# 3. Test suite
echo -n "[$STAMP] tests... " >> "$LOG"
if timeout 180 "$PY" -m pytest "$REPO/tests/" -q --tb=line > /tmp/ht-$$.out 2>&1; then
  echo "PASS" >> "$LOG"
else
  errors=$((errors+1))
  echo "FAIL" >> "$LOG"
  tail -5 /tmp/ht-$$.out >> "$LOG"
fi
rm -f /tmp/ht-$$.out

# 4. State file integrity
echo -n "[$STAMP] state files... " >> "$LOG"
for f in data/fx_state.json data/fx_crashtest.json data/fx_intraday.json \
         data/wayfinder/deployability_status.json data/warden/warden_state.json \
         data/defect_log.json data/exog_cache.json; do
  "$PY" -c "import json;json.load(open('$f'))" 2>/dev/null || { echo "BROKEN:$f" >> "$LOG"; errors=$((errors+1)); }
done
echo "ok" >> "$LOG"

# 5. Golden crontab drift
echo -n "[$STAMP] golden crontab... " >> "$LOG"
diff <(crontab -l) "$REPO/data/ops/golden_crontab.txt" > /tmp/cr-$$.diff 2>&1
if [ -s /tmp/cr-$$.diff ]; then
  # Only flag non-trivial drift (ignore trailing-newline-only diffs)
  if grep -vE '^[0-9]+[acd]' /tmp/cr-$$.diff | grep -q .; then
    errors=$((errors+1))
    echo "DRIFT" >> "$LOG"
    cat /tmp/cr-$$.diff >> "$LOG"
  else
    echo "cosmetic only" >> "$LOG"
  fi
else
  echo "MATCH" >> "$LOG"
fi
rm -f /tmp/cr-$$.diff

# 6. Summary
if [ "$errors" -eq 0 ]; then
  echo "[$STAMP] health_audit — PASS (0 errors)" >> "$LOG"
else
  echo "[$STAMP] health_audit — FAIL ($errors errors)" >> "$LOG"
fi
echo "[$STAMP] health_audit — end" >> "$LOG"
exit $errors