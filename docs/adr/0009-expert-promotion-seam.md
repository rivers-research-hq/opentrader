# ADR-0009: Expert promotion seam — epoch registry, shadow-first, compete-not-displace

- **Status:** accepted
- **Date:** 2026-08-31
- **Context:** #156 (grilling) asked how a gate-passing expert enters the
  router's expert set — the seam that makes MoT's "experts earn weight"
  mechanism real. Decision memo
  (`data/wayfinder/promotion-path-memo.md`) analyzed three candidate seams
  with ledger-verified citations; the human decided 2026-08-31 (five
  questions, all recommendations adopted). Inputs: V06 (verified roster,
  routing-only boundary), V07 (epoch engine no-promotion — the bar stands,
  no candidate has cleared it), V10 (loop seeded-once; #157 accrual now
  live), continuity-3 (upstream `RegimeRouter.step()` invariant
  `rule = 1 − expert` breaks with multiple validated experts — floor clamp
  required).

- **Decision:**

  1. **Seam: separate epoch-expert registry** (`strategies/epoch_registry.py`,
     to be built): keyed by (epoch, regime), shadow-first,
     **compete-not-displace**. The static `VERIFIED` registry stays OOS
     strategies only; live order flow is untouched until weight is earned
     through forward accrual (V06 boundary holds). ValueHeadExpert live
     registration (seam A) is rejected — it crosses the V06 boundary;
     VERIFIED append (seam B) is rejected — gate margin is not a Calmar
     (unit mismatch would propagate through `evolve_weights`).
  2. **Seed:** a promoted candidate's track entry is
     `sum = gate_margin × SCALE (10.0)`, `n = MIN_EVIDENCE (5)`, marked
     `"seed": "gate_margin"` — the `evolve_weights` pattern. The seed is
     **replaced, never merged**, once real forward windows accrue. Proportional
     -to-sample `n` is rejected: thin gate samples must not masquerade as
     tournament-grade track records.
  3. **Compete, never displace:** promotion grants *eligibility* only; the
     rule-floor prior stays intact and weight moves solely through
     `RegimeRouter.step()` on forward windows. Displacement, if it ever
     happens, is earned by accrual — never granted at promotion.
  4. **Auto-promotion into the shadow registry** on gate pass, with full
     artifact logging (epoch report + holdout windows, human-visible log).
     Human signoff is required only at the **shadow → live-order-flow
     boundary** — the irreversible step.
  5. **Zero-forward regimes hold the rule floor** (existing `pick()`
     behavior, `mot/mixture.py:113`). No seeded floor share — free options
     are the drift pattern ADR-0007 was written to prevent.
  6. **The gate bar is unchanged** (ADR-0006): kept-trades mean minus
     candidate mean ≥ +1% on BOTH regime windows; erosion ≤ 0.5% on prior
     holdouts; beats the single-global-expert baseline; real data only.
     Current status: no candidate has cleared it (V07) — the factory keeps
     producing candidates; the seam waits ready.

- **Consequences:** implementation is a bounded build
  (`strategies/epoch_registry.py` + `pick()` eligibility extension +
  promotion artifact log), owned by the subscription agent per the role
  division (critical path). The multi-expert floor clamp proven in
  continuity-3 (`_apply_floor`) carries into the registry path. Evidence
  accrual for eligibility runs on the live books via the shadow driver
  (Monday cadence) — the seam becomes exercisable as forward windows accrue.
  VERIFIED, the arena, and the epoch engine are unchanged; the engine's
  next candidate either clears the bar or logs another honest no-promotion.
