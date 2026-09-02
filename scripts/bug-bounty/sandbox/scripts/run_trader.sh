#!/usr/bin/env bash
# run_trader.sh — Start all OpenTrader services
# Usage: ./scripts/run_trader.sh [options]
#   --mcp-port PORT    MCP server port (default: 8092)
#   --dash-port PORT   Dashboard port (default: 8091)
#   --state-dir DIR    State directory (default: ./data)
#   --no-dashboard     Don't start the dashboard
#   --no-mcp           Don't start the MCP server
#   --agent NAME       Agent type (default: heuristic)

set -euo pipefail
cd "$(dirname "$0")/.."

MCP_PORT=${MCP_PORT:-8092}
DASH_PORT=${DASH_PORT:-8095}
STATE_DIR=${STATE_DIR:-"./data"}
AGENT=${AGENT:-heuristic}
NO_DASH=false
NO_MCP=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mcp-port) MCP_PORT="$2"; shift 2 ;;
        --dash-port) DASH_PORT="$2"; shift 2 ;;
        --state-dir) STATE_DIR="$2"; shift 2 ;;
        --no-dashboard) NO_DASH=true; shift ;;
        --no-mcp) NO_MCP=true; shift ;;
        --agent) AGENT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$STATE_DIR"

cleanup() {
    echo ""
    echo "Shutting down OpenTrader..."
    kill $MCP_PID $DASH_PID 2>/dev/null || true
    wait 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

echo "╔══════════════════════════════════════════╗"
echo "║        ◈ OpenTrader — Launcher          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Start MCP server
if ! $NO_MCP; then
    echo "[1/2] Starting MCP server on port $MCP_PORT..."
    python mcp_server.py --port "$MCP_PORT" --state-dir "$STATE_DIR" --log-level INFO &
    MCP_PID=$!
    sleep 1
    # Quick health check
    if curl -sf "http://localhost:$MCP_PORT/api/health" > /dev/null 2>&1; then
        echo "      ✓ MCP server ready (PID $MCP_PID)"
    else
        echo "      ⚠ MCP server starting..."
    fi
fi

# Start Dashboard
if ! $NO_DASH; then
    echo "[2/2] Starting Dashboard on port $DASH_PORT..."
    python dashboard.py --port "$DASH_PORT" --state-dir "$STATE_DIR" --log-level INFO &
    DASH_PID=$!
    sleep 1
    if curl -sf "http://localhost:$DASH_PORT/api/dashboard/summary" > /dev/null 2>&1; then
        echo "      ✓ Dashboard ready (PID $DASH_PID)"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MCP Server:    http://localhost:$MCP_PORT"
echo "  REST API:      http://localhost:$MCP_PORT/api/health"
echo "  Dashboard:     http://localhost:$DASH_PORT"
echo "  State Dir:     $STATE_DIR"
echo "  Agent:         $AGENT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Run the harness separately:"
echo "  python harness.py --agent $AGENT --bars 200 --max-cycles 50"
echo ""
echo "Press Ctrl+C to stop all services."
echo ""

# Wait for any child to exit
wait
