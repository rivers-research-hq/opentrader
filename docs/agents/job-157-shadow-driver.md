# TASK — Ticket #157 "Shadow driver" (prototype, one session, sandbox)

You are the OpenTrader implementer (Qwen3.8-27B). ONE bounded task: prototype
the recurring shadow driver that accrues per-regime impact from the paper
lanes into the router and fires `RegimeRouter.step()` — the missing piece
that makes ADR-0002 clause 2 measurable (V11 currently reports it NOT
MEASURABLE per ledger V10). Sandbox only; HITL review happens after.

## PRECONDITION — freshness + tree checks

1. Any prior conversation above this message → STOP, reply exactly:
   "NOT A FRESH SESSION — open a new one and paste only this file."
2. All paths under `/home/mrc/opentrader-sandbox/` except: this card, the ToC
   workspace, `data/wayfinder/` heartbeat. Self-correct stray live-tree paths.

## STEP 0 — Orient (≤4 calls)

```bash
cd /home/mrc/opentrader-sandbox && git status --short | head
cd /home/mrc/opentrader/data/wayfinder/toc && toc status && cat chapters/01-scope.md
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start 157 --allowance 30000
```
Read `docs/adr/0007-reground-victory-path.md` (score function) and ledger
facts V06 (verified experts), V10 (loop audit), V11's clause-2 note.

## CONTEXT (what exists — verify, don't assume)

- `strategies/lanes.py` (live): runs one paper lane per verified expert daily
  (cron 17:30 weekdays), caches in `data/lanes_basket.json` /
  `data/lanes_intl.json` / `data/lanes_state.json`, and ALREADY accrues each
  lane's latest 1-day return into the router track via
  `strategies/router_state.py::_accrue_router` (#155 single-writer module).
- `strategies/evolve_weights.py`: one-shot static seed of weights+track —
  `step()` never fires in operation (this is the gap).
- `mot/mixture.py`: `RegimeRouter.record(regime, expert, impact)` +
  `step()` — read both before designing.
- The harness records closes into the same track (attribution path,
  harness.py ~2670) — your driver is the SHADOW complement, not a
  replacement. Never write live order flow.

## THE WORK

### Item 1 — Design (one paragraph in the report)

Cadence source: reuse the lanes daily artifacts (`data/lanes_state.json`
carries per-lane latest returns + regime). Driver = a small module
`strategies/shadow_driver.py` with `step(dry=False)`: read lane results →
compute per-(regime, expert) impact → `router.record()` via router_state
single-writer → call `RegimeRouter.step()` → persist evolved weights through
`write_router_state()`. Cite the exact functions you reuse.

### Item 2 — Implement (sandbox)

- `strategies/shadow_driver.py` (<150 lines), dry-run mode default-on
  (`--dry` prints the would-be accrual + weight deltas; writes nothing).
- Weights that evolve must respect the incumbent guards from
  `evolve_weights.py`: floor share for `rule`, expert cap (0.5), min
  evidence (5) — reuse its constants/functions rather than duplicating.
- A `--once` mode for the cron pattern (`strategies.lanes` already has the
  17:30 weekday crontab; do NOT wire crontab — propose the line in the
  report, human applies).

### Item 3 — Prove it

- Run `--dry` against the REAL caches (read-only) — paste output verbatim:
  per-lane impacts read, would-be weight deltas, no writes.
- Run one real `--once` **in the sandbox data dir only**
  (`--state-dir /home/mrc/opentrader-sandbox/data`) — then show the sandbox
  `live_router_state.json` before/after (schema live_router_state/2, weights
  changed, track preserved).
- Import battery: `python3 -c "import strategies.shadow_driver"` clean.

## CAPS AND RULES

- ≤ 40 tool calls; heartbeat every ~10 to `data/wayfinder/ultimate_chapter.md`
  (`157 heartbeat <N> item:<1|2|3> did:... next:...`).
- Sandbox only; no service restarts; no crontab edits; no commits in live tree.
- Numbers from commands you ran this session only; V01–V20 are `[known]`.
- Blocked >3 attempts → report blocker, move on.
- End: `toc checkpoint --allowance 5000`.

## DELIVERABLES

1. `git -C /home/mrc/opentrader-sandbox diff > /home/mrc/opentrader/data/wayfinder/patches/157.patch`
2. Report: design paragraph, verbatim dry-run + sandbox once-run outputs, proposed crontab line, call count, blockers.
3. Heartbeat line. 4. Proposed gh comment for #157 (do not post).
