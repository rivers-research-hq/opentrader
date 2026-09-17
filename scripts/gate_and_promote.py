#!/usr/bin/env python3
"""Record and evaluate one FX expert candidate without changing live state.

A candidate is eligible for forward shadow accrual only when the coherence
 gate passes. White's Reality Check is deliberately reported as pending unless
the candidate is part of the canonical comparable population; this command
never mutates the lifecycle registry or deploys orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from fxexpert import gate
from fxexpert.recorder import record_generation


def evaluate_candidate(tag: str, out_dir: Path, history_path: Path,
                       report_dir: Path) -> dict:
    gate_result = gate.evaluate(tag, out_dir=out_dir, write=False)
    row = record_generation(tag, out_dir=out_dir, history_path=history_path,
                            gate_result=gate_result)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tag": str(tag),
        "artifact_dir": str(out_dir),
        "history_row": row,
        "gate": gate_result,
        "wrc": {
            "status": "PENDING_POPULATION",
            "reason": "Candidate is not yet in the canonical comparable population; "
                      "run scripts/white_reality_check.py after population registration.",
        },
        "recommendation": (
            "SHADOW_ELIGIBLE" if row["gate"] == "ELIGIBLE" else "REJECT"
        ),
        "live_deployment": "HUMAN_GATED",
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"gate_and_promote_{tag}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--out-dir", type=Path, default=Path("data/fx_expert"))
    ap.add_argument("--history", type=Path, default=Path("data/fx_expert/history.jsonl"))
    ap.add_argument("--report-dir", type=Path, default=Path("data/fx_expert"))
    args = ap.parse_args()
    report = evaluate_candidate(args.tag, args.out_dir, args.history, args.report_dir)
    print(json.dumps({
        "tag": report["tag"],
        "recommendation": report["recommendation"],
        "wrc": report["wrc"]["status"],
        "report": str(args.report_dir / f"gate_and_promote_{args.tag}.json"),
    }, indent=2))


if __name__ == "__main__":
    main()
