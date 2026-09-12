#!/usr/bin/env python3
"""Unit tests for the accrual-store journal monotonicity guard.

The 2026-09-11 truncation defect: the OANDA sinceid walk stopped at the first
1000 transactions (the endpoint has no `pages` field), so the store looked
healthy while hiding ~75% of the journal. The guard makes a shrinking journal
a hard failure on rebuild.

Run as a script:  .venv/bin/python3 tests/test_accrual_journal_guard.py
Run under pytest: .venv/bin/python3 -m pytest tests/test_accrual_journal_guard.py -v
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "bas", REPO / "scripts" / "build_accrual_store.py")
bas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bas)


def test_growth_is_allowed():
    assert bas.journal_shrink_guard({"txns": 1000, "fills": 315},
                                    {"txns": 4104, "fills": 1591}) is None


def test_equal_counts_allowed():
    assert bas.journal_shrink_guard({"txns": 4104, "fills": 1591},
                                    {"txns": 4104, "fills": 1591}) is None


def test_shrinking_txns_refused():
    err = bas.journal_shrink_guard({"txns": 4104, "fills": 1591},
                                   {"txns": 1000, "fills": 315})
    assert err and "txns shrank" in err


def test_shrinking_fills_refused_even_when_txns_grow():
    err = bas.journal_shrink_guard({"txns": 4104, "fills": 1591},
                                   {"txns": 5000, "fills": 1500})
    assert err and "fills shrank" in err


def test_first_build_without_manifest_is_allowed():
    assert bas.journal_shrink_guard({}, {"txns": 4104, "fills": 1591}) is None


def test_skip_venue_rebuild_is_exempt():
    """--skip-venue intentionally keeps zero venue rows; it must not trip."""
    assert bas.journal_shrink_guard({"txns": 4104, "fills": 1591},
                                    {"txns": 0, "fills": 0},
                                    skip_venue=True) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all journal-guard tests passed")