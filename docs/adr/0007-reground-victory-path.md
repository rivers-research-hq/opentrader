# ADR-0007: Re-ground the victory path — pinned-universe deployability, regime-switching edge, governed claims

- **Status:** accepted
- **Date:** 2026-08-28
- **Context:** Between 2026-08-12 and 2026-08-23 the plan's foundations were
  falsified by the project's own probes: the VIX edge was struck (falsifier,
  1/3 eras), the rule-floor contract does **not** generalize (−45.95% on the
  511-registry, −41.07% on the 7.3k fullcross, re-verified 2026-08-23), the
  signal-family probe found no existing family generalizes under realistic
  fees, the macro `ff_falling` gate failed its OOS walkforward (1/4 folds), the
  arena gate is failing, and the epoch engine's on-disk verdict is
  **no-promotion** (`data/arena/epoch_report.json`: both epochs FAIL) —
  contradicting ADR-0006's phase-2 PASS narrative, which is therefore
  **unverified and must not be repeated**. `docs/evolution-thesis.md` R1
  (2026-08-01) still cites a "+~5%/yr OOS, 3/3 unseen years" edge measured on
  the pre-`1718f33` engine (metrics optimistic by ~4–5pp). Meanwhile four
  agent campaigns (Aug 13–28) produced work that feeds no gate in the written
  deployment program (dashboards, TUI, agent tooling, monetization plumbing,
  model self-benchmarks) while the critical path (ADR-0002 shadow evidence,
  tickets #155–157) stalled, and the dev-plan's weekly human review never
  convened. `docs/agents/research/self-improvement-loop-audit.md` (2026-08-23)
  concludes the improvement loop is "seeded once from static OOS evidence" and
  does not close. A single, pinned victory condition is required so every
  future session has a score function.

- **Decision:**

  1. **The victory condition is ADR-0002's deployability criterion, evaluated
     on the pinned live universe** (511-ticker industry registry radar →
     6-symbol focus; see `docs/agents/research/universe-bridge-matrix.md` —
     the "19-symbol universe" phrase in CONTEXT.md/AGENTS.md/`experts.py` is
     stale boilerplate). Edge evidence accrues in the shadow engine only.
     Nothing else counts as progress until deployability is met or a clause
     fails with a written diagnosis.

  2. **The edge thesis is structural regime-switching**, because that is the
     only thing that verified OOS: momentum-participation in confirmed bull
     (`laggard`, OOS Calmar 1.666, maxDD −7.5%), contrarian worst-5 rotation
     in crisis windows, drawdown control as the cross-universe transferable
     skill (6/8 R2 gauntlet), and diversification (intl basket BH beats SPY
     BH risk-adjusted). The rule floor remains the incumbent that holds all
     weight until an expert earns it. No single-signal edge claim is
     entertainable without a fresh passing probe.

  3. **Generalization becomes a separate research track, not a blocker.**
     Scope: new signal inputs (macro-relative, sector-relative) — the one
     untested family per the signal-family probe. Success bar:
     `scripts/universe_contract_test.py` passing on the 7.3k wide archive.
     Until it passes, the deployment track does not wait on it, and no
     config is promoted without the standing `--wide-eval` gate.

  4. **The improvement loop (#155 → #156 → #157) is re-scoped as
     infrastructure for decision 1:** it exists so per-regime shadow impact
     accrues to experts and weights evolve on evidence (#157 is precisely the
     accrual driver ADR-0002 clause 2 needs). The loop is not itself the
     goal, and it optimizes nothing until a validated edge exists to improve.

  5. **FTMO remains the revenue vehicle (ADR-0005 unchanged)** with two
     honest pins: (a) the sandbox cadence math (~939 days / 44 trades to
     Phase 1 target at the system's actual trade frequency) is the planning
     baseline — accepting it is the default; a cadence workstream under
     ADR-0004's frequency policy is the alternative and needs its own
     decision; (b) the prop leg trades the OANDA/FTMO universe (FX, metals,
     indices, commodities, crypto CFDs — US single-stock CFD availability
     unverified), so the FTMO-facing strategy variants are a distinct bridge
     work item mapped in `universe-bridge-matrix.md`.

  6. **Governance repairs — binding:**
     - The weekly human review convenes for real, with this ADR as the score
       function; AFK agents never resolve grilling tickets (existing rule,
       now enforced by the review actually existing).
     - **Claims are governed by a ToC epistemic ledger**
       (`toc`, `/home/mrc/ai/table-of-context`; workspace:
       `data/wayfinder/toc/`). Every numeric claim an agent wants to repeat
       must resolve to a ledger variable whose status is `known` with probe
       bounds; unverifiable mechanisms are `computable` (probe must be run),
       dead ends are `unknowable` (recorded as open questions at zero token
       cost), speculation is quarantined `explore`. The agent may not promote
       its own variables to `known` — that stays with the human/orchestrator.
     - The Runway ladder is **1% → 10%** per ADR-0002; CONTEXT.md's "15%" is
       drift to be reconciled in CONTEXT.md (raising the ceiling requires a
       new ADR, not a glossary edit).
     - Qwen3.8-27B remains the implementer under this governance: machine
       verification for every number it emits (its digit-garbling is
       documented in the overnight pipeline), and no operational authority
       beyond paper until deployability. Outbound publishing hooks (C2
       transmit) stay dormant/suspended — monetization workstreams do not
       run before the deployability gate.

  7. **Suspension by default:** workstreams that feed none of decisions 1–5
     are parked, not deleted: monetization maps (#73, #80), court week
     (#123–128), Hollama UI (#149), TUI, dashboard cosmetics, further
     agent-meta tooling. Any of them can return through an explicit ADR or a
     human-review decision that names the gate it feeds.

- **Consequences:** The evolution-thesis is revised to **R2** on this basis.
  ADR-0001, 0002, 0003, 0004, 0005 are unchanged; ADR-0006's continual/
  rehearsal/reasoning *design* stands but its phase-2 **demo claim is
  corrected** to "no-promotion as measured — retry next epoch." Work already
  in flight that feeds the gates (accumulator data pipeline, lanes paper
  feed, risk/state plumbing fixes) continues. The success metric for every
  future session is: **does this session's work move a deployability clause,
  close #155–157, advance the FTMO bridge, or produce a passing
  generalization probe?** If none, it should not have run.
