#!/usr/bin/env bash
# Chapter 1 reconcile script — run verbatim, paste output into ch01.md.
set -u
echo "=== opencode-server ==="
systemctl --user is-active opencode-server 2>&1
echo "=== hollama container ==="
docker ps -a --filter name=hollama --format '{{.Names}} {{.Status}} {{.Ports}}' 2>&1
echo "=== qwen38 health ==="
curl -s -m 5 http://127.0.0.1:5804/health 2>&1; echo
echo "=== qwen38 models ==="
curl -s -m 5 http://127.0.0.1:5804/v1/models 2>&1; echo
echo "=== tailscale serve ==="
tailscale serve status 2>&1
echo "=== listening ports ==="
ss -tlnp 2>/dev/null | grep -E ':(4096|4173|5804|5802)\b'
