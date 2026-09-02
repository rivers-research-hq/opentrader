#!/bin/bash
# Install and enable OpenTrader systemd services

set -e

# Copy service files
mkdir -p /etc/systemd/system
cp /home/mrc/opentrader/opentrader-llama.service /etc/systemd/system/
cp /home/mrc/opentrader/opentrader-harness.service /etc/systemd/system/
cp /home/mrc/opentrader/opentrader-dashboard.service /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable and start all services
systemctl enable opentrader-llama.service
systemctl enable opentrader-harness.service
systemctl enable opentrader-dashboard.service

systemctl start opentrader-llama.service
systemctl start opentrader-harness.service
systemctl start opentrader-dashboard.service

# Show status of all services
systemctl status opentrader-llama.service opentrader-harness.service opentrader-dashboard.service
