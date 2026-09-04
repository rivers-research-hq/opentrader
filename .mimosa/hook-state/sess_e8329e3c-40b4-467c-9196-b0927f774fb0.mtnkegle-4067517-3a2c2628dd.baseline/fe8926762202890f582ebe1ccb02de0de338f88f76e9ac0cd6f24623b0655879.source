#!/usr/bin/env python3
"""Score bug-bounty runs against the ground-truth manifest.

Uses the shared detection logic (scoring.py) so results match the runner's
early-exit decisions. Writes a comparison table + scores.json.

Usage: python3 scripts/bug-bounty/score.py
"""
import json
import sys
from pathlib import Path

REPO = Path("/home/mrc/opentrader")
HERE = Path(__file__).resolve().parent
OUT_ROOT = REPO / "data" / "benchmark-q38" / "bug-bounty"
MANIFEST = Path("/tmp/opencode/bb-meta/manifest.json")

import scoring  # noqa: E402


def main() -> int:
    ground = scoring.load_ground(MANIFEST)
    rows = []
    for combo_dir in sorted(OUT_ROOT.iterdir()):
        if not combo_dir.is_dir():
            continue
        transcript = combo_dir / "transcript.txt"
        meta = combo_dir / "meta.json"
        if not transcript.exists():
            continue
        text = transcript.read_text()
        found = scoring.scan_transcript(text, ground)
        m = json.loads(meta.read_text()) if meta.exists() else {}
        rows.append({
            "combo": combo_dir.name,
            "model": m.get("model", "qwen38"),
            "ctx": m.get("ctx"), "layers": m.get("layers"),
            "budget": m.get("budget"),
            "rc": m.get("rc"), "seconds": m.get("seconds"),
            "reason": m.get("reason"),
            "found": found,
            "n_found": len(found),
            "n_ground": len(ground),
            "reports": scoring.report_lines(text),
            "fp": scoring.false_positives(text, ground),
        })

    rows.sort(key=lambda r: (r.get("model") or "", r.get("ctx") or 0,
                             r.get("budget") or 0, r.get("layers") or 0))
    print(f"{'combo':<20} {'model':<12} {'found':<8} {'ids/conf':<26} "
          f"{'reason':<10} {'sec':<7} {'reports':<8} {'fp'}")
    for r in rows:
        ids = ",".join(f"{k}:{v[0]}" for k, v in r["found"].items()) or "-"
        print(f"{r['combo']:<20} {r['model']:<12} {r['n_found']}/{r['n_ground']:<6} "
              f"{ids:<26} {str(r.get('reason')):<10} "
              f"{str(r.get('seconds')):<7} {r.get('reports', 0):<8} {r['fp']}")

    (OUT_ROOT / "scores.json").write_text(json.dumps(rows, indent=2))
    print(f"\nscores -> {OUT_ROOT / 'scores.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
