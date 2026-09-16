#!/usr/bin/env bash
# local_candidate_stop — tear down a server started by scripts/local_candidate.sh.
#   scripts/local_candidate_stop.sh <name>
set -uo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NAME="${1:?usage: local_candidate_stop.sh <name>}"
PIDFILE="$REPO/data/local/$NAME/server.pid"
if [ ! -f "$PIDFILE" ]; then echo "[stop] no pidfile for $NAME"; exit 0; fi
PID="$(cat "$PIDFILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for i in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  kill -0 "$PID" 2>/dev/null && { echo "[stop] SIGKILL $PID"; kill -9 "$PID"; }
  echo "[stop] $NAME (pid $PID) stopped"
else
  echo "[stop] $NAME (pid $PID) already gone"
fi
rm -f "$PIDFILE"