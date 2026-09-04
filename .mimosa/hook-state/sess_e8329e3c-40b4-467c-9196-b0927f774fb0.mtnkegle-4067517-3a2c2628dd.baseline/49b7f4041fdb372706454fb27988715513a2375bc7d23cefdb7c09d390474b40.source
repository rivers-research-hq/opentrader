#!/usr/bin/env python3
"""Seed a bug-bounty sandbox: copy the live opentrader tree, inject the verified
historical bugs, write manifest.json (ground truth), and run each detector to
prove the seeds are actually present.

Usage:
  python3 scripts/bug-bounty/seed.py [outdir]

Exit 0 = all seeds verified present. Non-zero = a seed failed its detector.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/home/mrc/opentrader")
HERE = Path(__file__).resolve().parent
BUGS_DIR = HERE / "bugs"
DEFAULT_OUT = Path("/tmp/opencode/bb-sandbox")
DEFAULT_MANIFEST = Path("/tmp/opencode/bb-meta/manifest.json")

# Files we never copy (state data, caches, .git) so the agent sees only source.
SKIP = {
    ".git", "data", "__pycache__", ".venv", "venv",
    "charts", "showcase", "static", ".pytest_cache",
}


def load_bug(mod_path: Path):
    spec = importlib.util.spec_from_file_location("bug", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def apply_seed(tree: Path, bug) -> None:
    target = tree / bug.FILE
    src = target.read_text()
    assert bug.FIXED_BODY in src, f"{bug.BUG_ID}: fixed body not found in {bug.FILE}"
    src = src.replace(bug.FIXED_BODY, bug.BUGGY_BODY, 1)
    target.write_text(src)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    manifest_path = (Path(sys.argv[2]) if len(sys.argv) > 2
                     else DEFAULT_MANIFEST)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Copy all source files (tracked + untracked .py, configs), excluding heavy
    # runtime data and caches. harness.py pulls in modules from data/ and
    # training/ that aren't all git-tracked, so a full-tree walk is required.
    for src in REPO.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(REPO)
        # Never descend into the output dir we're writing (sandbox lives
        # under scripts/bug-bounty/ when using the default).
        if str(rel).startswith(str(HERE.relative_to(REPO))):
            continue
        if any(part in {".git", "__pycache__", ".venv", "venv", ".pytest_cache",
                        "charts", "showcase", "static", ".ruff_cache"}
               for part in rel.parts):
            continue
        # Keep python modules everywhere (incl. data/, training/), skip heavy
        # data blobs and artifacts.
        if rel.suffix == ".py" or rel.suffix in {".toml", ".cfg", ".ini"}:
            pass
        elif rel.suffix in {".pkl", ".csv", ".sqlite", ".db", ".json",
                            ".jsonl", ".log", ".md", ".html", ".svg", ".png",
                            ".jpg", ".jpeg", ".pdf", ".txt", ".yaml", ".yml",
                            ".npy", ".npz", ".parquet", ".joblib"}:
            continue
        elif not (rel.suffix == ".py"):
            # Non-python, non-data files (e.g. .sh) — keep only small source-ish
            if rel.suffix not in {".sh", ".py"}:
                continue
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Load bugs and inject.
    manifest = []
    bug_mods = []
    for mod_path in sorted(BUGS_DIR.glob("bug_*.py")):
        bug = load_bug(mod_path)
        apply_seed(out, bug)
        manifest.append({
            "id": bug.BUG_ID,
            "file": bug.FILE,
            "function": bug.FUNCTION,
            "severity": bug.SEVERITY,
            "detectable_by": bug.DETECTABLE_BY,
            "keywords": bug.KEYWORDS,
        })
        bug_mods.append(bug)

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"bugs": manifest}, indent=2)
    )

    # Verify every seed is present with its detector.
    import os
    env = dict(os.environ, PYTHONPATH=str(out))
    rc = 0
    for bug in bug_mods:
        det = bug.DETECTOR.strip()
        p = subprocess.run(
            [sys.executable, "-c", det], cwd=out, env=env,
            capture_output=True, text=True,
        )
        status = "OK" if p.returncode == 0 else "FAIL"
        print(f"[{status}] {bug.BUG_ID}: {p.stdout.strip() or p.stderr.strip()}")
        if p.returncode != 0:
            rc = 1
    print(f"manifest -> {manifest_path}")
    print(f"seeds verified: {len(bug_mods) - rc} of {len(bug_mods)} present")
    print(f"IMPORTANT: manifest kept OUTSIDE the sandbox ({manifest_path}); "
          f"the agent must never see it")
    return rc


if __name__ == "__main__":
    sys.exit(main())
