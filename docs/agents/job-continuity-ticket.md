# TASK — Fills/equity continuity across harness restarts (diagnose → fix, one session)

You are the OpenTrader implementer (Qwen3.8-27B). This is ONE bounded task:
find out why harness restarts reset the paper portfolio, then fix it so
restarts RESUME instead of reinitialize. Work in the **sandbox checkout**;
deliver a patch. Evidence already collected — do not re-derive it.

## PRECONDITION — freshness + tree checks

1. If ANY prior conversation exists above this message, STOP and reply
   exactly: "NOT A FRESH SESSION — open a new one and paste only this file."
2. Every file you read/edit must be under `/home/mrc/opentrader-sandbox/`
   (exceptions: this card, the ToC workspace, `data/wayfinder/` heartbeat).
   Catch yourself on a `/home/mrc/opentrader/...` path → correct to
   `/home/mrc/opentrader-sandbox/...`.

## STEP 0 — Orient (≤4 calls)

```bash
cd /home/mrc/opentrader-sandbox && git status --short | head
cd /home/mrc/opentrader/data/wayfinder/toc && toc status && cat chapters/01-scope.md
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start continuity --allowance 25000
```
Then read the ToC ledger (V01–V20 + Q03) and AGENTS.md "Audit gate".

## THE EVIDENCE (already gathered 2026-08-29 — verify, don't redo)

- Before today's 14:22 restart: paper account had cash $373.94, 3 positions
  (BTC/ETH/SOL) opened at cycle 12869, 3 fills.
- After restart: `initial_cash` reset to 500.0, cash 500 → 352.35 after
  re-entry, fills log wiped to 3 NEW entries (live_1/2/3, 19:22Z), positions
  re-opened at cycle 20634. `data/history/cycle_*.json` mtimes SURVIVED.
- Live harness unit: `systemctl --user cat opentrader-harness` (note the
  flags — there is no `--reset-portfolio` flag anymore; #118 removed it).
- Shadow (`opentrader-shadow`) shows the same behavior (cash also reset).

## THE WORK

### Item 1 — Root cause (sandbox, read-only)

Trace the startup path: where does `harness.py` (or `state/manager.py`) decide
to initialize a fresh portfolio vs load the existing `paper_state.json`?
Candidate suspects to check (verify, don't assume): startup default when
`--reset-portfolio` was removed (#118); a cycle/stage mismatch treating the
existing state as stale; the `--stage 3` re-entry path; fills list truncation
on save. Write the causal chain in one paragraph with file:line anchors.

Verify: quote the exact lines that cause the reset (verbatim, with paths).

### Item 2 — Fix: append-only fills ledger + resume semantics

- **Fills**: every fill also appends one JSON line to
  `data/fills_ledger.jsonl` (append-only, fsync-friendly, declared in
  `data/MANIFEST.json` as runtime-state with the harness as sole writer).
  Startup loads `paper_state.json` for positions/cash but REBUILDS fills
  history from the ledger if the in-file list is shorter.
- **Resume**: fix the root cause from Item 1 so a restart with an existing
  `paper_state.json` resumes cash/positions (no re-initialization) unless the
  operator explicitly passes a reset flag. If a reset flag is needed,
  re-introduce an explicit `--reset-portfolio` (opt-in, loud log line) rather
  than implicit behavior.
- Keep the change minimal — this is plumbing fidelity (ADR-0002 clause 1),
  not a redesign.

### Item 3 — Prove it

In the sandbox, simulate: start-state with 3 positions + 3 fills → simulated
restart → assert cash/positions/fills-history survive (write a tiny test
script under `sandbox tests` or a `__main__` self-check; paste its output
verbatim). Then show a forced-reset path still works via the explicit flag.

## CAPS AND RULES

- ≤ 40 tool calls; heartbeat every ~10 to
  `data/wayfinder/ultimate_chapter.md`
  (`continuity heartbeat <N> item:<1|2|3> did:<one line> next:<one line>`).
- Sandbox only. No service restarts. No commits in the live tree.
- Every claim from a command you ran this session; ledger facts V01–V20 are
  `[known]` — never contradict from memory.
- Blocked >3 attempts on an item → stop it, report the blocker, move on.
- End: `toc checkpoint --allowance 5000` in the ToC workspace.

## DELIVERABLES

1. `git -C /home/mrc/opentrader-sandbox diff > /home/mrc/opentrader/data/wayfinder/patches/continuity.patch` (mkdir -p the dir)
2. Report: root-cause paragraph with file:line anchors, verbatim test output, call count, blockers.
3. Heartbeat line appended.
4. Proposed GitHub issue text (do NOT post):
   **Title:** "Harness restart resets paper portfolio — fills history and equity continuity lost"
   **Body:** the root-cause paragraph + before/after evidence above + the fix summary + ADR-0002 clause-1 impact (evidence continuity is a deployability input).
