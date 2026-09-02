#!/bin/bash
# Install OpenTrader systemd USER units (no root needed)
# Usage: bash scripts/install-systemd-user.sh
set -e

UNIT_DIR="$HOME/.config/systemd/user"
SRC="/home/mrc/opentrader/scripts/systemd"

mkdir -p "$UNIT_DIR"
cp "$SRC"/opentrader-*.service "$UNIT_DIR"/

systemctl --user daemon-reload

systemctl --user enable opentrader-llama-gpu1.service
systemctl --user enable opentrader-llama-gpu0.service
systemctl --user enable opentrader-gpu-sync.service
systemctl --user enable opentrader-mcp-server.service
systemctl --user enable opentrader-harness.service
systemctl --user enable opentrader-dashboard.service
systemctl --user enable opentrader-codesage.service

echo "Units installed and enabled. Enable linger so they start at boot:"
echo "  loginctl enable-linger mrc   (requires sudo once)"
