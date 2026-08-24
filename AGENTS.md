# AGENTS — OpenTrader

OpenTrader is a self-improving trading system: a Mixture of Traders (rule floor +
value-head experts) trained by an adversarial arena. Read `ARCHITECTURE.md` and
`CONTEXT.md` before working — they are the single sources of truth for design and
language. All changes are proven in the sandbox (`opentrader-sandbox`) first; the
live tree and the GPU stay untouched until validated.

## Agent skills

### Issue tracker

Issues live as GitHub issues on `darylerivers/opentrader` (gh CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles, labels equal to their names: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` (glossary) + `docs/adr/` at the repo root, with
`ARCHITECTURE.md` as the canonical design doc. See `docs/agents/domain.md`.

## Quantitative claims — verify before repeating (binding)

No numeric claim about the rule floor, a config, a gate, or an "edge" is trusted
from prose. Before repeating or acting on one, re-run it:

- **Rule floor / any config on the full archive**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 /home/mrc/opentrader/data/evidence/rule_floor_honest.py` (repo's own `run_backtest`, 5y, all configs side by side).
- **Universe generalization**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 /home/mrc/opentrader/scripts/universe_contract_test.py` — same contract on the 511-registry (466 ∩ archive) and the 7.3k-symbol fullcross archive (~25 min). The contract does NOT generalize beyond the 17 search names (−45.95% registry, −41.07% wide — re-verified 2026-08-23 on the regenerated archive; was −37.8%/−40.4% on the 2026-08-13 archive); treat any "edge" claim as universe-bound until proven otherwise.
- **Signal-family probe**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 /home/mrc/opentrader/scripts/signal_family_probe.py` — screens every feature family the engine already has (mom/rev/rsi/brk/z blends, rank, vol-scaling, filters) on the 5y-wide universe (~20 min). Result (2026-08-13): NO existing family generalizes under realistic fees; only new signal inputs (macro/sector-relative) are untested paths.
- **Macro-regime probe**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 /home/mrc/opentrader/scripts/macro_regime_probe.py` — FRED entry gates (`run_backtest(..., macro_gate=...)`, default off) across the promising families. ONE lead (2026-08-13): incumbent + `ff_falling` (long only while Fed Funds < 60d-ago level) flips 5y-wide from −41.8% → +6.2% (PF 1.07, 124 trd). **OOS walkforward DISPROVES it as an edge (1/4 folds positive) — it is a loss-reducer, not a validatable edge.** Do NOT repeat as a claim of edge. (The dedicated walkforward script was lost to /tmp cleanup 2026-08-23; the DISPROVED verdict stands as recorded — treat as closed.)
- **Wide-gated search**: `setup_search/loop.py --wide-eval --wide-min 0.0 --wide-min-trades 8 --wide-max-fee-ratio 0.5` — standing promotion requirement (5y-wide net ≥ 0, ≥ 8 wide trades, fees ≤ 50% of account). No config may become best.json without passing it. Run from the sandbox; `data/setup_search/wide_aligned_1300b.pkl` is the cached wide set.
- **Cross-asset test (2026-08-13; script LOST to /tmp cleanup 2026-08-23 — finding stands as recorded, not re-runnable)**: long-horizon (60d trend/hold) timing across 13 asset-class proxies vs SPY buy-and-hold net of costs. Result: buy-and-hold beats every variant. THE benchmark is SPY buy-and-hold net of costs, not "beat iter-74".
- **International test (2026-08-13; script LOST to /tmp cleanup 2026-08-23 — finding stands as recorded, not re-runnable)**: 10 intl assets, no-lookahead. No active edge, BUT intl basket BH beats SPY BH risk-adjusted (Calmar 0.73 vs 0.47) — diversification, not selection, is the measurable edge.
- **Engine integrity (commit 1718f33)**: `run_backtest` decisions use prior close, fills use current close (no same-bar lookahead). Any metric computed with the pre-1718f33 engine is optimistic by up to ~4-5pp (iter-74 +23.1%→+18.6%). Re-verify before quoting old numbers.
- **Contrarian finding (2026-08-13)**: long the WORST-5 by 60d momentum within liquid large-caps (no macro gate) beats buy-and-hold 3/4 folds over 2008-26 (9.1% vs 6.8% ann). It is a ROTATION tool — wins crisis windows, loses smooth bulls. Momentum-top is the bull tool. The arena should learn the regime switch between them, NOT a single signal. Script LOST to /tmp cleanup (2026-08-23); finding stands as recorded, not re-runnable.
- **Tournament swarm (R1/R1b/R1c, 2026-08-13; swarm data + agent scripts LOST to /tmp cleanup 2026-08-23 — findings stand as recorded, not re-runnable)**: escalating-bar cull + OOS gauntlet. Verified leaders (US 2008-26, Calmar): spectral 1.071, copula 0.904, hurst 0.884, entropy 0.832, momtrend 0.469->0.938 OOS, multiasset 0.39->1.289 OOS. Roster has 6 prototype experts (momtrend, multiasset, spectral, copula, hurst, entropy). The committed `strategies/` ports (entropy/bayes/kalman/spectral/laggard) are the durable artifacts — they reference the lost swarm .pkl data and are currently unimportable (defect, plumbing ticket). Key rule all agents confirmed: **gate-entries-only; forced exits / trailing stops / soft de-risk destroy returns.** NOT wired to live harness (different universe).
- **R2 OOS gauntlet (2026-08-13)**: 6/8 abstract winners transfer to intl symbols (fixed params). PASS: bayes 1.148, spectral 1.000, kalman 0.988, hurst 0.967, wavelet 0.803, entropy 0.667 (OOS Calmar vs intl basket 0.501). FAIL: hmm (posterior-prob threshold not scale-free across universes), copula (marginal; intl lacks bond safe-haven; book-only variant passed). Universal transfer = drawdown control, not raw return — every passing strategy trails equal-weight basket in 2023-26 bull. Details file LOST to /tmp cleanup (2026-08-23); the PASS/FAIL list above stands as recorded.
- **Arena handoff (2026-08-13, committed)**: 8 OOS-verified strategies wired into MoT layer. `strategies/experts.py` (VerifiedExpert registry + StrategyRouter), `strategies/handoff.py` (eval→router state), `strategies/seed_router.py` (seeds `data/live_router_state.json` with tournament evidence as initial track record), `strategies/shadow.py` (paper lane → `data/live_router_state_strategies.json`). Router picks multiasset per-regime (OOS Calmar 1.289). REGIME KEYS MUST BE 'up'/'down' (harness maps bull/bear→up/down at attribution, harness.py:2636). HONEST BOUNDARY: daily-bar universe allocators, NOT validated on harness's real-time 19-symbol universe — ROUTING/MONITORING only, not live order flow.
- **R1d participation round (2026-08-13, VERIFIED)**: solved the broad-bull gap. New verified expert `laggard` (momentum k5 + one 10-day laggard catch-up, both in confirmed bull breadth>0.7) — OOS Calmar 1.666, maxDD -7.5%, beats intl basket in 2023-26 (+71.8% vs +64.5%). Bar: `scorer_intl.bull_participation_oos` (calibrated so momtrend/multiasset both fail). Roster now 9 prototype experts. Script LOST to /tmp cleanup (2026-08-23); the committed port `strategies/laggard.py` is the durable artifact.
- **Weight evolution (2026-08-13, committed)**: `strategies/evolve_weights.py` evolves the MoT weight schedule from verified OOS Calmar (weights + track reconciled, audit #3). Router now picks `laggard` in both regimes (verified Calmar 1.666); live `RegimeRouter.step()` continues from here. Status: ROUTING evolution, not live order flow. State: `data/live_router_state.json`.
- **`_cross_sectional_rank` fix (commit 9b7301a)**: `rank_on` configs were silently dead (0 trades) because `dropna(axis=1)` removed all columns whenever any bar had NaN. Fixed to per-bar dropna. Any prior "rank inactive" reading is invalid.
- **Walkforward report**: `PYTHONPATH=/home/mrc/opentrader-sandbox /home/mrc/rocm_venv/bin/python3 -m setup_search.walkforward` — its `references` rows now include the ledger contract, and a `full_archive` section reports every reference over the whole span (fold-only views hide sparse regime-gated configs).
- **best.json provenance**: the ledger (`data/setup_search/ledger.jsonl`, max-score config) is the source of truth for the rule floor; `best.json` was clobbered once (2026-08-10, agent run af1e6d83) and is restored from the ledger. If the two disagree, flag it — do not silently trust either.
- **Probe provenance (STEP ZERO, 2026-08-23)**: canonical probe locations are declared in `data/MANIFEST.json`. `/tmp` is scratch — nothing durable references it. Probes lost to /tmp cleanup are marked LOST above: their findings stand as recorded but are not re-runnable.

History: the 08-12 "rule floor falsified" report measured DEFAULT_CONFIG (5% risk, no regime), not the documented contract (15% risk, 96d regime, thresh 0.28). The contract measures +23.1% net / 5y. See `docs/CONTEXT.md` and `~/overnight-reports/opentrader-2026-08-12-session.md`.

## Audit gate — binding, every session (no exceptions)

1. **Verify before consuming.** Any ledger/state/DB file you read or write (paper_state.json, catalog.db, alt_data_cache.db, live_router_state_*): enumerate its writers, confirm atomicity and locking, identify the single source of truth. Never trust a state file's provenance unverified.
2. **Audit before building.** No consumer of a ledger without first auditing that ledger's writer set. Never extend a system whose integrity you haven't checked.
3. **Reconcile before reporting "done".** Confirm the ledgers you touched agree (exchange ledger vs risk account vs state file) — or document the drift explicitly.
4. **No fabricated metrics.** Computed values must trace to real outcomes; heuristics must be labeled as heuristics.
5. **Surface contradictions immediately.** If findings contradict a prior report, say so in the first message. Never bury it.
6. **Resource discipline.** rcheck check_environment before heavy steps; run_sandboxed for anything risky; never disturb running services without cause.
