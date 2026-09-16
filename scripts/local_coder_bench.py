#!/usr/bin/env python3
"""local_coder_bench — grade the local coding workhorse on objective tasks.

Each task runs in a fresh sandbox copy of data/local/coder-bench/fixture and is
graded by a command that either passes/fails or by comparing the model's report
against ground truth computed independently. Nothing here trusts the model's
self-report: the checkers re-derive the answer.

    python3 scripts/local_coder_bench.py            # all tasks
    python3 scripts/local_coder_bench.py edit_constant count_lines
"""
import json, os, pathlib, re, shutil, subprocess, sys, time

REPO = pathlib.Path("/home/mrc/opentrader")
FIXTURE = REPO / "data/local/coder-bench/fixture"
SBROOT = pathlib.Path("/var/tmp/coder-bench")
RESULTS = REPO / "data/local/coder-bench/results"
PY = str(REPO / ".venv/bin/python3")
OPENCODE = str(REPO / "scripts/local_coder.sh")
AGENT = "local-coder"
MODEL = os.environ.get("BENCH_MODEL", "local-worker/qwen3-coder-30b-a3b-ud")
TIMEOUT_S = 900

# check:      shell command run in the sandbox; exit 0 == pass
# truth:      (cmd, regex) — run cmd, pull the number out, require it in the report
# expect:     strings that must appear verbatim in the model's report
TASKS = [
    dict(name="edit_constant",
         prompt="In config.py, change RETRY_LIMIT from 3 to 5. Verify with one command.",
         check="grep -q '^RETRY_LIMIT = 5' config.py"),
    dict(name="fix_attributor",
         prompt="Running `python3 -m pytest test_attributor.py -q` fails one test. Fix "
                "attributor.py so every test in test_attributor.py passes. Do not modify "
                "any test file.",
         check="python3 -m pytest test_attributor.py -q"),
    dict(name="implement_util",
         prompt="Implement dedupe_by_id in util.py so `python3 -m pytest test_util.py -q` "
                "passes. It must keep the FIRST row for each id, preserving order. Do not "
                "modify any test file.",
         check="python3 -m pytest test_util.py -q"),
    dict(name="full_suite",
         prompt="`python3 -m pytest -q` fails several tests across config.py, attributor.py "
                "and util.py. Make the entire suite pass without editing any test_*.py file.",
         check="python3 -m pytest -q"),
    dict(name="count_lines",
         prompt="Report the exact number of lines in attributor.py. Run a command to get "
                "it — do not estimate.",
         truth=("wc -l < attributor.py", r"\d+")),
    dict(name="quote_output",
         prompt="Run `{py} report.py` and report its output exactly as printed.",
         expect=["LANES: crash,h1-mom,mom-k5", "RETRY_LIMIT: 3"]),
    dict(name="repo_locate", dir="repo",
         prompt="READ ONLY — do not modify any file. In this repository, find the "
                "function named resolve_fill_tag. Report: its file path, the line "
                "number where it is defined, and its exact signature.",
         expect=["strategies/lane_attribution.py", "resolve_fill_tag(t, tags, order_tag)"],
         regex=[r"\b51\b"]),
    dict(name="repo_lifecycle", dir="repo",
         prompt="READ ONLY — do not modify any file. Open strategies/expert_lifecycle.py "
                "and examine the transition function. If new_state is not a valid "
                "lifecycle state, what exactly happens? Quote the exact line of code.",
         expect=["unknown lifecycle state"]),
]



ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


ENV = dict(os.environ, PATH=f"{REPO}/.venv/bin:" + os.environ.get("PATH", ""),
           LOCAL_CODER_MODEL=MODEL)


def run(cmd, cwd, timeout=TIMEOUT_S):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True,
                           text=True, timeout=timeout, env=ENV)
        return p.returncode, ANSI.sub("", p.stdout), ANSI.sub("", p.stderr)
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def parse_events(stdout):
    """Split opencode's JSON event stream into (final assistant text, tool calls, raw)."""
    texts, calls, raw = [], 0, []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            if line:
                raw.append(line)
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = ev.get("part") or {}
        if ev.get("type") == "text" or part.get("type") == "text":
            texts.append(part.get("text") or ev.get("text") or "")
        elif part.get("type") == "tool":
            calls += 1
    return ("\n".join(texts) if texts else "\n".join(raw)), calls, raw


def grade(task, sandbox, report):
    if "check" in task:
        cmd = task["check"]
        rc, out, err = run(cmd, sandbox, timeout=180)
        return rc == 0, f"{cmd} -> rc={rc}" + ("" if rc == 0 else f" {(out+err).strip()[-300:]}")
    if "truth" in task:
        cmd, rx = task["truth"]
        rc, out, _ = run(cmd, sandbox, timeout=60)
        want = re.search(rx, out)
        if not want:
            return False, f"could not compute ground truth ({cmd})"
        got = want.group(0)
        ok = re.search(rf"(?<!\d){re.escape(got)}(?!\d)", report) is not None
        return ok, f"truth={got}; {'found' if ok else 'NOT found'} in report"
    if "expect" in task or "regex" in task:
        missing = [s for s in task.get("expect", []) if s not in report]
        bad = [rx for rx in task.get("regex", []) if not re.search(rx, report)]
        ok = not missing and not bad
        return ok, ("all strings/regex present" if ok
                    else f"missing strings={missing} regex={bad}")
    return False, "task has no checker"


def main():
    wanted = sys.argv[1:]
    RESULTS.mkdir(parents=True, exist_ok=True)
    SBROOT.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"[bench] model={MODEL}")
    for task in TASKS:
        if wanted and task["name"] not in wanted:
            continue
        name = task["name"]
        if task.get("dir") == "repo":
            sandbox = REPO
            rc0 = run("git status --porcelain", REPO)[1]
        else:
            sandbox = SBROOT / name
            if sandbox.exists():
                shutil.rmtree(sandbox)
            shutil.copytree(FIXTURE, sandbox)
            rc0 = ""
        prompt = task["prompt"]
        cmd = [OPENCODE, "--dir", str(sandbox),
               "--title", f"bench-{name}", "--format", "json", prompt]
        t0 = time.time()
        rc, out, err = run(" ".join(f"'{c}'" if " " in c else c for c in cmd),
                           REPO, timeout=TIMEOUT_S)
        secs = round(time.time() - t0, 1)
        ok, why = grade(task, sandbox, parse_events(out)[0])
        if task.get("dir") == "repo":
            dirty = run("git status --porcelain", REPO)[1]
            if dirty != rc0:
                ok = False
                why += " | TREE MODIFIED during run"
        report, calls, raw = parse_events(out)
        (RESULTS / f"{name}.log").write_text(out)
        row = dict(task=name, pass_=ok, secs=secs, exit=rc, tool_calls=calls,
                   grade=why, report_tail=report.strip().splitlines()[-8:])
        rows.append(row)
        print(f"[{'PASS' if ok else 'FAIL'}] {name:18s} {secs:6.1f}s calls={calls:3d} rc={rc}  {why}")
    (RESULTS / "latest.json").write_text(json.dumps(rows, indent=1))
    passed = sum(r["pass_"] for r in rows)
    print(f"\n{passed}/{len(rows)} passed  -> {RESULTS/'latest.json'}")


if __name__ == "__main__":
    main()