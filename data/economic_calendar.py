#!/usr/bin/env python3
"""In-house economic calendar — release schedule model for the US + major
global markets.

WHY: economic releases (FOMC, CPI, NFP, GDP, PMI) create predictable
volatility/regime shifts. A strategy that knows "CPI lands in 2 days" or
"we're inside the FOMC window" can time entries around them. This is a
calendar-DRIVEN signal (scheduled events), distinct from the daily FRED/VIX
state and the annual World Bank context.

Design:
  - Rules model the recurring annual schedule (Fed 8 FOMC meetings/year on
    published dates; CPI/NFP/GDP/PMI on fixed rules like "first Friday").
  - `releases_between(start, end)` -> list of (date, name, impact).
  - `next_release(date)`, `days_until_next(date)`, `days_since_last(date)`.
  - `release_density(window_days, date)` -> count of releases in the trailing
    window (a volatility-regime feature).
  - `release_proximity(date)` -> 0..1 feature, peaks near a release.

Honesty: scheduled dates are NOT certain (FOMC dates are pre-announced years
out; NFP can shift a day). We model the published/rule-based schedule; the
arena/strategies treat proximity as a soft signal, never a hard gate.

Sources (public, pre-announced): Federal Reserve FOMC meeting calendar
(federalreserve.gov, ~8/yr), BLS scheduled release calendar (CPI ~mid-month,
NFP ~first Friday, PPI ~mid-month), BEA (GDP advance ~late Apr/Jul/Oct/Jan),
S&P Global / ISM (PMI ~1st business day of month).
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class Release:
    date: dt.date
    name: str
    impact: str  # "high" | "med" | "low"


# FOMC meeting dates (pre-announced by the Fed). Years 2024-2027.
FOMC_DATES = {
    2024: [dt.date(2024, 1, 31), dt.date(2024, 3, 20), dt.date(2024, 5, 1),
           dt.date(2024, 6, 12), dt.date(2024, 7, 31), dt.date(2024, 9, 18),
           dt.date(2024, 11, 7), dt.date(2024, 12, 18)],
    2025: [dt.date(2025, 1, 29), dt.date(2025, 3, 19), dt.date(2025, 5, 7),
           dt.date(2025, 6, 18), dt.date(2025, 7, 30), dt.date(2025, 9, 17),
           dt.date(2025, 10, 29), dt.date(2025, 12, 10)],
    2026: [dt.date(2026, 1, 28), dt.date(2026, 3, 18), dt.date(2026, 4, 29),
           dt.date(2026, 6, 17), dt.date(2026, 7, 29), dt.date(2026, 9, 16),
           dt.date(2026, 10, 28), dt.date(2026, 12, 9)],
    2027: [dt.date(2027, 1, 27), dt.date(2027, 3, 17), dt.date(2027, 4, 28),
           dt.date(2027, 6, 16), dt.date(2027, 7, 28), dt.date(2027, 9, 15),
           dt.date(2027, 10, 27), dt.date(2027, 12, 15)],
}


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> dt.date:
    """Date of the nth `weekday` (0=Mon..6=Sun) of the month."""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    d = first + dt.timedelta(days=offset + (nth - 1) * 7)
    return d


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    offset = (weekday - last.weekday()) % 7
    return last - dt.timedelta(days=offset)


def _monthly_rules(year: int) -> List[Release]:
    out = []
    for m in range(1, 13):
        out.append(Release(_nth_weekday(year, m, 4, 1), "NFP (jobs report)", "high"))  # first Friday
        out.append(Release(dt.date(year, m, 13) if dt.date(year, m, 13).weekday() < 5
                           else _nth_weekday(year, m, 4, 1), "CPI", "high"))
        # CPI ~ 10th-15th; BLS publishes ~2nd or 3rd week. Model as ~13th.
        out.append(Release(dt.date(year, m, 1), "ISM Manufacturing PMI", "med"))
        out.append(Release(dt.date(year, m, 3), "ISM Services PMI", "med"))
        out.append(Release(_last_weekday(year, m, 4), "PCE Price Index", "med"))  # ~ last Fri
    return out


def _quarterly_rules(year: int) -> List[Release]:
    """BEA GDP advance estimate: ~late Jan/Apr/Jul/Oct."""
    return [
        Release(dt.date(year, 1, 30), "GDP advance Q4", "high"),
        Release(dt.date(year, 4, 28), "GDP advance Q1", "high"),
        Release(dt.date(year, 7, 30), "GDP advance Q2", "high"),
        Release(dt.date(year, 10, 30), "GDP advance Q3", "high"),
    ]


def releases_between(start: dt.date, end: dt.date) -> List[Release]:
    """All modeled releases in [start, end], sorted by date."""
    out = []
    for year in range(start.year - 1, end.year + 2):
        for d in FOMC_DATES.get(year, []):
            if start <= d <= end:
                out.append(Release(d, "FOMC decision", "high"))
        for r in _monthly_rules(year) + _quarterly_rules(year):
            if start <= r.date <= end:
                out.append(r)
    return sorted(out, key=lambda r: r.date)


def next_release(date: dt.date) -> Tuple[dt.date, str]:
    rel = releases_between(date, date + dt.timedelta(days=120))
    if not rel:
        return date + dt.timedelta(days=120), "none"
    r = rel[0]
    return r.date, r.name


def days_until_next(date: dt.date) -> int:
    d, _ = next_release(date)
    return (d - date).days


def days_since_last(date: dt.date) -> int:
    rel = releases_between(date - dt.timedelta(days=120), date)
    if not rel:
        return 120
    return (date - rel[-1].date).days


def release_density(date: dt.date, window_days: int = 14) -> int:
    """Number of releases in the trailing `window_days` before `date`."""
    rel = releases_between(date - dt.timedelta(days=window_days), date)
    return len(rel)


def release_proximity(date: dt.date, half_life_days: float = 3.0) -> float:
    """0..1 feature: high near a release, decays with half-life. Peak exactly
    on release day."""
    d, _ = next_release(date)
    days = (d - date).days
    return float(2.0 ** (-days / half_life_days))


# ── Central-bank decision gate (2026-09-01, ToC BM5) ──────────────────────
#
# The weekly-entry / daily-decision book is blind to scheduled monetary
# events between runs. blackout() blocks NEW entries for a pair when a
# decision for either currency's bank falls inside the exposure window.
#
# HONESTY: FOMC dates are exact (pre-announced). The other 7 banks are
# PATTERN-APPROXIMATE: anchored on their 2024 meeting rhythm and projected
# (one meeting every ~6-7 weeks, first meeting late January, snapped to the
# bank's weekday) — typical error grows from ±3 days (2025) to ±1-2 weeks
# (2027). Over-blocking (a missed entry) is cheap; under-blocking is the
# residual shock risk, covered by the watchdog lane. Replacing the
# approximations with fetched published schedules is the standing follow-up
# (ToC BM5).

_CURRENCY_BANK = {
    "USD": "FED", "EUR": "ECB", "GBP": "BOE", "JPY": "BOJ",
    "CHF": "SNB", "CAD": "BOC", "AUD": "RBA", "NZD": "RBNZ",
}

# (anchor date from the bank's 2024 rhythm, mean gap in weeks, weekday 0=Mon)
_CB_BANKS = {
    "ECB":  (dt.date(2024, 1, 25), 6.6, 3),   # Thursdays
    "BOE":  (dt.date(2024, 2, 1), 6.7, 3),    # Thursdays
    "BOC":  (dt.date(2024, 1, 24), 6.5, 2),   # Wednesdays
    "BOJ":  (dt.date(2024, 1, 23), 6.6, 2),   # ~Wednesdays
    "RBA":  (dt.date(2024, 2, 6), 7.2, 1),    # Tuesdays
    "RBNZ": (dt.date(2024, 2, 28), 6.0, 2),   # Wednesdays
    "SNB":  (dt.date(2024, 3, 21), 13.0, 3),  # quarterly Thursdays
}


def _snap_weekday(d: dt.date, weekday: int) -> dt.date:
    while d.weekday() != weekday:
        d += dt.timedelta(days=1)
    return d


def bank_dates(bank: str) -> set:
    """Decision dates for a bank, 2024-2027. FOMC = exact; others =
    pattern-approximate (see honesty note). Cached in the module."""
    cached = _CB_CACHE.get(bank)
    if cached is not None:
        return cached
    out: set = set()
    if bank == "FED":
        for year, dates in FOMC_DATES.items():
            out.update(dates)
    else:
        anchor, gap_weeks, weekday = _CB_BANKS[bank]
        d = anchor
        last_year = None
        while d.year <= 2027:
            # each NEW YEAR, restart the rhythm from a late-January meeting
            if last_year is not None and d.year > last_year:
                d = _snap_weekday(dt.date(d.year, 1, 22), weekday)
            out.add(d)
            last_year = d.year
            d = _snap_weekday(d + dt.timedelta(weeks=gap_weeks), weekday)
    _CB_CACHE[bank] = out
    return out


_CB_CACHE: dict = {}


def blackout(now: dt.datetime, pair: str, days: int = 1) -> Tuple[bool, str]:
    """Entry gate: True when a monetary decision for either currency of the
    pair falls within ±`days` of `now`'s date, or a high-impact US release
    within the same window for USD pairs. Decisions land mid-afternoon UTC —
    often AFTER the daily 17:10 UTC run — so the decision DAY itself blocks
    entries made that morning/afternoon."""
    check = {now.date() + dt.timedelta(o) for o in range(-days, days + 1)}
    reasons = []
    for cur in pair.split("_"):
        bank = _CURRENCY_BANK.get(cur)
        if bank and bank_dates(bank) & check:
            hit = sorted(bank_dates(bank) & check)[0]
            approx = "" if bank == "FED" else " (approx date)"
            reasons.append(f"{bank} decision {hit}{approx}")
    if "USD" in pair.split("_"):
        for r in releases_between(min(check), max(check)):
            if r.impact == "high" and "FOMC" not in r.name:
                reasons.append(f"US {r.name} {r.date}")
    if reasons:
        return True, "; ".join(reasons[:3])
    return False, ""


if __name__ == "__main__":
    today = dt.date(2026, 8, 14)
    print(f"today: {today}")
    nd, nn = next_release(today)
    print(f"next release: {nd} ({nn}), in {days_until_next(today)}d")
    print(f"last release: {days_since_last(today)}d ago")
    print(f"14d release density: {release_density(today)}")
    print(f"proximity feature: {release_proximity(today):.3f}")
    print("\nnext 10 releases:")
    for r in releases_between(today, today + dt.timedelta(days=90))[:10]:
        print(f"  {r.date} {r.name:28s} {r.impact}")
    print("\nblackout checks (gate semantics):")
    for pair in ("EUR_USD", "USD_JPY", "GBP_USD"):
        blocked, why = blackout(dt.datetime(2026, 9, 16, 17, 10, tzinfo=dt.timezone.utc), pair)
        print(f"  {pair} @ FOMC-day 2026-09-16 17:10 UTC: blocked={blocked} ({why})")


