# Checkpoint 04 — OpenTrader frontier under ADR-0007

> Created by compaction + verification. Raw log and ledger are the sources of truth.

## Verification notes

- No material issues found.
- Draft is faithful to ledger variables, open questions, and previous checkpoint.
- Variables and Open questions sections replaced with placeholders per tooling note.

## Final checkpoint

## State
Campaign: OpenTrader frontier under ADR-0007. Goal: make ADR-0002 deployability measurable/passing on pinned live universe (511-registry radar → 6-symbol focus) by closing plumbing tickets #155→#157 (improvement loop) and keeping live paper harness faithful (ADR-0001). No raw findings logged yet; no phase has started (plan phases are empty templates). V11 (deployability status) is `[computable]` and must be recomputed from real ledgers at session end, never quoted from prose.

## Decisions
- Victory condition = deployability on pinned universe. Parked (ADR-0007 §7): wide-universe edge claims, marketplace/monetization (#73/#80), C2 transmit, court week (#123–128), UI/cosmetics, new agent-meta tooling.
- ADR-0008: TradeLocker adapter is sanctioned bridge work but sequenced AFTER #155–157 close; do not start it now; no challenge-mode risk reconfig without its own ADR.
- Sandbox-first (`/home/mrc/opentrader-sandbox`); live tree + GPU untouched until validated; never kill/restart harness, gpu-sync, dashboard, or model servers.
- Engine integrity: metrics pre-`1718f33` are optimistic ~4–5pp; never quote uncorrected.
- REGIME KEYS are `up`/`down` (harness maps bull/bear→up/down at attribution, harness.py:2636).
- Cannot self-promote ledger vars to `[known]`; propose via open question for human curation.

## Findings
- Success criteria (checkboxes, all open): #155 regime keys unified to up/down, `live_router_state.json` single-writer, swarm evidence moved /tmp→data/ (sandbox-proven first); #156 HITL promotion-seam decision drafted quoting +1%/0.5%-erosion bar from ADR; #157 recurring shadow driver accrues per-regime impact + calls `RegimeRouter.step()`; ADR-0002 clause status recomputed from real ledgers each session end.
- Deliverables: #155/#157 closed with verbatim command-output proof in ticket; findings appended to `chapters/04-raw/` (append-only); checkpoint at each phase boundary (`toc checkpoint`); ledger status changes → `toc open add`.
- Ledger status: V01–V10, V16–V18, V20 `[known]`; V11, V12, V13, V19 `[computable]`; V14 `[unknowable]`; V15 `[explore]`.

## Dead ends
- V04 ff_falling macro gate: loss-reducer not edge (OOS 1/4 folds); script lost, DISPROVED stands.
- V09 VIX gate edge FALSIFIED (1/3 eras OOS); live runs --vix-gate off (7ed8271); code default strict fail-closed is a footgun.
- V02/V03: universe contract and all existing signal families do not generalize wide under realistic fees.
- V07: epoch engine no-promotion; ADR-0006 phase-2 PASS narrative UNVERIFIED — never repeat.

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
- No phase has been opened yet; plan phase templates are empty, so no phase-boundary checkpoint has fired this session.
- "No raw findings" means `chapters/04-raw/` has no new append this session; all facts above come from the standing scope/ledger, not fresh probes.
- Q03's `toc open add` was not executed by the operator, so it is tracked here as an open question pending formal registration.

## Dropped
- None material; plan template placeholders retained as "no phase opened yet."

---

## Draft (compaction stage)

## State
Campaign: OpenTrader frontier under ADR-0007. Goal: make ADR-0002 deployability measurable/passing on pinned live universe (511-registry radar → 6-symbol focus) by closing plumbing tickets #155→#157 (improvement loop) and keeping live paper harness faithful (ADR-0001). No raw findings logged yet; no phase has started (plan phases are empty templates). V11 (deployability status) is `[computable]` and must be recomputed from real ledgers at session end, never quoted from prose.

## Decisions
- Victory condition = deployability on pinned universe. Parked (ADR-0007 §7): wide-universe edge claims, marketplace/monetization (#73/#80), C2 transmit, court week (#123–128), UI/cosmetics, new agent-meta tooling.
- ADR-0008: TradeLocker adapter is sanctioned bridge work but sequenced AFTER #155–157 close; do not start it now; no challenge-mode risk reconfig without its own ADR.
- Sandbox-first (`/home/mrc/opentrader-sandbox`); live tree + GPU untouched until validated; never kill/restart harness, gpu-sync, dashboard, or model servers.
- Engine integrity: metrics pre-`1718f33` are optimistic ~4–5pp; never quote uncorrected.
- REGIME KEYS are `up`/`down` (harness maps bull/bear→up/down at attribution, harness.py:2636).
- Cannot self-promote ledger vars to `[known]`; propose via open question for human curation.

## Findings
- Success criteria (checkboxes, all open): #155 regime keys unified to up/down, `live_router_state.json` single-writer, swarm evidence moved /tmp→data/ (sandbox-proven first); #156 HITL promotion-seam decision drafted quoting +1%/0.5%-erosion bar from ADR; #157 recurring shadow driver accrues per-regime impact + calls `RegimeRouter.step()`; ADR-0002 clause status recomputed from real ledgers each session end.
- Deliverables: #155/#157 closed with verbatim command-output proof in ticket; findings appended to `chapters/04-raw/` (append-only); checkpoint at each phase boundary (`toc checkpoint`); ledger status changes → `toc open add`.
- Ledger status: V01–V10, V16–V18, V20 `[known]`; V11, V12, V13, V19 `[computable]`; V14 `[unknowable]`; V15 `[explore]`.

## Dead ends
- V04 ff_falling macro gate: loss-reducer not edge (OOS 1/4 folds); script lost, DISPROVED stands.
- V09 VIX gate edge FALSIFIED (1/3 eras OOS); live runs --vix-gate off (7ed8271); code default strict fail-closed is a footgun.
- V02/V03: universe contract and all existing signal families do not generalize wide under realistic fees.
- V07: epoch engine no-promotion; ADR-0006 phase-2 PASS narrative UNVERIFIED — never repeat.

## Open questions
- Q02: Human decision queued — challenge-mode risk contract (plan 1.3); needs own ADR + sandbox walkforward (ADR-0008 §4) before E8/FTUK purchase. Proposed params (0.04 breaker/0.02 stop/0.04 target/0.10 pos/0.25 kelly) HEURISTIC, unvalidated.
- Q03: Paper harness has 0 closed round trips since 2026-08-01 (3 open BUYs only) → clause 1 can't pass on trade evidence; is harness expected to close positions, or is 70-day calendar clock (clause 3, currently 0 continuous days due to gaps) binding? (Operator wrote in deployability_status.json but did NOT execute `toc open add`.)

## Variables (unchanged from ledger)
V01 [known] Rule floor contract 17-sym: +23.1% net 5y pre-1718f33, +18.6% post-fix (~4-5pp optimistic) — bounds: data/setup_search/ledger.jsonl; best.json.
V02 [known] Universe contract no-generalize: -45.95% 511-registry, -41.07% 7.3k fullcross (2026-08-23) — bounds: scripts/universe_contract_test.py (~25 min).
V03 [known] No existing signal family generalizes wide (2026-08-13) — bounds: scripts/signal_family_probe.py (~20 min).
V04 [known] ff_falling loss-reducer, not edge; script lost 2026-08-23 — bounds: AGENTS.md.
V05 [known] Contrarian rotation beats B&H 3/4 folds 2008-26 (9.1% vs 6.8% ann); crisis tool not standalone; script lost — bounds: AGENTS.md.
V06 [known] 9 experts OOS-verified; laggard is champion (Calmar 1.666, maxDD -7.5%); ROUTING/MONITORING only; swarm pkl lost, strategies/ ports durable — bounds: strategies/experts.py; data/live_router_state.json.
V07 [known] Epoch no-promotion (+0.945%/+0.533% vs +1%; erosion 1.006%>0.5%) — bounds: data/arena/epoch_report.json.
V08 [known] DD control 6/8 R2 intl; intl basket Calmar 0.73 vs SPY 0.47; benchmark = SPY net costs; scripts lost — bounds: AGENTS.md.
V09 [known] VIX gate falsified; live off (7ed8271); default fail-closed footgun — bounds: data/vix_gate.py; 7ed8271.
V10 [known] Arena gate FAILING (-0.57%/+0.20% vs +1%, 2026-08-23); loop seeded once, not closed (#155-157 open) — bounds: docs/agents/research/self-improvement-loop-audit.md.
V11 [computable] Deployability vs ADR-0002 3 clauses — recompute from ledgers each session end — bounds: docs/adr/0002-deployability-criterion.md; paper_state.json + shadow reconciliation.
V12 [computable] FTMO Phase-1 ~939 days/44 trades; re-run only on config change — bounds: setup_search/prop_challenge_sim.py.
V13 [computable] Live universe = 511-registry radar → 6 focus (fallback ~66); 19-symbol phrasing stale — bounds: mot/industry_map.py; docs/agents/research/universe-bridge-matrix.md.
V14 [unknowable] WHY contract fails wide — parked ADR-0007 track, don't burn tokens guessing — bounds: docs/adr/0007 decision 3.
V15 [explore] Macro/sector-relative signal inputs generalize wide — untested, speculation — bounds: ADR-0007 decision 3; signal_family_probe.py.
V16 [known] FTUK One-Step (2026-08-29): 10% target/4% daily DD/8% RELATIVE max DD/min 4 days/no time limit/80% split/$250 min; Flex differs (4% target/5% daily) — bounds: faq.ftuk.com; plan 1.2.
V17 [known] E8 Signature 25K (2026-08-29): fee ~$110 FUT/~$138 CFD; EOD dynamic DD 4%; ~6% target; 35% best-day payout; buffer=DD size; 80% split; CFD 60-day activity clock — bounds: e8markets.com; plan 1.2.
V18 [known] TradeLocker class satisfies no-inactivity-clock (FTUK/FunderPro/E8 no time limits); FunderPro trust caution (Trustpilot Jan 2026) — bounds: plan 1; fundedtrading.com.
V19 [computable] Plan pass-prob/income (15-25%, $425-1068/mo) HEURISTIC; recompute via prop_challenge_sim.py before purchase — bounds: setup_search/prop_challenge_sim.py; plan 4.
V20 [known] ADR-0008 (2026-08-29): multi-venue; FTMO sim-primary, TradeLocker added; adapter after #155-157, sandbox-first; challenge-mode reconfig needs own ADR — bounds: docs/adr/0008-multi-venue-prop-bridge.md.

## Assumptions
- No phase has been opened yet; plan phase templates are empty, so no phase-boundary checkpoint has fired this session.
- "No raw findings" means `chapters/04-raw/` has no new append this session; all facts above come from the standing scope/ledger, not fresh probes.
- Q03's `toc open add` was not executed by the operator, so it is tracked here as an open question pending formal registration.
