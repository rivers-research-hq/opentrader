#!/usr/bin/env python3
"""FTMO prop-leg entry gate (ADR-0005 operational constraints, sandbox-ready).

Encodes the verified FTMO 2-Step ruleset's entry restrictions so the prop leg
never opens a position in a banned window:

1. No entries within +/- 5 minutes of high-impact news (FOMC, NFP, CPI, PCE,
   GDP, unemployment, retail sales — the scheduled US events).
2. No entries within 2 hours of a relevant market closing for >= 2 hours
   (practically: the FX weekend close — Friday ~17:00 ET).

Design notes:
- The event schedule below is a 2026 APPROXIMATION (documented as such). The
  prop leg must wire a live economic-calendar feed (e.g. finnhub calendar /
  investing.com) before it goes live — the gate accepts an `events` override.
- Standalone + testable; NOT wired into the live harness yet (ADR-0001: no
  silent strategy changes). Wiring point when the prop leg starts: call
  entry_allowed() inside _rule_gate_ok before any BUY is emitted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Approximate 2026 scheduled high-impact US events: (month, day, hour_utc).
# FOMC: 2026 meeting statement days ~ Jan 27, Mar 17, Apr 28, Jun 16, Jul 28,
# Sep 15, Oct 27, Dec 8 (14:00 ET = 19:00 UTC). NFP: first Friday 08:30 ET.
# CPI: ~10-14th 08:30 ET. PCE: ~end-of-month 08:30 ET. GDP: ~last week 08:30 ET.
# Approximation only — the live calendar feed replaces this before the prop
# leg trades real challenge accounts.
HIGH_IMPACT_2026 = [
    # (month, day, hour_utc)
    (1, 27, 19), (3, 17, 19), (4, 28, 19), (6, 16, 19),
    (7, 28, 19), (9, 15, 19), (10, 27, 19), (12, 8, 19),  # FOMC
    (1, 2, 13), (2, 6, 13), (3, 6, 13), (4, 3, 13), (5, 1, 13),
    (6, 5, 13), (7, 2, 13), (8, 7, 13), (9, 4, 13), (10, 2, 13),
    (11, 6, 13), (12, 4, 13),                              # NFP first Fridays
    (1, 13, 13), (2, 10, 13), (3, 10, 13), (4, 10, 13), (5, 12, 13),
    (6, 10, 13), (7, 14, 13), (8, 12, 13), (9, 11, 13), (10, 13, 13),
    (11, 10, 13), (12, 10, 13),                            # CPI
]

NEWS_WINDOW_MIN = 5       # +/- 5 minutes around a high-impact event
CLOSE_WINDOW_H = 2        # no entries within 2h of a >=2h close
FX_CLOSE_DAY = 4          # Friday (weekday 4)
FX_CLOSE_HOUR_ET = 17     # 17:00 ET ~ 21:00 UTC (EDT) / 22:00 UTC (EST)


def _events_utc(year: int, table: list) -> list:
    """(month, day, hour_utc) -> aware datetimes for the year."""
    out = []
    for m, d, h in table:
        try:
            out.append(datetime(year, m, d, h, tzinfo=timezone.utc))
        except ValueError:
            continue
    return out


def entry_allowed(dt_utc: datetime, market: str = "fx",
                  events: list | None = None) -> tuple:
    """Is an entry allowed at dt_utc? Returns (allowed, reason).

    market 'fx' applies the weekend-close window; 'eq' (equities) skips it.
    events: list of aware datetimes of high-impact events (default: the
    approximate 2026 table, valid for that calendar year).
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    if events is None:
        events = _events_utc(dt_utc.year, HIGH_IMPACT_2026)

    # 1. high-impact news window
    for ev in events:
        if abs((dt_utc - ev).total_seconds()) <= NEWS_WINDOW_MIN * 60:
            return False, f"within {NEWS_WINDOW_MIN}min of high-impact news at {ev:%H:%M} UTC"
        if ev > dt_utc and (ev - dt_utc).total_seconds() <= NEWS_WINDOW_MIN * 60:
            return False, f"high-impact news in <{NEWS_WINDOW_MIN}min"

    # 2. market-close window (FX weekend)
    if market == "fx":
        wd = dt_utc.weekday()
        # close = Friday 17:00 ET; approximate ET offset: UTC-4 (EDT) Mar-Nov
        hour_et = dt_utc.hour - 4 if dt_utc.month in range(3, 12) else dt_utc.hour - 5
        if wd == FX_CLOSE_DAY and hour_et >= FX_CLOSE_HOUR_ET - CLOSE_WINDOW_H:
            return False, "within 2h of the FX weekend close (Friday)"
        if wd >= 5:  # Sat/Sun
            return False, "market closed (weekend)"
    return True, "ok"


if __name__ == "__main__":
    # quick self-check: a normal Wednesday passes; Friday 16:00 ET blocked
    wed = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    fri = datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)  # Fri 16:00 ET
    print("wed:", entry_allowed(wed))
    print("fri:", entry_allowed(fri))
