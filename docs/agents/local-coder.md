# The local coding workhorse (`local-coder`)

The local model is now usable for real coding work on this repo. This is the
operator's guide.

## What it is

| | |
|---|---|
| model | Qwen3-Coder-30B-A3B-Instruct **UD-Q5_K_XL** (unsloth imatrix), 64K ctx, q8_0 KV, n-gram speculation |
| server | llama.cpp on the AMD GRE, `local-worker.service`, `http://127.0.0.1:5808` |
| harness | `opencode`, agent profile `.opencode/agents/local-coder.md` |
| wrapper | `scripts/local_coder.sh` |

## How to use it

```bash
# a task, in the current repo
scripts/local_coder.sh "In strategies/fx_warden.py, find where the halt gate is
checked and add a one-line comment explaining the maintenance exemption."

# against a specific tree
scripts/local_coder.sh --dir /home/mrc/opentrader-sandbox "Run the FX lane tests
and fix the first failure."

# label the session so it is findable later
scripts/local_coder.sh --title fx-halt-fix "..."
```

Each call is a **fresh session** (no `-c`/`-s`), so nothing leaks between tasks.
The wrapper puts `~/opentrader/.venv/bin` first on `PATH`, so `python3`, `pip`
and `pytest` resolve to the project environment.

Agent profile options live in `.opencode/agents/local-coder.md` (`steps`,
`temperature`, tool permissions). To point the wrapper at a different model:
`LOCAL_CODER_MODEL=provider/model scripts/local_coder.sh "..."`.

## What it is good for

Bounded, verifiable coding tasks — the shape where the answer can be *checked*:

- locate → edit → verify (fix a failing test, change a constant, add a function)
- "find X and report its path/line/signature"
- run a command and report its output verbatim
- small multi-bug test-driven fixes

## What it is not good for

- **Unbounded sessions.** Give it one bounded task per call. Multi-hour
  interactive use is outside its envelope (and was what killed the previous
  local-model loop — see the 2026-08-31 postmortem).
- **Unverifiable output.** It still occasionally states an unverified result.
  Always read its `PROOF:` line and confirm the command actually ran and passed.
  Do not let it write gate-feeding artifacts unattended without a checker.
- **Frontier-reasoning or large refactors.** It is a 30B MoE on one GPU.

## Measured behaviour

Benchmark: `scripts/local_coder_bench.py` (8 objective tasks; checkers re-derive
the answer rather than trusting the model). Fixture + results under
`data/local/coder-bench/`.

- **30/30 tasks passed across 5 consecutive full runs** (runs 3,4,6,7,8) after
  the fixes below.
- **8/8 including two read-only tasks on the real repo** (`repo_locate`,
  `repo_lifecycle`), with a git-clean check confirming it did not touch the tree.
- Typical cost: a one-line edit 3–4 tool calls / ~20 s; a test-driven fix
  5–18 calls / 40–330 s. Wall time is dominated by **turn count**, not token
  rate — worth knowing before optimising the model for speed (see below).
- **Model choice settled:** Ornith-1.5-9B-Q4_K_M is ~3× faster per token
  (64 vs 23 tok/s) but needs *more turns* (27 vs 13 calls on the same task), so
  it is no faster end-to-end and less efficient. The MoE is the workhorse;
  Ornith is a viable low-VRAM fallback.

## What made it work (and what to preserve)

1. **The venv on `PATH`.** Without it the model hunted for pytest, tried
   `pip install`, never saw real test output, and then *invented* a pass. The
   wrapper fixes this. Keep it.
2. **An explicit two-mode prompt** (`.opencode/agents/local-coder.md`): simple
   edit → one edit, one verify; test-driven → fix one failure, re-run, repeat,
   last command must be the passing run. An earlier "ONE PASS / VERIFY ONCE"
   prompt actively harmed multi-bug tasks.
3. **A hard no-fabrication rule**, and report checkers that re-derive every
   claimed number.

## Failure modes still on the record

- It can report success on work it did not do (observed 2026-09-16: claimed
  "all 92 tests pass" with zero edits). Verify the `PROOF` line.
- It can exceed the tool budget on hard tasks; `steps: 30` caps it.
- The full V11 ledger-recompute trial (a transcription job, *not* a coding task)
  showed wrong aggregation and a fabricated `tool_calls_used`. Do not route
  gate-feeding compute jobs to it without an independent checker.

## Ops

- The server yields to gaming (`ExecCondition` on `scripts/gpu_pick.py`); if a
  game is running the service will not start. `local-worker.service` is enabled
  for autostart.
- Restart it with `systemctl --user restart local-worker.service`; validate a new
  model with `scripts/local_validate.sh <name> 5808 65536`.
- Model/config source of truth: `ops/local/worker.env`.
