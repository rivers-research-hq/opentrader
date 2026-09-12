#!/usr/bin/env python3
"""Tests for the 2026-09-12 gate re-specification (eligibility, not promotion).

The old bar (PF >= 1.05 as a promotion gate) was retired because the
population study showed PF/Sharpe/mean-return are one statistic that does not
persist across periods. The gate now certifies coherence only. These tests pin
the decision rule so a future edit cannot quietly turn it back into a
performance bar.

Run as a script:  .venv/bin/python3 tests/test_gate_eligibility.py
Run under pytest: .venv/bin/python3 -m pytest tests/test_gate_eligibility.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402

OUT = REPO / "data" / "fx_expert"


def test_criteria_are_coherence_not_performance():
    g = fxgate.GATE
    assert g["ic_min"] == 0.0            # signal positive
    assert g["mean_bps_min"] == 0.0      # book not losing after costs
    assert g["folds_positive_min"] == 2
    assert "pf_min" in g                 # kept for callers, but…
    assert g["pf_min"] == g["pf_reported_only"], \
        "pf_min must not be a separate performance threshold any more"


def test_recorded_generations_judged_consistently():
    """A past run's verdict must follow the criteria, not the verdict at the
    time. g206 lost money after costs -> NOT ELIGIBLE; g185 was profitable."""
    import json
    for tag, expect in (("185", "ELIGIBLE"), ("206", "NOT ELIGIBLE")):
        if not (OUT / f"preds_g{tag}.npz").exists():
            continue
        r = fxgate.evaluate(tag, write=False)
        assert r["gate"]["verdict"] == expect, (tag, r["gate"])
        assert r["gate"]["promotion"].startswith("forward shadow accrual")


def test_write_false_leaves_recorded_verdict_untouched():
    p = OUT / "gate_g185.json"
    if not p.exists():
        return
    before = p.read_bytes()
    fxgate.evaluate("185", write=False)
    assert p.read_bytes() == before, "audit mode must not rewrite run-time history"


def test_eligibility_reasons_fire_on_a_losing_book():
    """Synthetic check of the rule shape: negative net mean -> reason."""
    r = fxgate.evaluate("206", write=False) if (OUT / "preds_g206.npz").exists() else None
    if r is None:
        return
    assert any("net mean" in x for x in r["gate"]["reasons"])


def test_no_pf_threshold_in_the_verdict():
    """A profitable-but-low-PF book must still be eligible: PF is reported
    only. g201 has PF 1.0225 (< the old 1.05 bar) and is eligible."""
    if not (OUT / "preds_g201.npz").exists():
        return
    r = fxgate.evaluate("201", write=False)
    assert r["model"]["pf"] < 1.05
    assert r["gate"]["verdict"] == "ELIGIBLE"
    assert not any("pf " in x for x in r["gate"]["reasons"])


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all gate-eligibility tests passed")
