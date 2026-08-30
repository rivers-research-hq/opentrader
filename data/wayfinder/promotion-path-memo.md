# Decision memo — #156 promotion path (how a gate-passing expert enters the router)

- **Date:** 2026-08-29
- **Status:** PREP FOR HITL GRILLING — this memo decides nothing, implements
  nothing, registers nothing. It lays out the three candidate seams with
  evidence, failure modes, and reversibility, then asks the human to choose.
- **Method:** every number below is quoted verbatim from the ToC ledger
  (`data/wayfinder/toc/`) or from code at file:line in
  `/home/mrc/opentrader-sandbox`. No prose-derived metrics.

## 0. The bar (binding, from ADR-0006)

A candidate expert is promoted only if, on real data only (synthetic never
enters the gate):

- kept-trades mean minus candidate mean **≥ +1% on BOTH regime windows**;
- **erosion ≤ 0.5%** on prior holdouts (the anti-forgetting counterweight);
- it **beats the single-global-expert baseline** on both.

ADR-0006 §(epoch bar), lines 71–74 of `docs/adr/0006-deepseek-pillars.md`.

**Current state of the bar (V07, verbatim):** "Epoch engine verdict:
no-promotion. Both epochs FAIL (+0.945%/+0.533% vs +1% gate; epoch2 erosion
1.006% > 0.5%). ADR-0006 phase-2 PASS narrative is UNVERIFIED - never repeat
it." The bar stands; **no candidate has cleared it yet.** This memo is about
the *seam* — what happens when one does — not about whether one exists.

## 1. The machinery the seam must plug into

- `RegimeRouter` (`mot/mixture.py:66`): per-regime track records
  `track[regime][expert] = {sum, n}`; `pick()` (`mot/mixture.py:113`) lets an
  expert act only if `n >= min_evidence` (default 5) and its mean impact
  strictly beats the rule floor's; `step()` (`mot/mixture.py:137`) shifts
  weight +0.1/window toward a validated (regime, expert), cap 0.5, reset to
  floor on failure.
- `VERIFIED` registry (`strategies/experts.py:45`): the 9 OOS-verified
  experts as `VerifiedExpert(name, oos_calmar, ...)` — `laggard` 1.666,
  `multiasset` 1.289, `bayes` 1.148, `spectral` 1.000, `kalman` 0.988,
  `hurst` 0.967, `momtrend` 0.938, `wavelet` 0.803, `entropy` 0.667.
- Reconciliation pattern (`strategies/evolve_weights.py:78-95`): every
  verified expert gets a track entry `sum = oos_calmar * SCALE` (SCALE =
  10.0), `n = MIN_EVIDENCE` (5), so `pick()` and `weights` agree — "weights
  and track are two views of the same verified evidence — never let them
  diverge."
- **V06 (verbatim):** "9 prototype experts OOS-verified; laggard is champion
  (OOS Calmar 1.666, maxDD -7.5%). ROUTING/MONITORING only, never live order
  flow."
- **V10 (verbatim):** "Arena gate FAILING (-0.57%/+0.20% vs +1% bar,
  2026-08-23 audit); improvement loop seeded once from static OOS evidence,
  does not close (#155-157 open)."

**Dependency the whole memo rests on (V10):** the loop is seeded *once* from
static evidence. #157 (the recurring shadow driver) is the accrual mechanism
that makes per-regime impact accumulate on real forward windows. **Promotion
evidence quality depends on #157 existing first** — without it, any
promotion decision is made on the same static seed the loop already has, and
the seam is dead code until #157 lands.

## 2. Candidate seam A — ValueHeadExpert registration

**Mechanism.** A gate-passing MLP becomes a live expert class in the harness
router: a new `Expert`-protocol implementation (like `TournamentExpert`,
`strategies/experts.py:80`) whose `decide()` runs the MLP value head and
returns an `ExpertDecision`. It enters `RegimeRouter.track` under its own
name and competes in `pick()` like any other expert.

**Evidence for.** The `Expert` protocol (`mot/mixture.py:31`) is exactly the
seam for this — any class with `name` + `decide(ctx, symbol)` plugs in.
`TournamentExpert` already shows the wrapper pattern for verified strategies.

**Evidence against / risk.** V06: the verified set is "ROUTING/MONITORING
only, never live order flow." Registering an MLP as a *live* expert class
crosses from routing into order flow — a category the ledger has kept closed.
Also V02: every edge claim is universe-bound; the MLP was gated on its epoch
holdout, not on the pinned 511-registry universe.

**Failure mode if wrong.** A gate-passing-on-its-own-holdout MLP that does not
transfer to the pinned universe takes weight in `pick()` (it only needs
`n >= 5` and to beat the rule floor's mean impact in-regime) and silently
degrades live routing quality. The rule-floor prior (`mot/mixture.py:113-135`)
protects only while the rule has a track record; once the MLP accrues 5
windows it can displace the floor in `pick()` even with weak real impact.

**Reversibility.** High. It is one class + one track entry; removing the
class and its track entry restores prior behavior. But any live decisions it
made while registered are not reversible.

## 3. Candidate seam B — VERIFIED append

**Mechanism.** Promote the gate-passing expert into
`strategies/experts.py::VERIFIED` with its gate margin as seed evidence —
exactly what `evolve_weights.py:78-95` reconciles from. It becomes a
`VerifiedExpert(name, oos_calmar=<gate-margin-as-calmar>, ...)` and inherits
the existing reconciliation: `sum = calmar * 10.0`, `n = 5`.

**Evidence for.** This is the *existing* reconciliation path — no new
machinery. `evolve_weights.py` already iterates `VERIFIED` to build both the
weight schedule and the track. Appending is the minimal-diff promotion.

**Evidence against / risk.** `VERIFIED` is a **static, code-committed**
registry of OOS-verified *strategies* (daily-bar universe allocators,
`strategies/experts.py:4`). An MLP value head is not the same kind of object;
forcing it into `VerifiedExpert` (which expects `oos_calmar`, `max_dd`, etc.)
conflates "verified OOS strategy" with "gate-passing candidate." The gate
margin (+1% mean) is not a Calmar — seeding `oos_calmar` with it is a unit
mismatch that `evolve_weights` would then propagate into weights.

**Failure mode if wrong.** The static registry becomes a second, code-level
source of truth for "who is verified," diverging from the ToC ledger and from
`live_router_state.json` track — exactly the multi-writer divergence #155
exists to prevent. A wrong unit (margin-as-Calmar) silently inflates the
expert's weight in `_evolve_schedule()`.

**Reversibility.** Medium. It is a code change (git-reversible), but it
permanently entangles the promotion path with the static OOS registry, and
every future `evolve_weights` run re-derives weights from the polluted entry
until the line is removed.

## 4. Candidate seam C — Separate epoch-expert registry (shadow-first)

**Mechanism.** ADR-0006's per-(epoch, regime) keyed registry, run
shadow-first: the gate-passing expert is recorded in a *separate* registry
keyed by (epoch, regime), accrues real per-regime impact via #157, and
**competes with — not displaces —** `laggard`/`multiasset`. It does not touch
`VERIFIED` and does not become a live order-flow expert; it earns weight only
through `RegimeRouter.step()` on validated forward windows.

**Evidence for.** This is the seam ADR-0006 itself describes (per-(epoch,
regime) registry) and the one the handoff's default recommendation points to
("use a separate epoch-expert registry; compete with (not displace)
`laggard`/`multiasset`"). It keeps the static `VERIFIED` registry pure (OOS
strategies only) and keeps the MLP out of live order flow (V06's boundary).
It is the only seam that is *forward-looking*: it waits for #157 to accrue
real evidence before any weight shifts, which is precisely the dependency
V10 flags.

**Evidence against / risk.** It is the most machinery: a new registry + a
shadow accrual path + a compete-not-displace rule in `pick()`. And it is
*useless until #157 exists* — with no accrual driver, the registry stays
empty and the seam is inert. It also defers any benefit: nothing is promoted
until real forward windows validate.

**Failure mode if wrong.** Low blast radius — if the expert never validates,
the registry simply stays empty and `laggard`/`multiasset` are untouched. The
main risk is scope creep: building the registry before #157 means building
against a non-existent accrual source.

**Reversibility.** Highest. Shadow-first + separate registry + compete-not-
displace means the incumbent set is structurally untouched; deleting the
registry and its (empty or partial) entries is a clean revert with no live
decisions to undo.

## 5. Comparison

| | A: ValueHeadExpert | B: VERIFIED append | C: epoch registry |
|---|---|---|---|
| Crosses into live order flow? | **Yes** (V06 boundary) | No (routing) | No (shadow-first) |
| New machinery | 1 class | none (reuses evolve) | registry + accrual + compete rule |
| Unit-mismatch risk | low | **high** (margin≠Calmar) | low |
| Multi-writer divergence | medium | **high** (2nd code source of truth) | low |
| Usable before #157 | yes (but on static seed) | yes (but on static seed) | **no — inert until #157** |
| Reversibility | high | medium | **highest** |
| Respects V06 "never live order flow" | **no** | yes | yes |

**The dependency that dominates all three (V10):** none of the seams produces
*new* evidence until #157 accrues real per-regime impact. A and B can be
wired now but would only ever act on the static seed the loop already has; C
is the only one whose value is *created* by #157.

## 6. DECISION QUESTIONS for the human (max 5)

1. **Which seam?** (A) ValueHeadExpert live registration, (B) VERIFIED append
   with gate-margin seed, or (C) separate epoch-expert registry, shadow-first,
   compete-not-displace?
2. **Evidence seed:** if a candidate is seeded before #157 accrues real
   windows, is the seed `sum = gate_margin * SCALE, n = MIN_EVIDENCE` (the
   `evolve_weights.py:88-95` pattern), or `n` proportional to the candidate's
   actual gate sample size?
3. **Compete vs displace:** should a promoted expert only *compete* for
   weight (rule-floor prior intact, `pick()` argmax), or is it allowed to
   *displace* an incumbent (`laggard`/`multiasset`) outright once validated?
4. **Auto vs signoff:** auto-promote on gate pass with the gate artifacts
   logged (epoch report + holdout windows) to a human-visible log, or require
   human signoff per promotion?
5. **No-evidence regime:** in the first regime where the new expert has no
   track record yet (`n = 0`), does it (a) hold the rule floor (current
   `pick()` behavior, `mot/mixture.py:113-135`), (b) get a seeded floor share,
   or (c) abstain entirely until #157 gives it ≥ `min_evidence` windows?

## Provenance

- ToC ledger `data/wayfinder/toc/`: V02, V06, V07, V10 (quoted verbatim above)
- `docs/adr/0006-deepseek-pillars.md` lines 71–74 (the +1%/0.5%/baseline bar)
- `mot/mixture.py:66` (RegimeRouter), `:113` (pick), `:137` (step)
- `strategies/experts.py:45` (VERIFIED), `:80` (TournamentExpert)
- `strategies/evolve_weights.py:78-95` (SCALE/MIN_EVIDENCE reconciliation)
- `docs/agents/handoff-ultimate.md` §5 (default recommendation: seam C)
