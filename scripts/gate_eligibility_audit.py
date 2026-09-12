#!/usr/bin/env python3
"""gate_eligibility_audit — re-judge the population under the 2026-09-12
eligibility criteria, WITHOUT rewriting the recorded gate_g*.json files.

Those files record what the gate said when the generation ran (old PF bar);
this audit is a separate artifact (data/fx_expert/eligibility_audit.json) so
the two are never confused.

Usage: .venv/bin/python3 scripts/gate_eligibility_audit.py [--era 58]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from fxexpert import gate as fxgate  # noqa: E402

OUT = REPO / "data" / "fx_expert"
HISTORY = OUT / "history.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--era", type=int, default=58)
    ap.add_argument("--out", default="eligibility_audit.json")
    a = ap.parse_args()

    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    gens = []
    for r in rows:
        tag = str(r.get("tag", ""))
        if not tag.isdigit() or int(tag) < 36:
            continue
        p = OUT / f"preds_g{tag}.npz"
        if not p.exists():
            continue
        if np.unique(np.load(p)["pair_idx"]).size != a.era:
            continue
        gens.append(tag)

    results, n_elig = {}, 0
    for t in gens:
        r = fxgate.evaluate(t, write=False)
        g = r["gate"]
        results[t] = {"verdict": g["verdict"], "reasons": g["reasons"],
                      "ic": json.loads((OUT / f"train_g{t}.json").read_text()
                                       )["aggregate"]["ic_mean"],
                      "mu_bps": r["model"]["daily_mean_bps"],
                      "pf_reported_only": r["model"]["pf"]}
        n_elig += g["verdict"] == "ELIGIBLE"

    print(f"\n[audit] {len(gens)} generations on the {a.era}-pair era: "
          f"{n_elig} ELIGIBLE, {len(gens) - n_elig} NOT ELIGIBLE")
    reasons = {}
    for t, v in results.items():
        for r in v["reasons"]:
            key = r.split(" ")[0]
            reasons[key] = reasons.get(key, 0) + 1
    print(f"[audit] reason counts: {reasons}")
    print("[audit] note: eligibility is a coherence check — it is NOT a "
          "promotion and NOT evidence of edge (see gate.py docstring)")

    doc = {"era_pairs": a.era, "n": len(gens), "n_eligible": n_elig,
           "criteria": fxgate.GATE,
           "note": "re-judged under the 2026-09-12 criteria without rewriting "
                   "the recorded gate_g*.json run-time files",
           "generations": results}
    (OUT / a.out).write_text(json.dumps(doc, indent=1))
    print(f"[audit] wrote {OUT / a.out}")


if __name__ == "__main__":
    main()