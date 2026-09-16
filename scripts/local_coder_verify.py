#!/usr/bin/env python3
"""local_coder_verify — re-derive the agent's PROOF claims against reality.

Reads opencode's JSON event stream from stdin, finds the assistant's final
report, extracts the PROOF commands, re-runs them, and rejects the result if
any proof command produces output inconsistent with what the agent claimed.

This is how we catch fabrication: the model can claim "all tests pass" all day,
but if we then re-run the test and it fails, we reject the run.

Usage: scripts/local_coder.sh "task" | tee /tmp/out | scripts/local_coder_verify.py
Exit 0 if all proof commands re-derive, non-zero with details if not.
"""
import json, re, subprocess, sys

SAFE_PREFIXES = ("python3 -m pytest", "pytest", "grep ", "wc ", "cat ",
                 "diff ", "md5sum", "sha256sum", "stat ", "find ",
                 "head ", "tail ", "echo ", "ls ", "python3 -c ",
                 "git diff", "git status", "git log", "git show",
                 "python3 scripts/", "python3 -m unittest", "python3 -m doctest")

# Characters that make a command rewrite-safe: if the command does not have the
# normal output yet, we can DISARM it into a pure read. For now we only allow
# commands that are inherently read-only: pytest, grep, wc, cat, diff, etc.
# (Pytest is read-only — it doesn't modify the tree.)


def safe(cmd):
    """Check that cmd is safe to re-run (no destructive side-effects)."""
    return any(cmd.strip().startswith(p) for p in SAFE_PREFIXES)


def rederive(cmd, expected_snippet):
    """Run the command and check that expected_snippet appears in its output."""
    try:
        rc, out = subprocess.getstatusoutput(cmd)
    except Exception as e:
        return False, f"could not run: {e}"
    if expected_snippet in out:
        return True, "verified"
    return False, f"rc={rc} expected={expected_snippet!r} not in output (first 200 chars: {out[:200]})"


def main():
    proof_claims, errors = [], []
    report_text = ""
    # Parse opencode output
    for line in sys.stdin:
        line = line.strip()
        if not line.startswith("{"):
            if line:
                report_text += line + "\n"
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            report_text += line + "\n"
            continue
        if ev.get("type") == "text":
            report_text += (ev.get("text") or "") + "\n"
        p = ev.get("part") or {}
        if p.get("type") == "text":
            report_text += (p.get("text") or "") + "\n"

    # Extract PROOF lines from the assistant text
    for m in re.finditer(r"PROOF:\s*(.+)", report_text):
        proof = m.group(1).strip()
        # split on " -> " to get command and expected output
        parts = proof.split(" -> ", 1)
        cmd = parts[0]
        expected = parts[1].strip() if len(parts) > 1 else ""
        if safe(cmd):
            ok, why = rederive(cmd, expected)
            proof_claims.append((cmd, expected, ok, why))
            if not ok:
                errors.append(f"  FAIL: {cmd}\n    expected: {expected}\n    why: {why}")
        else:
            proof_claims.append((cmd, expected, "SKIP", "unsafe command — not re-run"))

    if not proof_claims:
        print("VERIFY: no PROOF lines found — nothing to verify")
        return 1

    for cmd, expected, ok, why in proof_claims:
        status = "OK" if ok is True else ("SKIP" if ok == "SKIP" else "FAIL")
        print(f"  {status:4s} {cmd[:80]}")
        if ok is not True:
            print(f"         {why}")

    if errors:
        print(f"\nVERIFY: {len(errors)} proof(s) failed — run rejected")
        return 1
    print("\nVERIFY: all proofs re-derived — run accepted")

    # Tree-state check: report any changes the agent made to the repo.
    rc, state = subprocess.getstatusoutput("cd /home/mrc/opentrader && git diff --shortstat 2>/dev/null")
    if rc == 0 and state.strip():
        print(f"  Note: tree has uncommitted changes: {state}")
    elif rc == 0:
        print("  Tree is clean (no uncommitted changes).")

    return 0


if __name__ == "__main__":
    sys.exit(main())