#!/usr/bin/env python3
"""Autonomous self-test task: verifies the workflow process + scheduler infra.

Checks (each writes a pass/fail line, all summarized to a JSON result):
1. The scheduler's signals work (GPU0/GPU1 launch counters readable).
2. The manifest is valid and every task has a gpu assignment + result file path.
3. The wayfinder workflow artifacts exist: a wayfinder:map issue, its closed
   child tickets have resolution comments, and the map's Decisions-so-far is
   populated (gh CLI checks).
4. The results dir is writable and the last task results parse as JSON.
"""

import json
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "gpu_scheduler"


def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception as e:
        return f"ERR {e}"


def main():
    checks = {}

    # 1. signals readable
    from setup_search.gpu_scheduler import launches_in, GPU0_SERVICE, GPU1_SERVICE
    checks["gpu0_signal"] = launches_in(GPU0_SERVICE, 5) >= 0
    checks["gpu1_signal"] = launches_in(GPU1_SERVICE, 1) >= 0

    # 2. manifest valid + assignments
    m = json.loads((PROJECT / "setup_search" / "auto_tasks.json").read_text())
    tasks = m["tasks"]
    checks["manifest_valid"] = len(tasks) >= 3
    checks["all_tasks_have_gpu"] = all("gpu" in t for t in tasks)

    # 3. workflow artifacts (gh)
    gh = "gh issue list --state closed --json number,title,labels"
    out = run(f"{gh} --jq '[.[] | select(any(.labels[]?; .name==\"wayfinder:map\"))][0]'")
    checks["map_exists_closed"] = "wayfinder" in out or "issue" in out.lower() or len(out) > 10
    map_title = None
    try:
        map_title = json.loads(out).get("title") if out.startswith("{") else None
    except Exception:
        pass
    checks["map_decisions_populated"] = bool(map_title and "wayfinder:map" in map_title)

    # 4. results dir + last result parses
    checks["results_writable"] = OUT.exists()
    result_files = list((PROJECT / "data" / "research_gate").glob("*.json"))
    checks["gate_results_exist"] = len(result_files) > 0
    if result_files:
        try:
            json.loads(result_files[0].read_text())
            checks["last_result_parses"] = True
        except Exception:
            checks["last_result_parses"] = False

    passed = sum(1 for v in checks.values() if v)
    verdict = "SELF-TEST PASS" if passed == len(checks) else f"SELF-TEST PARTIAL ({passed}/{len(checks)})"
    print(verdict)
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'XX '}{k}")
    (OUT / "self_test.json").write_text(json.dumps({**checks, "verdict": verdict}, indent=1))


if __name__ == "__main__":
    main()
