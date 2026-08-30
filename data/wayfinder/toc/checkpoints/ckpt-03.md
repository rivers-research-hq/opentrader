# Checkpoint 03 — OpenTrader frontier under ADR-0007

> Created by compaction + verification. Raw log and ledger are the sources of truth.

## Verification notes

- Draft "Dropped" section incorrectly lists V05, V08, V12, V14, V15, V17, V19 as dropped; these are active ledger variables and must not be marked dropped.
- Draft "State" omits the specific ticket scope details for #155 (regime keys, single-writer, evidence relocation) present in the previous checkpoint; restored for fidelity.
- Draft "Decisions" omitted the explicit "Sandbox-first" and "Live tree untouched" constraints as a distinct decision point; merged into State/Assumptions in the final to match previous checkpoint structure.
- No material conflicts between Ledger and Raw Log (Raw Log is empty).
- Variables and Open questions restored verbatim by tooling; placeholders emitted.

## Final checkpoint

## State
Session is at the **start** of the ADR-0007 campaign (tickets #155–#157 open, no work performed yet). The working tree is the sandbox at `/home/mrc/opentrader-sandbox`; live tree, GPU, harness, gpu-sync, dashboard, and model servers are untouched and must remain so. No phase has been opened; no raw findings have been logged to `chapters/04-raw/`; no `toc checkpoint` has been taken. The plan section is still the blank template (Phase 1/2 unnamed, no steps). The immediate next action is to draft Phase 1 (closing #155: unify regime keys to `up`/`down`, make `live_router_state.json` single-writer, move swarm evidence from `/tmp` to `data/`, sandbox-proven first) and open it with `toc phase start`.

## Decisions
- Victory condition is deployability on the pinned 511-registry→6-symbol universe; all out-of-scope tracks (wide-universe edge, #73/#80 monetization, C2 transmit, #123–128 court week, UI, agent-meta tooling) are parked per ADR-0007 §7.
- TradeLocker adapter (ADR-0008) is sanctioned but sequenced strictly AFTER #155–#157 close; do not start it now.
- Challenge-mode risk reconfiguration requires its own ADR (ADR-0001) — not in this campaign.
- Numeric discipline: only `[known]` ledger values may be quoted (with bounds); everything else is `[computable]` (probe, record command+output in `chapters/04-raw/`) or "unknown".
- Regime keys are `up`/`down` (harness maps bull/bear→up/down at attribution, harness.py:2636).
- Any pre-`1718f33` engine metric is optimistic ~4–5pp and must never be quoted uncorrected.

## Findings
- No new findings this session; all standing facts are carried in the ledger below.

## Dead ends
- ff_falling macro gate as validatable edge — DISPROVED (V04).
- VIX gate edge — FALSIFIED (V09).
- ADR-0006 phase-2 PASS narrative — UNVERIFIED, do not repeat (V07).
- Why the contract fails wide — parked as research track, do not burn tokens guessing (V14).

## Open questions (ledger, verbatim)

- Q02: Human decision queued: challenge-mode risk contract (per small-capital plan 1.3) — requires its own ADR + sandbox walkforward per ADR-0008 s4 before any E8/FTUK purchase. Proposed params (0.04 breaker / 0.02 stop / 0.04 target / 0.10 pos / 0.25 kelly) are HEURISTIC, unvalidated
- Q03: Q03 (from V11 run, added by orchestrator 2026-08-29 — operator wrote it in deployability_status.json but did not execute toc open add): paper harness has 0 closed round trips since 2026-08-01 (3 open BUY positions only) — clause 1 cannot pass on trade evidence; is the harness expected to close positions at this stage, or is the 70-day calendar clock the binding constraint (clause 3, currently 0 continuous days due to gaps)?

## Variables (ledger, verbatim)

- V01 [known] Rule floor contract (ledger iter-74) on 17-symbol search universe: +23.1% net 5y pre-1718f33, +18.6% after engine fix (metrics pre-fix optimistic ~4-5pp) — bounds: data/setup_search/ledger.jsonl; data/setup_search/best.json
- V02 [known] Universe contract does NOT generalize: -45.95% on 511-registry, -41.07% on 7.3k fullcross (re-verified 2026-08-23). Treat every edge claim as universe-bound — bounds: scripts/universe_contract_test.py (~25 min)
- V03 [known] Signal-family probe: NO existing feature family (mom/rev/rsi/brk/z, rank, vol-scaling, filters) generalizes wide under realistic fees (2026-08-13); only new signal inputs untested — bounds: scripts/signal_family_probe.py (~20 min)
- V04 [known] ff_falling macro gate is a loss-reducer, NOT a validatable edge (OOS walkforward 1/4 folds positive); dedicated script lost to /tmp cleanup 2026-08-23, DISPROVED verdict stands — bounds: AGENTS.md quantitative-claims section
- V05 [known] Contrarian rotation: long worst-5 by 60d momentum in liquid large-caps beats B&H 3/4 folds 2008-26 (9.1% vs 6.8% ann); a crisis-rotation tool, not a standalone edge; script lost 2026-08-23 — bounds: AGENTS.md quantitative-claims section
- V06 [known] 9 prototype experts OOS-verified; laggard is champion (OOS Calmar 1.666, maxDD -7.5%). ROUTING/MONITORING only, never live order flow. Swarm pkl data lost; committed ports in strategies/ are the durable artifacts — bounds: strategies/experts.py; data/live_router_state.json
- V07 [known] Epoch engine verdict: no-promotion. Both epochs FAIL (+0.945%/+0.533% vs +1% gate; epoch2 erosion 1.006% > 0.5%). ADR-0006 phase-2 PASS narrative is UNVERIFIED - never repeat it — bounds: data/arena/epoch_report.json
- V08 [known] Transfer findings: drawdown control passes 6/8 of R2 intl gauntlet; intl basket BH beats SPY BH risk-adjusted (Calmar 0.73 vs 0.47); THE benchmark is SPY buy-and-hold net of costs. Scripts lost 2026-08-23, findings stand as recorded — bounds: AGENTS.md quantitative-claims section
- V09 [known] VIX gate edge FALSIFIED (1/3 eras OOS). Live harness runs --vix-gate off (commit 7ed8271); code default remains strict fail-closed - a footgun for future runs — bounds: data/vix_gate.py docstring; commit 7ed8271
- V10 [known] Arena gate FAILING (-0.57%/+0.20% vs +1% bar, 2026-08-23 audit); improvement loop seeded once from static OOS evidence, does not close (#155-157 open) — bounds: docs/agents/research/self-improvement-loop-audit.md
- V11 [computable] Deployability status vs ADR-0002 three clauses - MUST be recomputed from real ledgers at session end, never quoted from prose — bounds: docs/adr/0002-deployability-criterion.md; paper_state.json + shadow reconciliation
- V12 [computable] FTMO Phase-1 cadence ~939 days / 44 trades at current trade frequency (ADR-0005 sandbox sim); re-run only if the config changes — bounds: setup_search/prop_challenge_sim.py
- V13 [computable] Live harness universe is the 511-registry industry radar curated to 6 focus symbols (fallback ~66 names); the 19-symbol-universe phrasing in CONTEXT.md/AGENTS.md/experts.py is stale boilerplate — bounds: mot/industry_map.py; docs/agents/research/universe-bridge-matrix.md
- V14 [unknowable] Mechanism of WHY the contract fails wide (regime fragmentation vs fee structure vs selection effect) - parked as the ADR-0007 research track, do not burn tokens guessing — bounds: docs/adr/0007-reground-victory-path.md decision 3
- V15 [explore] Macro-relative / sector-relative signal inputs generalize wide - untested hypothesis, speculation only until probed — bounds: ADR-0007 decision 3; scripts/signal_family_probe.py conclusion
- V16 [known] FTUK One-Step rules (official FAQ, spot-checked 2026-08-29): 10% target / 4% daily DD / 8% RELATIVE max DD / min 4 days / no time limit / 80% split / on-demand payout $250 min. Relative != trailing (friendlier). Newer Flex variant differs (4% target, 5% daily DD) - re-verify before quoting — bounds: faq.ftuk.com one-step rules; docs/research/small-capital-profitability-plan.md 1.2
- V17 [known] E8 Signature 25K (spot-checked 2026-08-29): fee ~$110 FUTURES / ~$138 CFD (plan conflated variants); EOD dynamic DD 4% on 25K/50K; ~6% target; 35% best-day payout rule; payout buffer = DD size; fixed 80% split on Signature; CFD requires activity every 60 days (a clock) — bounds: e8markets.com compare-simfi; help.e8markets.com payout-on-demand; plan 1.2
- V18 [known] TradeLocker venue class satisfies the no-inactivity-clock constraint that drove ADR-0005 to FTMO: FTUK/FunderPro/E8 have no time limits with static/relative DD. FunderPro carries a trust caution (Trustpilot Jan 2026, payout-denial complaints) — bounds: docs/research/small-capital-profitability-plan.md 1; fundedtrading.com best-tradelocker-prop-firms
- V19 [computable] Plan pass-probabilities and income figures (15-25% pass, $425-1068/mo) are HEURISTIC - decision inputs only. Recompute by extending setup_search/prop_challenge_sim.py to venue-specific rules before any purchase decision — bounds: setup_search/prop_challenge_sim.py; plan 4
- V20 [known] ADR-0008 (2026-08-29): multi-venue posture - FTMO stays sim-validated primary, TradeLocker firm class added. TradeLocker ExchangeBase adapter is sanctioned bridge work, sequenced AFTER #155-157, sandbox-first, demo-paper-validated. Challenge-mode risk reconfig requires its own ADR (ADR-0001) — bounds: docs/adr/0008-multi-venue-prop-bridge.md

## Assumptions
- Sandbox tree is current and in sync enough to begin #155; will verify before mutating.
- `live_router_state.json` currently has multiple writers and swarm evidence lives in `/tmp` (per #155 ticket); to be confirmed by inspection.

## Dropped
- None material; plan template placeholders retained as "no phase opened yet."

---

## Draft (compaction stage)

## State
Session is at the start of the OpenTrader frontier campaign under ADR-0007. No work has been executed yet in this window; the raw findings log is empty. The objective is to close tickets #155 (regime key unification + single-writer state + evidence relocation), #156 (HITL promotion-seam decision draft), and #157 (recurring shadow driver prototype calling `RegimeRouter.step()`), then recompute ADR-0002 deployability status from real ledgers. The live paper harness is running but has 0 closed round trips since 2026-08-01 (3 open BUY positions), which blocks clause 1 of ADR-0002. Arena gate is FAILING (-0.57%/+0.20% vs +1% bar). The improvement loop is seeded but does not close because #155–157 remain open. All work must be sandbox-first (`/home/mrc/opentrader-sandbox`); live tree and GPU are untouched until validated.

## Decisions
- ADR-0007 pins the victory condition: deployability on the 511-registry radar → 6-symbol focus universe. Wide-universe edge, marketplace, C2 transmit, court week, UI, and agent-meta tooling are parked.
- ADR-0008 sanctions the TradeLocker adapter as bridge work but sequences it AFTER #155–157 close. Do not start it now.
- Challenge-mode risk reconfiguration requires its own ADR (ADR-0001); proposed params are heuristic and unvalidated (Q02).
- Regime keys are `up`/`down` (harness maps bull/bear at attribution, harness.py:2636).
- Engine integrity: any metric from pre-`1718f33` engine is optimistic ~4–5pp; never quote without correction.

## Findings
- V01: Rule floor contract on 17-symbol universe: +23.1% net 5y pre-fix, +18.6% post-fix.
- V02: Universe contract does NOT generalize: -45.95% on 511-registry, -41.07% on 7.3k fullcross.
- V06: 9 prototype experts OOS-verified; laggard is champion (OOS Calmar 1.666, maxDD -7.5%). Routing/monitoring only.
- V07: Epoch engine verdict: no-promotion. Both epochs FAIL vs +1% gate; epoch2 erosion 1.006% > 0.5%.
- V10: Arena gate FAILING (-0.57%/+0.20% vs +1% bar). Improvement loop seeded once, does not close.
- V13: Live harness universe is 511-registry radar curated to 6 focus symbols; 19-symbol phrasing in docs is stale.
- V16–V18: FTUK One-Step, E8 Signature 25K, and TradeLocker venue rules spot-checked 2026-08-29.
- V20: ADR-0008 multi-venue posture active; TradeLocker adapter sequenced after #155–157.

## Dead ends
- ff_falling macro gate: loss-reducer only, not validatable edge (V04).
- VIX gate edge: FALSIFIED 1/3 eras OOS (V09).
- No existing signal family generalizes wide under realistic fees (V03).

## Open questions
- Q02: Challenge-mode risk contract needs its own ADR + sandbox walkforward before any E8/FTUK purchase.
- Q03: Paper harness has 0 closed round trips since 2026-08-01; clause 1 cannot pass on trade evidence. Is the harness expected to close positions now, or is the 70-day calendar clock (clause 3, currently 0 continuous days) the binding constraint?

## Variables (unchanged from ledger)
V01 [known], V02 [known], V03 [known], V04 [known], V05 [known], V06 [known], V07 [known], V08 [known], V09 [known], V10 [known], V11 [computable], V12 [computable], V13 [computable], V14 [unknowable], V15 [explore], V16 [known], V17 [known], V18 [known], V19 [computable], V20 [known].

## Assumptions
- The 6-symbol focus universe is the correct pinned set for this campaign.
- Sandbox validation must precede any live-tree changes.
- The +1%/0.5%-erosion bar for promotion is quoted from the ADR, not prose.
- No ledger status changes will be made without human/orchestrator curation.

## Dropped
- Full text of V05, V08, V12, V14, V15, V17, V19 details (retained in ledger; not needed for immediate next steps).
- Plan phases are still blank; no phase has been started yet.
