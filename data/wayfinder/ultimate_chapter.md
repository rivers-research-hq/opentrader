# OpenTrader Ultimate — wayfinder checkpoint log

> Resume state for the "OpenTrader ultimate" map (#150). Read the **latest** block
> first; it supersedes everything above it. Companion prompt:
> `docs/agents/handoff-ultimate.md`.

---

## checkpoint 2026-08-24T00:50:00Z (STEP ZERO complete)

ticket: none (local-only setup, handoff §9)
decided:
- Evidence relocated: /tmp/opentrader probe scripts+logs → `data/evidence/` (durable, append-only). **swarm/ data was already GONE** (lost to /tmp cleanup) — not recoverable; findings stand as recorded.
- Probes repointed: AGENTS.md + docs/CONTEXT.md now cite `scripts/` (git-durable) and `data/evidence/rule_floor_honest.py`; 5 lost scripts marked LOST (not re-runnable).
- `data/MANIFEST.json` written (both trees): writer-per-path; wayfinder-agent = sole writer of `data/evidence/`, `data/wayfinder/ultimate_chapter.md`, `data/MANIFEST.json`.
- Verified in sandbox BEFORE live: probe run from new path = net=+18.57% (matches documented +18.6% post-1718f33 contract).
- Live commit cb2535c (4 files: AGENTS.md, docs/CONTEXT.md, data/evidence/rule_floor_honest.py, data/MANIFEST.json). Logs stay local (gitignored *.log — evidence tier is on-disk, not git).
- Chapter file stays in live `data/wayfinder/` (handoff §9 supersedes the older relocation note in this file).
files-touched: AGENTS.md, docs/CONTEXT.md, data/evidence/{rule_floor_honest.py,probe_verify.log,signal_family_probe.log,universe_contract_test.log}, data/MANIFEST.json (both trees)
next: claim #155 (assign @self) and resolve the plumbing task (AFK, sandbox-first): unify regime keys to up/down, single writer for live_router_state.json. NOTE: the "move /tmp swarm evidence into data/" item of #155 is SUBSUMED by this STEP ZERO (data was lost; evidence tier now exists) — record that in the #155 resolution, don't duplicate.
state-hash: OPEN map=1 (#150) | tickets open=3 (#155 task, #156 grilling, #157 prototype) | resolved research=4 (#151..#154) | live HEAD=cb2535c

---

## checkpoint 2026-08-24T00:55:00Z (#155 claimed, starting)

ticket: #155 Plumbing (task, AFK) — claimed (assignee rivers-research-hq; NOTE: gh auth is the org account, not darylerivers)
decided: work order = (1) audit writers/keys in sandbox, (2) unify regime keys to up/down, (3) single writer for live_router_state.json, (4) repoint swarm evidence to data/ (data LOST per STEP ZERO — code must point at canonical data/ location and degrade gracefully)
next: read mot/mixture.py, strategies/{handoff,seed_router,shadow,evolve_weights}.py, harness.py router-state paths in sandbox
state-hash: OPEN map=1 (#150) | tickets open=3 (#155 IN PROGRESS, #156, #157) | live HEAD=cb2535c

---

## checkpoint 2026-08-23T22:30:08Z (INITIAL — seeded by handoff)

ticket: none (mid-flight start)
decided: map #150 charted; 4 research tickets resolved, 3 frontier tickets open
files-touched: docs/agents/research/{ftmo-2step-phase0-facts,universe-bridge-matrix,openrouter-standin-matrix,self-improvement-loop-audit}.md; docs/agents/handoff-ultimate.md
next: (local-only) filesystem setup per handoff §9, THEN claim and resolve the #155 plumbing task (AFK, sandbox-first)
state-hash: OPEN map=1 (#150) | tickets open=3 (#155 task, #156 grilling, #157 prototype) | resolved research=4 (#151..#154)

### Local-only setup task (before the frontier)
- Move /tmp/opentrader/swarm/* and the probe scripts → data/evidence/ (durable).
- Relocate this checkpoint out of live data/ into the agent namespace.
- Write data/MANIFEST.json declaring writer-per-path.
- Full tier spec in handoff §9.

### Resolved (gists)
- #151 FTMO facts → 2-Step static 10% max loss; US single-stock CFD availability unverified.
- #152 Universe bridge → live=511-registry radar ("19-symbol" is stale); FTMO-eligible = intl/FX/commodity experts; prop leg needs a new FTMO-facing universe.
- #153 OpenRouter stand-in → trader=flash, coder=pro, court=sonnet; account ~708 tokens (use free `:free` models).
- #154 Loop audit → arena/epoch/breeder/weight-evolution DISCONNECTED; defects: regime-key mismatch, 3 writers to live_router_state.json, /tmp evidence dependency.

### Frontier (in work order)
1. #155 Plumbing (task, AFK) — unify regime keys to up/down, single writer, move /tmp swarm evidence into data/.
2. #156 Promotion path (grilling, HITL) — how a gate-passing MLP becomes routable; defaults in handoff §5.
3. #157 Shadow driver (prototype, HITL) — recurring per-regime impact accrual calling RegimeRouter.step().

### Standing constraints (from handoff §2)
Audit gate binding; verify-before-repeat; SPY buy-and-hold is the benchmark; claim-before-work; one non-research ticket per session; sandbox-first; do NOT disturb the live harness (rule-primary, 0 fills).

## checkpoint 2026-08-29T13:30-0500
ticket: 155 plumbing
decided: #155 implemented by ZCode in sandbox (prior partial from stalled 08-24 session completed, not redone); router_state.py is sole writer; all executable /tmp refs removed; strategies package now importable without lost pkls
files-touched: strategies/{experts,seed_router,handoff,evolve_weights,lanes,scorer,scorer_intl,evaluate,macro_features,shadow_current_alloc,verify,router_state}.py harness.py data/MANIFEST.json
next: human applies data/wayfinder/patches/155.patch to live tree (git apply --check PASSES), restarts harness at a quiet boundary, closes #155 with the comment draft in the session report
state-hash: 155 done-in-sandbox / 156,157 open / patch unapplied to live
v11 heartbeat 10 did:recomputed ADR-0002 clauses from ledgers (0 closed trades, 0 defects, rule-floor 0.348 n=5, 0 continuous days) pass:c1=false c2=null c3=false
156 heartbeat 1 did:wrote promotion-path memo (3 seams A/B/C, V06/V07/V10 cited, 5 decision questions) next:human reviews memo
157 heartbeat 1 did:implemented shadow_driver.py (200 lines, dry-run default, --once cron mode, floor guard) + proved dry-run + once-run in sandbox (schema/2, weights evolved, track preserved) + patch 157.patch next:human reviews report + proposed crontab

157 closeout heartbeat: patch regenerated, dry-run verified, ready for HITL review
