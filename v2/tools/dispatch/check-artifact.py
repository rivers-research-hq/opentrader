#!/usr/bin/env python3
"""check-artifact.py — integrator gate for dispatched worker artifacts (ticket #393).

Checks an artifact against its card's SCOPE + OUTPUT CONTRACT before a human
merges it. Catches today's defect classes mechanically:
  - out-of-scope dependencies (the `nix` incident)
  - full-file emission when the card said blocks (the hallucinated-skeleton class)
  - dropped symbols when a full-file was emitted (the W4a class)
  - emitted files outside ALLOWED FILES

Usage: check-artifact.py <artifact.json> <card.txt> [--deps "serde serde_json sha2"]
rc: 0 = clean, 1 = findings, 2 = usage error.
"""
import json, re, sys, pathlib

def extract_content(artifact) -> str:
    """Pull the model's text out of any dispatch-artifact shape.

    Supported: {"content": "..."} (normalized) and the raw OpenAI-shaped
    response {"choices": [{"message": {"content": ...}}]} (what the dispatch
    scripts actually save). Returns "" when nothing is extractable — the
    caller treats that as a refusal, never as a pass.
    """
    if isinstance(artifact, str):
        return artifact
    if not isinstance(artifact, dict):
        return ""
    if isinstance(artifact.get("content"), str) and artifact["content"].strip():
        return artifact["content"]
    choices = artifact.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            parts = []
            if isinstance(msg.get("content"), str):
                parts.append(msg["content"])
            if isinstance(msg.get("reasoning_content"), str):
                parts.append(msg["reasoning_content"])
            return "\n".join(parts)
    return ""


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__); return 2
    artifact = json.loads(pathlib.Path(sys.argv[1]).read_text())
    card = pathlib.Path(sys.argv[2]).read_text()
    allowed_deps = set()
    if "--deps" in sys.argv:
        # normalize crate names: ot-core == ot_core on the `use` side
        allowed_deps = {d.replace("-", "_") for d in sys.argv[sys.argv.index("--deps") + 1].split()}
    content = extract_content(artifact)
    findings = []
    if not content.strip():
        # FAIL CLOSED. An unreadable artifact must never report "clean": the
        # first version of this gate read only `artifact["content"]`, so every
        # raw API dump (choices[0].message.content) was reported as passing
        # without being read at all — a fail-open gate (the #320 class).
        print("artifact UNREADABLE: no extractable content — refusing to pass")
        return 1

    # 1. dependency scan: any `use <crate>` / `extern crate` outside the allowlist
    std_ok = {"std", "core", "alloc", "crate", "self", "super"}
    for m in re.finditer(r"^\s*(?:pub\s+)?use\s+([a-zA-Z_][a-zA-Z0-9_]*)", content, re.M):
        krate = m.group(1)
        if krate in std_ok or krate in allowed_deps:
            continue
        findings.append(f"out-of-scope crate used: `{krate}` (allowed: {sorted(allowed_deps) or 'std only'})")

    # 1b. inline path expressions: `nix::sys::...` with no `use` line is how the
    # real out-of-scope-dep incident slipped through (only `use` was scanned).
    KNOWN_PATH_ROOTS = std_ok | allowed_deps | {
        "String", "Vec", "Option", "Result", "Some", "None", "Ok", "Err", "Path", "PathBuf",
        "File", "OpenOptions", "fs", "io", "cmp", "collections", "fmt", "time", "process",
        "thread", "sync", "os", "env", "hash", "convert", "iter", "str", "mem", "borrow",
        "marker", "num", "slice", "vec", "boxed", "cell", "rc", "ffi", "panic", "error",
    }
    # noise words that appear before `::` but are never crates (methods, locals,
    # mod-ish fragments): `path::`, `parse::` etc. came from expressions, not imports
    NOISE = {"path", "parse", "kind", "from", "into", "new", "default", "index", "get", "to",
             "as", "is", "eq", "cmp", "add", "sub", "mul", "div", "iter", "map", "filter"}
    for m in re.finditer(r"\b([a-z_][a-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)", content):
        root = m.group(1)
        if root in KNOWN_PATH_ROOTS or root in NOISE:
            continue
        findings.append(f"out-of-scope crate path: `{root}::` (allowed: {sorted(allowed_deps) or 'std only'})")

    # 1c. internal `crate::X::` paths: X must be a real module of the crate.
    # The `crate::core::bar::Bar` defect slipped through because `crate` is
    # legitimately in std_ok — the wrong part was the module name after it
    # (ot-script depends on ot-core as an external crate: ot_core::bar::Bar).
    # Pass --modules "a b c" (the crate's own top-level modules) to enable it.
    if "--modules" in sys.argv:
        modules = set(sys.argv[sys.argv.index("--modules") + 1].split())
        for m in re.finditer(r"\bcrate::([a-z_][a-z0-9_]*)", content):
            if m.group(1) not in modules:
                findings.append(
                    f"unknown internal module: `crate::{m.group(1)}` "
                    f"(crate modules: {sorted(modules)})"
                )

    # 2. output contract: block markers vs full-file emission
    wants_blocks = "EMIT: blocks" in card or "=== BLOCK" in card
    has_blocks = "=== BLOCK" in content
    looks_full_file = bool(re.search(r"^(pub\s+)?(struct|enum|impl|fn)\s", content, re.M)) and content.count("\n") > 80
    if wants_blocks and not has_blocks and looks_full_file:
        findings.append("card required BLOCK output but the artifact looks like a whole file (hallucinated-skeleton risk)")

    # 3. dropped-symbol check for full-file emissions
    if "EMIT: full-file" in card:
        for sym in re.findall(r"`([A-Za-z_][A-Za-z0-9_]{2,})`", card):
            if sym in ("true", "false", "None", "Some"):
                continue
        # symbols explicitly listed in the card as MUST-KEEP
        keep = re.findall(r"MUST KEEP:?\s*(.+)", card)
        for line in keep:
            for sym in re.split(r"[,\s]+", line.strip()):
                if sym and sym not in content:
                    findings.append(f"dropped symbol from MUST KEEP list: {sym}")

    # 4. file-path scope: any `File:`/`crates/...` mention inside blocks vs ALLOWED FILES
    allowed = re.findall(r"ALLOWED FILES:\*\*\s*(.+)", card)
    if allowed:
        allowed_set = set(re.split(r"[,\s]+", allowed[0].strip()))
        for m in re.finditer(r"(crates/[A-Za-z0-9_./-]+\.rs)", content):
            p = m.group(1)
            if allowed_set and p not in allowed_set:
                findings.append(f"artifact references out-of-scope file: {p}")

    if findings:
        print("ARTIFACT FINDINGS:")
        for f in dict.fromkeys(findings):
            print("  -", f)
        return 1
    print("artifact clean: deps in scope, output contract respected")
    return 0

if __name__ == "__main__":
    sys.exit(main())
