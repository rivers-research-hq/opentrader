"""Regression tests for the 2026-08-29 hardening sweep.

The sweep introduced two defect classes that `ast.parse` does NOT catch:

1. `from security.guards import …` inserted ABOVE `from __future__ import annotations`
   → `SyntaxError` at compile time (future-import placement). Only `compile()` sees it.
2. The guard shadow (`urlopen = guarded_urlopen`) followed by a later
   `from urllib.request import …, urlopen` → the shadow is rebound to stock
   `urllib.request.urlopen`, so `validate_url` never runs.

Run as a script:  `.venv/bin/python3 tests/test_hardening_integrity.py`
Run under pytest: `.venv/bin/python3 -m pytest tests/test_hardening_integrity.py -v`
"""

import ast
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# Vendored / generated / tooling trees whose Python is not project code. These
# are excluded from the compile sweep so a dependency's own files don't fail it.
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__", ".mimosa", ".codesage",
    ".opencode", ".ruff_cache", ".pytest_cache", ".zcode", ".agents",
    "unsloth_compiled_cache", "_unsloth_sentencepiece_temp", "exchange-engine",
}

SHADOW_ASSIGN = "urlopen = guarded_urlopen"


def _repo_py_files():
    for p in sorted(REPO.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def test_all_modules_compile():
    """Every repo .py must compile() — catches `from __future__` misplacement.

    `ast.parse` is deliberately NOT used here: future-import placement is a
    compile-time error, not a parse-time one (the exact gap that let the
    2026-08-29 sweep break 7 modules unnoticed for 12 days).
    """
    broken = []
    for p in _repo_py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        try:
            compile(src, str(p), "exec")
        except SyntaxError as e:
            broken.append(f"{p}:{e.lineno}: {e.msg}")
    assert not broken, (
        "uncompilable modules (future-import placement or worse):\n"
        + "\n".join(broken)
    )


def test_guard_shadow_is_final_binding():
    """In every file that installs the shadow, the shadow is the LAST binding.

    Walks module-level statements in source order; the final binding of `urlopen`
    must be `urlopen = guarded_urlopen`, not an import of the stock `urlopen`.
    """
    offenders = []
    for p in _repo_py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        if SHADOW_ASSIGN not in src:
            continue  # this file doesn't claim to install the shadow
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue  # caught by test_all_modules_compile
        last_binding = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "urlopen":
                        last_binding = node
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "urlopen":
                        last_binding = node
        if last_binding is None:
            continue  # shadow text is docstring-only; nothing to check
        is_shadow = (
            isinstance(last_binding, ast.Assign)
            and isinstance(last_binding.value, ast.Name)
            and last_binding.value.id == "guarded_urlopen"
        )
        if not is_shadow:
            offenders.append(str(p))
    assert not offenders, (
        "guard shadow defeated (urlopen rebound after it):\n"
        + "\n".join(offenders)
    )


def _main():
    failures = []
    for fn in (test_all_modules_compile, test_guard_shadow_is_final_binding):
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            print(f"FAIL {fn.__name__}\n{e}")
            failures.append(fn.__name__)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    _main()
