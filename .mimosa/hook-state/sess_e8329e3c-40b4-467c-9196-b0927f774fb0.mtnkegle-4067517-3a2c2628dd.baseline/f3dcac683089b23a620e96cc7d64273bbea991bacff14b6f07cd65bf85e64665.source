#!/bin/bash
# Quick restart: sudo systemctl restart opentrader-llama && sleep 15 && sudo systemctl restart opentrader-harness opentrader-dashboard

set -e

sudo systemctl restart opentrader-llama.service
sleep 15
sudo systemctl restart opentrader-harness.service
sudo systemctl restart opentrader-dashboard.service
