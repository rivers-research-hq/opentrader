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

def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__); return 2
    artifact = json.loads(pathlib.Path(sys.argv[1]).read_text())
    card = pathlib.Path(sys.argv[2]).read_text()
    allowed_deps = set()
    if "--deps" in sys.argv:
        # normalize crate names: ot-core == ot_core on the `use` side
        allowed_deps = {d.replace("-", "_") for d in sys.argv[sys.argv.index("--deps") + 1].split()}
    content = artifact.get("content") or ""
    findings = []

    # 1. dependency scan: any `use <crate>` / `extern crate` outside the allowlist
    std_ok = {"std", "core", "alloc", "crate", "self", "super"}
    for m in re.finditer(r"^\s*(?:pub\s+)?use\s+([a-zA-Z_][a-zA-Z0-9_]*)", content, re.M):
        krate = m.group(1)
        if krate in std_ok or krate in allowed_deps:
            continue
        findings.append(f"out-of-scope crate used: `{krate}` (allowed: {sorted(allowed_deps) or 'std only'})")

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
