#!/usr/bin/env python3
"""Unit tests for the FTMO prop entry gate (setup_search/prop_entry_gate.py)."""
from __future__ import annotations

import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from setup_search.prop_entry_gate import entry_allowed, _events_utc, HIGH_IMPACT_2026

FAILS = []


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name}: {detail}")
    else:
        print(f"  PASS {name}")


def main():
    print("[prop-gate]")
    # 1. normal Wednesday mid-day passes
    ok, why = entry_allowed(datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc), "fx")
    check("wednesday passes", ok, why)
    # 2. Friday within 2h of the close is blocked
    ok, why = entry_allowed(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc), "fx")
    check("friday close window blocked", not ok, why)
    # 3. weekend blocked
    ok, why = entry_allowed(datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc), "fx")
    check("saturday blocked", not ok, why)
    # 4. news window: 3 minutes before a scheduled event is blocked
    events = _events_utc(2026, HIGH_IMPACT_2026)
    fomc = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    ok, why = entry_allowed(fomc - __import__("datetime").timedelta(minutes=3), "fx", events)
    check("3min before FOMC blocked", not ok, why)
    # 5. 20 minutes after the same event passes (outside the 5-min window)
    ok, why = entry_allowed(fomc + __import__("datetime").timedelta(minutes=20), "fx", events)
    check("20min after FOMC passes", ok, why)
    # 6. equities market: Friday close window does not apply
    ok, why = entry_allowed(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc), "eq")
    check("equities ignore FX close", ok, why)
    # 7. naive datetime is treated as UTC
    ok, why = entry_allowed(datetime(2026, 8, 5, 12, 0))
    check("naive dt treated as UTC", ok, why)

    print(f"\n=== {len(FAILS)} failures ===")
    for f in FAILS:
        print(f"  FAIL {f}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
