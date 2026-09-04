#!/usr/bin/env bash
# OpenTrader health check.
# Exits 0 when healthy, 1 when a critical check fails or a monitored service is down.
#
# CRITICAL (trading is broken):
#   - harness systemd unit not active
#   - circuit breaker tripped in the last 5 min
#   - harness hung (paper_state.json not rewritten in 300s)
#   - LLM backend :5801 unreachable (harness depends on it)
# WARNING (degraded, trading may continue):
#   - dashboard :8097 down
#   - MCP :8092 down
# INFO (never fails — research model servers may be intentionally stopped):
#   - :5804 / :5802 / :5810
set -u

STATE=/home/mrc/opentrader/data/paper_state.json
CRIT=0
WARN=0

pass() { printf '  [ok]   %s\n' "$*"; }
crit() { printf '  [CRIT] %s\n' "$*"; CRIT=1; }
warn() { printf '  [WARN] %s\n' "$*"; WARN=1; }
info() { printf '  [info] %s\n' "$*"; }

# HTTP status for a localhost port; 000 (or empty) = unreachable.
probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:$1/" 2>/dev/null || true; }

echo "OpenTrader health $(date -u '+%Y-%m-%d %H:%M:%SZ')"

# 1. Harness active
st=$(systemctl --user is-active opentrader-harness.service 2>/dev/null || true)
if [ "$st" = "active" ]; then pass "harness active"; else crit "harness NOT active (systemd state: ${st:-unknown})"; fi

# 2. Circuit breaker clear (last 5 min)
if journalctl --user -u opentrader-harness.service --since "5 min ago" --no-pager 2>/dev/null | grep -q "Circuit breaker tripped"; then
  crit "circuit breaker tripped in last 5 min"
else
  pass "circuit breaker clear (5m)"
fi

# 3. Harness cycling (state file rewritten recently)
if [ -f "$STATE" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$STATE") ))
  if [ "$age" -lt 300 ]; then pass "state fresh (${age}s old)"; else crit "state STALE (${age}s old) - harness may be hung"; fi
else
  crit "paper_state.json missing"
fi

# 4. LLM backend :5801 (harness depends on it)
c=$(probe 5801)
if [ -n "$c" ] && [ "$c" != "000" ]; then pass "llm backend :5801 up (http $c)"; else crit "llm backend :5801 UNREACHABLE"; fi

# 5. Dashboard :8097
c=$(probe 8097)
if [ "$c" = "200" ]; then pass "dashboard :8097 (200)"; else warn "dashboard :8097 down (http ${c:-000})"; fi

# 6. MCP :8092
c=$(probe 8092)
if [ -n "$c" ] && [ "$c" != "000" ]; then pass "mcp :8092 up (http $c)"; else warn "mcp :8092 down (http ${c:-000})"; fi

# 7. Research model servers (info only)
for p in 5804 5802 5810; do
  c=$(probe "$p")
  if [ -n "$c" ] && [ "$c" != "000" ]; then info "model :$p up"; else info "model :$p down"; fi
done

if [ "$CRIT" -ne 0 ]; then
  echo "RESULT: UNHEALTHY (critical)"
  exit 1
elif [ "$WARN" -ne 0 ]; then
  echo "RESULT: DEGRADED (warning)"
  exit 1
else
  echo "RESULT: HEALTHY"
  exit 0
fi
