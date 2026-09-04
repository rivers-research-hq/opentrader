#!/usr/bin/env python3
"""Epoch engine prototype (ADR-0006, ticket #84).

Continual learning = epoch-based experts: a new momentum value-head MLP
spawns per epoch, trained on the EXPANDING window of prior epochs' data
(rehearsal = replay of prior-epoch rows). Each epoch's expert must:

  (a) clear the +1% gate on its OWN epoch holdout (both adaptive windows,
      via the same discrimination as the arena gate),
  (b) retain prior-epoch edge: margin delta vs the previous epoch's expert
      on every prior holdout <= erosion bar (0.5% = half-gate),
  (c) beat the single-global-expert baseline on its own holdout.

24-month epochs (EPOCH_BARS=500) per the ADR-0006 prototype finding:
12-month epochs are structurally unreachable; 24-month clear the gate.
Momentum expert only, CPU-only. Output: data/arena/epoch_report.json.
"""

import json
import statistics
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "arena"

sys.path.insert(0, str(PROJECT))

from arena import agent as agent_mod
from arena import candidates as cand_mod
from setup_search.value_head import THETA_BAR

EPOCH_BARS = 500        # 24-month epoch (~250 bars/yr)
EROSION_BAR = 0.005     # half-gate
EPOCHS = 250            # MLP fit epochs
LR = 1e-3


def window_margins(art, rows):
    """Same discrimination as recompute_gate: kept vs all forward-return
    margin on the given rows, using the model's theta."""
    theta = art["theta"]
    if not rows:
        return []
    wp = agent_mod.predict_batch(art, [r["x"] for r in rows])
    kept = [r["fwd"] for r, p in zip(rows, wp) if p >= theta]
    all_m = statistics.mean(r["fwd"] for r in rows)
    kept_m = statistics.mean(kept) if kept else 0.0
    return kept_m - all_m


def gate_pass(art, holdout):
    """(a) the +1% gate: recompute_gate passes iff every adaptive window on
    the holdout has margin >= THETA_BAR."""
    gated = agent_mod.recompute_gate(art, holdout)
    return gated["report"]["pass"], gated["report"]["results"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, cfg = cand_mod.collect("5y")
    rows.sort(key=lambda r: r["bar"])
    lo, hi = min(r["bar"] for r in rows), max(r["bar"] for r in rows) + 1
    span = hi - lo
    n_epochs = max(1, (span - 1) // EPOCH_BARS)
    print(f"[epoch] {len(rows)} momentum rows, bars {lo}-{hi} ({span}) -> {n_epochs} epochs of ~{EPOCH_BARS} bars")

    # global baseline: single expert fit once on ALL data
    base_art = agent_mod.fit(rows, None, epochs=EPOCHS, lr=LR)
    print(f"[epoch] baseline global expert fit: theta={base_art['theta']:.4f}")

    boundaries = [min(hi, lo + (k + 1) * EPOCH_BARS) for k in range(n_epochs)]
    epoch_arts = []
    report = {"epochs": [], "n_epochs": n_epochs, "bars": [lo, hi]}

    for n in range(n_epochs):
        train_end = boundaries[n]
        hold_start, hold_end = boundaries[n], boundaries[n + 1] if n + 1 < len(boundaries) else hi
        train = cand_mod.rows_in_window(rows, lo, train_end)
        holdout = cand_mod.rows_in_window(rows, hold_start, hold_end)
        print(f"\n[epoch {n + 1}] train bars {lo}-{train_end} ({len(train)} rows) "
              f"| holdout {hold_start}-{hold_end} ({len(holdout)} rows)")

        art = agent_mod.fit(train, None, epochs=EPOCHS, lr=LR)
        epoch_arts.append(art)
        own_pass, own_results = gate_pass(art, holdout)
        own_margin = window_margins(art, holdout)

        # (b) erosion on prior holdouts vs previous epoch's expert
        erosion = {}
        if n > 0:
            prev = epoch_arts[-2]
            for pn in range(n):
                ph_s, ph_e = boundaries[pn], boundaries[pn + 1] if pn + 1 < len(boundaries) else hi
                ph = cand_mod.rows_in_window(rows, ph_s, ph_e)
                if not ph:
                    continue
                m_new = window_margins(art, ph)
                m_prev = window_margins(prev, ph)
                erosion[f"epoch{pn + 1}"] = round(m_new - m_prev, 5)

        # (c) baseline comparison on this holdout
        base_margin = window_margins(base_art, holdout)

        beats_base = own_margin >= base_margin
        ero_ok = all(v <= EROSION_BAR for v in erosion.values()) if erosion else True
        passed = bool(own_pass) and ero_ok and beats_base

        entry = {
            "epoch": n + 1,
            "train_rows": len(train),
            "holdout_rows": len(holdout),
            "gate_pass": bool(own_pass),
            "gate_results": own_results,
            "own_margin": round(own_margin, 5),
            "baseline_margin": round(base_margin, 5),
            "beats_baseline": beats_base,
            "erosion_deltas": erosion,
            "erosion_ok": ero_ok,
            "PASS": passed,
        }
        report["epochs"].append(entry)
        print(f"[epoch {n + 1}] gate_pass={own_pass} own_margin={own_margin:+.4f} "
              f"base_margin={base_margin:+.4f} beats_base={beats_base} "
              f"erosion={erosion} erosion_ok={ero_ok} -> {'PASS' if passed else 'FAIL'}")

    passed_any = any(e["PASS"] for e in report["epochs"])
    report["verdict"] = "promote-eligible" if passed_any else "no-promotion (log for review, retry next epoch)"
    out_path = OUT / "epoch_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n[epoch] verdict: {report['verdict']}")
    print(f"[epoch] report -> {out_path}")
    return 0 if passed_any else 1


if __name__ == "__main__":
    sys.exit(main())
