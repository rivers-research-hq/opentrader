# TASK — Ticket #155 "Plumbing" (single bounded job, one session)

You are the OpenTrader implementer (Qwen3.8-27B). This is ONE bounded task:
unify the router plumbing in the **sandbox checkout**, verify it, deliver a
patch. Read the ToC workspace FIRST — it is your scope, your claims registry,
and your budget governor. Do not work anything else this session.

## PRECONDITION — freshness + tree checks (do these before anything else)

1. **Fresh-session check:** if there is ANY prior conversation above this
   message — a state snapshot, a compressed history, an earlier task — STOP
   now and reply exactly: "NOT A FRESH SESSION — open a new one and paste
   only this file." A prior task's context caused a failed 2026-08-29 run
   (4 context compressions, 0 deliverables). Do not repeat it.
2. **Tree check:** every file you read or edit this session must be under
   `/home/mrc/opentrader-sandbox/` — EXCEPT this card, the ToC workspace, and
   `data/wayfinder/ultimate_chapter.md` (agent namespace, live tree). In the
   failed run, 99 consecutive calls read the live tree. If you catch a path
   like `/home/mrc/opentrader/strategies/...` (no `-sandbox`), stop, correct
   to `/home/mrc/opentrader-sandbox/strategies/...`, and continue.

## STEP 0 — Orient (read-only, ≤4 calls)

```bash
cd /home/mrc/opentrader-sandbox && git status --short | head    # dirty sandbox? stash/commit first
cd /home/mrc/opentrader/data/wayfinder/toc && toc status && cat chapters/01-scope.md
```
Then read `docs/adr/0007-reground-victory-path.md` (the score function) and
`AGENTS.md` section "Audit gate" — from the SANDBOX copies. Ledger facts
V01–V20 are pre-verified — never contradict them from memory; if you compute
something different, stop and record it as an open question (`toc open add "..."`).

Open your budget window:
```bash
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start 155 --allowance 30000
```

## HEARTBEAT — externalize state every 10 tool calls (compression armor)

Context compression in this CLI is lossy and has eaten task instructions
before. After every ~10 tool calls (and immediately after finishing each
item), append one line to
`/home/mrc/opentrader/data/wayfinder/ultimate_chapter.md`:
```
155 heartbeat <N=call-count> item:<1|2|3> did:<one line> next:<one line>
```
The call count N is your tool-call budget counter — when N reaches 40, go
straight to DELIVERABLES with whatever you have. If you cannot remember N
after a compression, read your own last heartbeat line and continue from it.

## THE WORK — three items, in order, all in the SANDBOX

Work in `/home/mrc/opentrader-sandbox` (a separate checkout). The live tree
`/home/mrc/opentrader` is **read-only** for you — your only live-tree writes
are the patch file, the chapter point, and the ToC workspace (agent
namespace). First: `cd /home/mrc/opentrader-sandbox && git status` — commit
or stash any pre-existing dirt so your final diff is clean.

### Item 1 — Unify regime keys to `up`/`down`

The router state uses `bull`/`bear` in some places and `up`/`down` in others;
the harness maps bull/bear→up/down at attribution (`harness.py:2636`), so
mismatched keys make records invisible to the router.

- `strategies/experts.py:76` — `regime_key()` returns `"bull"/"bear"`
- `strategies/experts.py:140` — iterates `("bull", "bear", "unknown")`
- `strategies/seed_router.py:45-52` — registers `bull`/`bear` (its own
  comment admits records must live under `up`/`down` or the seed is inert)
- `strategies/handoff.py:81` — `register_regime("bull", ...)`

Canonical = `up`/`down`. Define module-level constants once (e.g. in
`strategies/experts.py`), import them everywhere, convert all router-state
keys. Keep `regime_from_spy()` semantics identical. **Scope guard:** the
`bull_host`/`bull_model` names in `harness.py:544-559` are DEBATE PERSONAS,
not regime keys — do not touch them.

Verify (paste verbatim):
```bash
grep -rn '"bull"\|"bear"\|'"'"'bull'"'"'\|'"'"'bear'"'"'' strategies/ mot/ | grep -v bull_host | grep -v bear_host
PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 -c "import strategies.experts, strategies.seed_router, strategies.handoff; print('imports OK')"
```

### Item 2 — Single writer for `data/live_router_state.json`

Known writers: `strategies/evolve_weights.py:70`, `strategies/seed_router.py:73`,
`strategies/lanes.py:258` — then ENUMERATE the full set yourself:
```bash
grep -rn "live_router_state.json" strategies/ mot/ setup_search/ harness.py | grep -v "\.md"
```
Create `strategies/router_state.py`: one `write_router_state(state)` with an
atomic write (unique tmp name `f"{path}.{os.getpid()}.{time.time_ns()}.tmp"`
+ `os.replace`, same pattern as `state/manager.py::_write_state`), a versioned
schema header, and a read helper. Refactor every writer to call it — no other
file may `open()` that path for writing. Declare the single writer in
`data/MANIFEST.json`. Note: `live_router_state_strategies.json` (shadow.py)
is a separate file — leave its writer as is, but record it in MANIFEST if
absent.

Verify (paste verbatim): the grep above re-run — every hit must be
`router_state.py` or a read-only consumer.

### Item 3 — Prove nothing durable references `/tmp/opentrader` anymore

STEP ZERO moved the probes; verify the move is complete:
```bash
grep -rn "/tmp/opentrader" /home/mrc/opentrader-sandbox --include="*.py" --include="*.sh" --include="*.md" | grep -v node_modules
```
Fix any code hit to point at `data/evidence/` (or the path declared in
`data/MANIFEST.json`). If zero hits: record that as the verified outcome —
"no action needed" is a valid resolution.

## CAPS AND RULES

- **≤ 40 tool calls total**, tracked via your heartbeat lines. Rote steps get
  minimal reasoning; do not emit long `<analysis>` essays — the failed run
  burned 30-minute / 10K-token outputs on re-derivation. State, analyze, act.
- Sandbox-first: nothing you do may restart or reconfigure any service
  (harness, gpu-sync, llama-server, dashboard). No `git commit` in the live
  tree; the sandbox checkout may commit locally.
- Every number you output must come from a command you ran in this session.
  No ledger fact may be contradicted from memory — V01–V20 are `known`.
- If blocked >3 attempts on any item: stop that item, write the blocker in
  the report, move on. A partial honest result beats a fabricated full one.
- At the end: `cd /home/mrc/opentrader/data/wayfinder/toc && toc checkpoint --allowance 6000`

## DELIVERABLES (all four, or the job is not done)

1. `git -C /home/mrc/opentrader-sandbox diff > /home/mrc/opentrader/data/wayfinder/patches/155.patch` (create the dir)
2. A report containing: the three items' verbatim verification output, tool-call count, and any blockers.
3. Append the chapter point to `/home/mrc/opentrader/data/wayfinder/ultimate_chapter.md`:
   ```
   ## checkpoint <timestamp>
   ticket: 155 plumbing
   decided: <one line>
   files-touched: <paths>
   next: <single next action>
   ```
4. Proposed comment text for `gh issue close 155` (do NOT post it yourself —
   the human reviews and posts).
