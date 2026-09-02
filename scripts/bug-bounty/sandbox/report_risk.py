#!/usr/bin/env python3
"""Quick risk/exposure summary from the latest cycle state."""
import json, os, sys
from pathlib import Path

HISTORY = Path("/home/mrc/opentrader/data/history")
files = sorted(HISTORY.glob("cycle_*.json"), key=os.path.getmtime, reverse=True)
if not files:
    print("  (no state files)")
    sys.exit(0)

with open(files[0]) as f:
    s = json.load(f)

tv = s.get("total_value", s.get("portfolio_value", 100000))
cash = s.get("cash", tv)
raw_pos = s.get("positions", {})
if isinstance(raw_pos, list):
    pos = {p["symbol"]: p for p in raw_pos if isinstance(p, dict)}
else:
    pos = raw_pos
invested = tv - cash
exposure = invested / max(tv, 1) * 100

print(f"  Exposure:      {exposure:.1f}% (${invested:,.2f} invested)")
print(f"  Cash Reserve:  ${cash:,.2f}")

# Drawdown from equity curve
eq = s.get("equity_curve", [])
if eq:
    peak = max(eq)
    trough = min(eq)
    dd = (peak - trough) / peak * 100 if peak > 0 else 0
    print(f"  Max Drawdown:  {dd:.2f}%")

# Signal accuracy
metrics = s.get("metrics", {})
acc = metrics.get("signal_accuracy", {})
if isinstance(acc, dict) and acc.get("total", 0) > 0:
    pct = acc.get("correct", 0) / acc["total"] * 100
    print(f"  Accuracy:      {pct:.1f}% ({acc['correct']}/{acc['total']})")

# MoT stage
stage = s.get("models", {}).get("stage", s.get("metrics", {}).get("stage", "?"))
print(f"  Stage:         {stage}")

# Alerts
alerts = s.get("alerts", [])
if alerts:
    print(f"  Alerts:        {len(alerts)}")
    for a in alerts[-3:]:
        print(f"    [{a.get('type','?')}] {a.get('message','')}")
