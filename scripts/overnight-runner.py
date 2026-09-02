#!/usr/bin/env python3
"""Overnight self-improvement runner — "runner does all file I/O" architecture.

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow
Each of the 5 chapters:
  1. The runner gathers live machine state and file contents (reads files,
     runs recon.sh, runs cheap checks).
  2. The runner builds a self-contained prompt and invokes a tool-less
     "scribe" agent (qwen38) to reason and emit a text analysis.
  3. The runner writes the chapter artifact (chNN.md), appends a distilled
     entry to INDEX.md (capped to the last 5), and (chapter 5) writes the
     final report.

The model never reads files, runs commands, or writes files — so qwen38's
token-level inability to reproduce multi-token paths/URLs in tool calls
cannot corrupt anything.
"""
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
open = guarded_open  # hardening shadow
import datetime, json, os, re, subprocess, time

OPC = "/home/mrc/.opencode/bin/opencode"
DIR = "/home/mrc/opentrader"
DATA = os.path.join(DIR, "data")
CHAPTERS = os.path.join(DATA, "chapters")
ARCHIVE = os.path.join(CHAPTERS, "archive")
INDEX = os.path.join(DATA, "INDEX.md")
LOG = os.path.join(DATA, "overnight_run.log")
CFG = os.path.join(DATA, "overnight-config.jsonc")
REPORT = os.path.join(DATA, "overnight_run_report.md")
RECON = os.path.join(DATA, "overnight_stages", "recon.sh")
VENV_PY = "/home/mrc/rocm_venv/bin/python"
CONTINUE_STR = ("Continue if you have next steps, or stop and ask for "
                "clarification if you are unsure how to proceed.")


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    with guarded_open(LOG, "a") as f:
        f.write("%s %s\n" % (ts(), msg))


def read(p):
    try:
        with guarded_open(p) as f:
            return f.read()
    except Exception as e:
        return "(missing/unreadable %s: %s)" % (p, e)


def run_shell(cmd, timeout=120):
    try:
        r = subprocess.run(shlex.split(cmd), shell=False, cwd=DIR, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return "timeout", "", ""


_live_cache = None


def live_state():
    global _live_cache
    if _live_cache is None:
        rc, out, err = run_shell("bash %s" % RECON, 60)
        _live_cache = (out or "") + (("\n[stderr]\n" + err) if err else "")
    return _live_cache


def llama_cmdlines():
    rc, out, err = run_shell("pgrep -af llama-server", 30)
    return out or err


def machine_facts():
    return (
        "## Machine-verified appendix (runner, not model-generated)\n\n"
        "The figures below were captured by the runner directly from the "
        "machine and are authoritative. Identifiers in the model's prose "
        "above may garble digits/names (e.g. port :5804 as :58, qwen38 as "
        "qwn); trust this appendix over the prose for exact values.\n\n"
        "### Listening ports, services, health (recon.sh, actually run)\n"
        "```\n%s\n```\n\n"
        "### llama-server processes (pgrep -af, actually run)\n"
        "```\n%s\n```\n"
        % (live_state(), llama_cmdlines())
    )


def extract_final(rawfile):
    texts, order = {}, []
    with guarded_open(rawfile) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") == "text":
                mid = e["part"].get("messageID")
                texts.setdefault(mid, []).append(e["part"]["text"])
                if mid not in order:
                    order.append(mid)
    for mid in order:
        j = "".join(texts[mid]).strip()
        if j and j != CONTINUE_STR:
            return j
    return ""


def run_scribe(n, prompt):
    tag = "ch%02d" % n
    raw = os.path.join(CHAPTERS, tag + ".json.log")
    err = os.path.join(CHAPTERS, tag + ".err.log")
    env = dict(os.environ, OPENCODE_CONFIG=CFG, OPENCODE_DISABLE_AUTOCOMPACT="1")
    for attempt in range(1, 4):
        with guarded_open(raw, "w") as out, guarded_open(err, "w") as errf:
            r = subprocess.run(
                [OPC, "run", "--dir", DIR, "--agent", "scribe", "--format",
                 "json", "--title", "overnight-stage-%d" % n, prompt],
                cwd=DIR, env=env, stdout=out, stderr=errf)
        rc = r.returncode
        ans = extract_final(raw)
        if ans:
            log("STAGE %d OK (%d chars)" % (n, len(ans)))
            return ans
        log("STAGE %d EMPTY rc=%d (attempt %d)" % (n, rc, attempt))
    return ""


def cap_index():
    text = read(INDEX)
    parts = re.split(r"(?m)(?=^## Chapter \d+)", text)
    header, chapters = parts[0], parts[1:]
    if len(chapters) > 5:
        os.makedirs(ARCHIVE, exist_ok=True)
        out = os.path.join(ARCHIVE, "index_archived_%d.md" % int(time.time()))
        with guarded_open(out, "w") as f:
            f.write("".join(chapters[:-5]))
        with guarded_open(INDEX, "w") as f:
            f.write(header + "".join(chapters[-5:]))


def record(n, answer):
    tag = "ch%02d" % n
    with guarded_open(os.path.join(CHAPTERS, tag + ".md"), "w") as f:
        f.write(answer)
        f.write("\n\n" + machine_facts())
    with guarded_open(INDEX, "a") as f:
        f.write("## Chapter %d — %s\n%s\n\n" % (n, ts(), answer[:1200]))
    cap_index()


def gather_stage1():
    return {
        "live": live_state(),
        "pinned": read(os.path.join(DATA, "pinned-context.md")),
        "handoff": read(os.path.join(DIR, ".opencode", "skills", "handoff", "SKILL.md")),
        "next": read(os.path.join(DIR, ".opencode", "skills", "next-session", "SKILL.md")),
        "index": read(INDEX),
    }


def parse_jsonc(text):
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return json.loads("".join(out))


FACT_RE = re.compile(r"(:\d{4,5}\b|GPU\d|\d+\s*GB|\d+B\b|Qwen|DeepSeek|"
                     r"Hermes|RTX|GRE|ROCm|CUDA|ollama|router|ctx)")


def summarize_global_config(path):
    c = parse_jsonc(read(path))
    lines = []
    for name, m in c.get("mcp", {}).items():
        if m.get("type") == "remote":
            lines.append("MCP %s: remote %s enabled=%s" % (
                name, m.get("url", ""), m.get("enabled")))
        else:
            cmd = m.get("command", [])
            cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            lines.append("MCP %s: local %s enabled=%s" % (
                name, cmd, m.get("enabled")))
    for name, a in c.get("agent", {}).items():
        lines.append("AGENT %s: model=%s mode=%s desc=%s" % (
            name, a.get("model"), a.get("mode"), a.get("description")))
        for ln in (a.get("prompt") or "").splitlines():
            s = ln.strip()
            if s and FACT_RE.search(s) and len(s) < 300:
                lines.append("    " + s)
    for name, p in c.get("provider", {}).items():
        base = (p.get("options") or {}).get("baseURL", "")
        models = list((p.get("models") or {}).keys())
        lines.append("PROVIDER %s: baseURL=%s models=%s" % (name, base, models))
    return "\n".join(lines)


def gather_stage2():
    return {
        "live": live_state(),
        "index": read(INDEX),
        "global_cfg": summarize_global_config(
            os.path.expanduser("~/.config/opencode/opencode.jsonc")),
        "overnight_cfg": read(CFG),
    }


def gather_stage3():
    return {
        "index": read(INDEX),
        "handoff": read(os.path.join(DIR, ".opencode", "skills", "handoff", "SKILL.md")),
        "next": read(os.path.join(DIR, ".opencode", "skills", "next-session", "SKILL.md")),
        "arch": read(os.path.join(DIR, ".opencode", "skills", "arch", "SKILL.md")),
    }


def gather_stage4():
    rc, out, err = run_shell("ls -la tests/ 2>&1", 30)
    files = (out or "") + err
    rc2, compile_out, compile_err = run_shell(
        "%s -m py_compile tests/*.py 2>&1" % VENV_PY, 90)
    rc3, pytest_out, pytest_err = run_shell(
        "%s -m pytest --version 2>&1" % VENV_PY, 30)
    return {
        "index": read(INDEX),
        "test_files": files,
        "py_compile": "rc=%s\n%s%s" % (rc2, compile_out, compile_err),
        "pytest": "rc=%s\n%s%s" % (rc3, pytest_out, pytest_err),
    }


def build_stage1(c):
    return """You are chapter 1 of a 5-chapter overnight self-improvement run for OpenTrader. You are a text-only analyst; every fact you need is already below. Produce your answer as plain text only.

Start your answer with ONE paragraph (under 8 lines): the services' current state (up/down) and the top 3 drift items. Then, after a blank line, give your full findings: a "Services" table, a "Ports listening" list, and a numbered "Drift list" comparing claimed state to live state.

=== LIVE MACHINE STATE (actually run via recon.sh) ===
%s

=== CLAIMED STATE — data/pinned-context.md ===
%s

=== CLAIMED STATE — .opencode/skills/handoff/SKILL.md ===
%s

=== CLAIMED STATE — .opencode/skills/next-session/SKILL.md ===
%s

=== PRIOR CHAPTERS — data/INDEX.md ===
%s

Rules: state only facts visible above; do not invent numbers; do not call any tools.""" % (
        c["live"], c["pinned"], c["handoff"], c["next"], c["index"])


def build_stage2(c):
    return """You are chapter 2 of a 5-chapter overnight self-improvement run for OpenTrader. You are a text-only analyst; all material is below. Produce your answer as plain text only.

Start with ONE paragraph (under 8 lines) summarizing: MCP servers you can PROVE unused, stale agent prompts, and any model/port/provider mismatches — and which edits you propose (and which you deliberately skip). Then give full findings: for each MCP server and each agent prompt, a verdict with evidence; for each proposed edit, the exact change and the evidence.

=== PRIOR CHAPTERS — data/INDEX.md ===
%s

=== LIVE MACHINE STATE (recon.sh) ===
%s

=== GLOBAL CONFIG — ~/.config/opencode/opencode.jsonc ===
%s

=== OVERNIGHT CONFIG — data/overnight-config.jsonc ===
%s

Rules: propose an edit only with evidence; if you cannot prove a server/prompt is unused or stale, say so and leave it. No invented facts. Do not call any tools.""" % (
        c["index"], c["live"], c["global_cfg"], c["overnight_cfg"])


def build_stage3(c):
    return """You are chapter 3 of a 5-chapter overnight self-improvement run for OpenTrader. You are a text-only analyst; all material is below. Produce your answer as plain text only.

Start with ONE paragraph (under 8 lines): which skill files need correction and the single most important fix in each. Then give full findings: for each skill file, list the specific stale facts (service names/ports, running/stopped status, model identities, known bugs) and the exact corrected text you propose. Leave anything not proven wrong untouched.

=== PRIOR CHAPTERS — data/INDEX.md ===
%s

=== .opencode/skills/handoff/SKILL.md ===
%s

=== .opencode/skills/next-session/SKILL.md ===
%s

=== .opencode/skills/arch/SKILL.md ===
%s

Rules: correct only facts proven wrong by the drift list above or by clear self-contradiction; do not rewrite wholesale; no invented facts; do not call any tools.""" % (
        c["index"], c["handoff"], c["next"], c["arch"])


def build_stage4(c):
    return """You are chapter 4 of a 5-chapter overnight self-improvement run for OpenTrader. You are a text-only analyst; all material is below. Produce your answer as plain text only.

Start with ONE paragraph (under 8 lines): how many test files exist, whether they compile, and what you recommend running. Then give full findings: for each test file, what it appears to test, any compile/import problems, and any safe, local fix you propose (with the exact change). Flag anything that needs a GPU or a larger redesign as a blocker — do not guess.

=== PRIOR CHAPTERS — data/INDEX.md ===
%s

=== TEST FILES — tests/ ===
%s

=== PY_COMPILE RESULT (actually run) ===
%s

=== PYTEST AVAILABILITY (actually run) ===
%s

Rules: no fabricated pass/fail; distinguish what was actually run from what you recommend running; do not call any tools.""" % (
        c["index"], c["test_files"], c["py_compile"], c["pytest"])


def build_stage5(c):
    return """You are chapter 5 of a 5-chapter overnight self-improvement run for OpenTrader. You are a text-only analyst; all material is below. Produce your answer as plain text only.

Your answer IS the overnight report. Write it with these sections, in order:
# Overnight Self-Improvement Report (date)
## Services (actual state, from chapter 1)
## Drift found (chapter 1)
## Harness changes (chapter 2) — proposed edits, and edits skipped and why
## Skill updates (chapter 3) — proposed corrections
## Code changes (chapter 4) — tests actually run, proposed fixes, blockers
## Remaining blockers
## Honesty note — everything here is PROPOSED by the model and RECORDED by the runner; nothing was auto-applied. Anything uncertain or left undone.

=== PRIOR CHAPTERS — data/INDEX.md ===
%s

=== CHAPTER ARTIFACTS ===
ch01: %s

ch02: %s

ch03: %s

ch04: %s

Rules: every claim must trace to the material above; no invented metrics; do not call any tools.""" % (
        c["index"], c["ch01"], c["ch02"], c["ch03"], c["ch04"])


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--from", dest="from_stage", type=int, default=1)
    args = ap.parse_args()
    only = args.only
    from_stage = args.from_stage

    def should_run(n):
        if only is not None:
            return n == only
        return n >= from_stage

    os.makedirs(CHAPTERS, exist_ok=True)
    os.makedirs(ARCHIVE, exist_ok=True)
    if not os.path.exists(INDEX):
        guarded_open(INDEX, "w").write("# Overnight Run Index\n\n")
    if should_run(1):
        guarded_open(LOG, "w").write("")
    log("RUNNER START (scribe/text-only architecture) only=%s from=%s" % (only, from_stage))

    if should_run(1):
        c1 = gather_stage1()
        record(1, run_scribe(1, build_stage1(c1)))

    if should_run(2):
        c2 = gather_stage2()
        record(2, run_scribe(2, build_stage2(c2)))

    if should_run(3):
        c3 = gather_stage3()
        record(3, run_scribe(3, build_stage3(c3)))

    if should_run(4):
        c4 = gather_stage4()
        record(4, run_scribe(4, build_stage4(c4)))

    if should_run(5):
        c5 = {
            "index": read(INDEX),
            "ch01": read(os.path.join(CHAPTERS, "ch01.md")),
            "ch02": read(os.path.join(CHAPTERS, "ch02.md")),
            "ch03": read(os.path.join(CHAPTERS, "ch03.md")),
            "ch04": read(os.path.join(CHAPTERS, "ch04.md")),
        }
        a5 = run_scribe(5, build_stage5(c5))
        record(5, a5)
        with guarded_open(REPORT, "w") as f:
            f.write(a5)
            f.write("\n\n" + machine_facts())

    log("RUNNER DONE")


if __name__ == "__main__":
    main()
