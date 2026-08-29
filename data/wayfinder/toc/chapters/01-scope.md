# Scope — OpenTrader frontier under ADR-0007

> The ask, success criteria, and constraints. This chapter is loaded into every
> governed query. Keep it tight — it costs tokens every time it is loaded.

## Objective

Advance the OpenTrader deployment program pinned by `docs/adr/0007-reground-victory-path.md`:
make ADR-0002's deployability criterion *measurable and passing* on the pinned
live universe (511-registry radar → 6-symbol focus) by (a) closing the
improvement-loop plumbing tickets #155 → #157 so per-regime shadow impact
accrues to experts and the router evolves on evidence, and (b) keeping the
live paper harness faithful (ADR-0001) so plumbing evidence accrues.

## Success criteria
- [ ] #155: regime keys unified to `up`/`down`; `live_router_state.json` single-writer; swarm evidence moved out of `/tmp` into `data/` (sandbox-proven first).
- [ ] #156 decision drafted (HITL): promotion seam for gate-passing experts, with the +1%/0.5%-erosion bar quoted from the ADR, not prose.
- [ ] #157 prototype: recurring shadow driver accrues per-regime impact and calls `RegimeRouter.step()`.
- [ ] ADR-0002 clause status recomputed from real ledgers (not prose) at the end of each session.

## Hard constraints
- The victory condition is deployability on the pinned universe. Do NOT
  pursue: wide-universe edge claims, marketplace/monetization (#73/#80), C2
  transmit, court week (#123–128), UI/cosmetics, or new agent-meta tooling. Parked by
  ADR-0007 §7.
- Multi-venue prop posture (ADR-0008): the TradeLocker adapter IS sanctioned
  bridge work, but sequenced AFTER #155–157 close. Do not start it in this
  campaign; do not reconfigure the validated risk contract for "challenge
  mode" without its own ADR.
- Numeric claims: only repeat what the epistemic ledger marks `[known]`, with
  its bounds. Anything else is `[computable]` (run the probe and record the
  command + output in `chapters/04-raw/`) or must be answered "unknown".
- You may not promote your own ledger variables to `[known]` — propose via an
  open question; the human/orchestrator curates status changes.
- Sandbox-first (`/home/mrc/opentrader-sandbox`); live tree and GPU untouched
  until validated. Never kill/restart harness, gpu-sync, dashboard, or the
  model servers.
- Engine integrity: any metric computed on the pre-`1718f33` engine is
  optimistic ~4–5pp — never quote one without the correction.
- REGIME KEYS are `up`/`down` (harness maps bull/bear → up/down at
  attribution, harness.py:2636).

## Deliverables
- Tickets #155/#157 closed with verbatim command-output proof in the ticket.
- Session findings appended to `chapters/04-raw/` (append-only) and a
  checkpoint at each phase boundary (`toc checkpoint`).
- Any proposed ledger status change → `toc open add "..."` for human review.
