# Off-course assessment — GLM-5.3 "80% off course" claim, checked against the ledgers

- **Date:** 2026-08-29
- **Trigger:** user reported a discussion with GLM-5.3 in which that model
  assessed the project as "roughly 80% off course". This document records what
  is actually off course, measured against the project's own score function
  (ADR-0007 §1: ADR-0002 deployability on the pinned universe), and what the
  claim gets wrong.
- **Method:** every datum below is transcribed from a ledger or command output
  of this session (V11 recompute run, 2026-08-29), not from prose.

## 1. What the score function says (the yardstick)

ADR-0002 deployability, all three clauses required:

1. **Plumbing fidelity** — ≥3 closed paper trades spanning ≥2 distinct exit
   paths, zero fatal defects, reconciliation <0.1%.
2. **Edge persistence** — shadow up-regime rule-floor edge ≥+0.9% mean
   per-trade impact, not decayed in the latest window.
3. **Calendar floor** — ≥10 weeks (70 days) continuous paper.

ADR-0007 adds the process gate: every session must move a clause, close
#155–157, advance the FTMO bridge, or produce a passing generalization probe.

## 2. Measured state (V11 recompute, 2026-08-29)

| Clause | Measured | Status |
|---|---|---|
| 1. Plumbing | 0 closed round trips (3 open BUYs: BTC/ETH/SOL, all 2026-08-29T19:22); 0 fatal defects in last 500 journal lines; main-vs-shadow cash delta 0.02 | **FAIL** (0/3 closed trades; no exit paths exercised) |
| 2. Edge | `track.up.rule` sum=1.74, n=5 → mean 0.348 (transcribed verbatim from `live_router_state.json`) | **NOT MEASURABLE** — this is forward-lane evidence since 2026-08-14, not the ADR-0002 +0.9% shadow measure; #157 shadow driver does not exist yet |
| 3. Calendar | first paper ts 2026-08-01T04:14Z (oldest `data/history/cycle_*.json` mtime); 10 gaps >24h in 28.6 days, largest 117.8h (Aug 6→11) | **FAIL** — 0 continuous days vs 70 required |

**Score: 0 of 3 clauses pass; 1 of 3 is not even measurable.**

## 3. What is genuinely off course (the claim's valid core)

1. **The critical path stalled for 16 days.** ADR-0007 (2026-08-28) itself
   records that four agent campaigns (Aug 13–28) produced work feeding no gate
   — dashboards, TUI, agent tooling, monetization plumbing, model
   self-benchmarks — while #155–157 sat open. Git history confirms the
   pattern: the last ~15 pre-ADR-0007 commits are dominated by dashboard
   cosmetics (`184b133`, `c75a72b`, `3433526`, `383476e`, `eba21ed`) and
   agent-meta tooling, not loop plumbing.
2. **Clause 2's mechanism does not exist.** #157 (recurring shadow driver that
   accrues per-regime impact and calls `RegimeRouter.step()`) is still open.
   Until it runs, the deployability gate's edge clause is structurally
   unmeasurable — the project cannot pass its own score function by
   construction.
3. **The paper harness is not generating the evidence clause 1 needs.** 0
   closed trades in 28 days of paper; the harness holds 3 open positions and
   the Coach reports "only 0 trades, need 5+ for review". The 14-day-hold
   exit path (94% of backtest exits per ADR-0002) has never been exercised
   live.
4. **The calendar clock is broken by gaps.** 10 gaps >24h in under a month
   (harness downtime Aug 6→11 alone is ~5 days). Even with zero further
   gaps, the 70-day floor cannot be met before ~2026-10-10 at the earliest,
   and only if continuity holds.
5. **The live tree is dirty.** 75 untracked files + 3 modified tracked files
   in `/home/mrc/opentrader` (accumulator, gpu_*, falsify, hive, overnight
   stages, research docs, ADR-0006 itself untracked). The triage (2026-08-28)
   had already flagged ~46 modified tracked files from Aug 11–18 as
   uncommitted (#122); that batch has not landed.
6. **Governance artifacts are partially uncommitted.** `docs/adr/0006-deepseek-pillars.md`
   is untracked; the ToC workspace (the ADR-0007 §6 claims registry) is
   tracked but its checkpoints/ dir is untracked.

## 4. What the "80%" claim gets wrong or overstates

1. **The project is not off course relative to its own (corrected) plan.**
   ADR-0007 (2026-08-28) *is* the off-course diagnosis — it was written
   precisely because the Aug 13–28 work fed no gate. Since that ADR, the
   direction is pinned and the work has followed it: #155 closed
   (`3ebb306`), ToC governance live (V01–V20, Q01/Q02), V11 recompute
   executed and checkpointed (`ckpt-01.md`, verification clean), ADR-0008
   multi-venue posture recorded. The "off course" period is real but it is
   the *pre-ADR-0007* period, and the project already self-corrected.
2. **"80%" is not a number the ledgers support.** No ledger variable
   quantifies off-course-ness. The defensible statement is: 0/3 deployability
   clauses pass, 1/3 unmeasurable, critical path (#157) open, calendar clock
   reset by gaps. That is a *stalled* project, not a *misdirected* one —
   the distinction matters because ADR-0007 already fixed the direction.
3. **The edge is not "wrong" — it is unproven at the required bar.** The
   rule-floor contract is universe-bound (V02: −45.95% on 511-registry,
   −41.07% on 7.3k fullcross) and the validated edges are structural
   regime-switching (V06: laggard OOS Calmar 1.666). The shadow's 0.348
   mean impact is below the +0.9% bar, but it is the wrong measurement
   (forward lane, n=5) — the honest status is "not measurable", not
   "edge failed".
4. **Plumbing is actually clean.** 0 fatal defects in the last 500 journal
   lines; main/shadow reconcile to 0.02. Clause 1 fails on *trade volume*,
   not on *fidelity* — the system is faithful, just not yet trading enough
   to prove it.

## 5. Net assessment

The GLM-5.3 claim is **directionally right about the period Aug 13–28**
(most of that work fed no gate — the project's own ADR-0007 says so) and
**right that the deployability gate is far from passing** (0/3 clauses).
It is **not supported as a current-state verdict**: as of 2026-08-29 the
project is on its corrected course, the direction is pinned, and the
binding constraints are (a) #157 does not exist, (b) the paper harness has
produced no closed trades, (c) the calendar clock has 10 gaps and ~55+ days
of continuity still to accrue.

**The honest one-liner:** the project is not 80% off course — it is ~80% of
the way to *measurability*, and 0% of the way to *passing*. The off-course
work already happened, was diagnosed (ADR-0007), and was corrected; what
remains is execution of #157 and letting the paper clock run continuously.

## 6. What would move the score (in order)

1. **#157 shadow driver** (prototype) — makes clause 2 measurable. Highest
   leverage; without it the gate is unpassable by construction.
2. **Continuous harness uptime** — close the gap pattern (10 gaps in 28 days);
   the 70-day clock only accrues while it runs.
3. **Let positions close** — 3 open BUYs since 19:22 today; the harness needs
   to exercise exit paths (stop/target/14-day hold) to accrue clause-1
   evidence. No intervention needed; this is a time + market function.
4. **#122 commit batch** — land the dirty tree so the audit gate has a clean
   baseline.
5. **#156 promotion path** (HITL grilling) — the seam that makes the loop
   mean anything; sequenced after #155/#157 exist.

## Provenance

- `data/wayfinder/deployability_status.json` (V11 recompute, this session)
- `data/wayfinder/toc/` ledger V01–V20, Q01/Q02; `checkpoints/ckpt-01.md`
- `docs/adr/0002-deployability-criterion.md`, `docs/adr/0007-reground-victory-path.md`
- `docs/agents/triage-2026-08-28.md`, `docs/agents/handoff-ultimate.md`
- `git log` / `git status` of `/home/mrc/opentrader` (2026-08-29)
- `data/live_router_state.json` (track.up.rule: sum=1.7399999999999998, n=5)
- `data/paper_state.json`, `data/shadow_scaled/paper_state.json`
- `data/history/cycle_*.json` mtimes (261 files, 2026-08-01 → 2026-08-29)
