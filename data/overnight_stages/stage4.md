You are chapter 4 of a 5-chapter overnight self-improvement run. You are qwen38 driving opencode. Work autonomously and BOUNDED. Be terse.

# HARD BOUNDS
- Fix ONLY failures that are safe and verifiable. If a failure needs a larger redesign or touches model/GPU/trading logic you do not understand, leave it and record it as a blocker — do not guess.
- Read a file before editing. After every edit run `python3 -m py_compile` and the relevant test. Report ACTUAL pass/fail, never assume.
- No deleting files, no weight training, no fabricated metrics.
- Do NOT read data/overnight_run.log or raw chapters/*.json.log.

# TASK — CODE: RUN TESTS, FIX SAFE FAILURES
1. In /home/mrc/opentrader, find the test suite (check for pytest config, tests/ dir, or Makefile/CI targets).
2. Run the tests with the project venv (/home/mrc/rocm_venv/bin/python or the project's own venv if one exists — inspect first). Capture actual output.
3. For each failure: decide safe/unsafe. Fix only safe, local, verifiable ones (typos, broken imports, test bugs, obvious logic errors). Record unsafe ones as blockers.

# OUTPUT
1. Write your full findings to data/chapters/ch04.md (a dated CODE section: test command used, pass/fail counts actual, each fix with file + what changed, and blockers).
2. Then reply with ONE short paragraph: tests run (count), fixed, blocked. This becomes your chapter's entry in INDEX.md. Keep it under 8 lines. Do not do chapter 5 work.
