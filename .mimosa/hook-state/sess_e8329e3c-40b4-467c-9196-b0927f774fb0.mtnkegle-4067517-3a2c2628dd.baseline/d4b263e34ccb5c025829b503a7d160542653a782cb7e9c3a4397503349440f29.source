#!/usr/bin/env python3
"""Autonomous task: retrain the successor (Ptolemy) on accumulated data.

Runs the training scheduler in force mode (the Genesis->Ptolemy lifecycle).
Writes a summary of what happened so the scheduler log tells the story.
"""

import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def main():
    print("[ptolemy] running training scheduler (--force)...")
    r = subprocess.run(
        [sys.executable, "-m", "training.train_scheduler", "--force"],
        cwd=str(PROJECT), capture_output=True, text=True, timeout=14300,
    )
    tail = (r.stdout or "")[-1500:] + (r.stderr or "")[-500:]
    print(f"[ptolemy] rc={r.returncode}")
    print(f"[ptolemy] tail:\n{tail}")
    import json

    out = PROJECT / "data" / "research_gate" / "ptolemy_retrain.json"
    out.write_text(json.dumps({"rc": r.returncode, "tail": tail[-2000:]}, indent=1))


if __name__ == "__main__":
    main()
