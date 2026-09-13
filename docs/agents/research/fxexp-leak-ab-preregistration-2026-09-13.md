# Pre-registration: fxexpert standardization-leak A/B (#249)

- **Timestamp:** 2026-09-13, written after the #244 leak fix and before the
  A/B has run. Author: agent session. Human directive 2026-09-13: all GPU
  work moves to the RTX 3070; the RX 7900 GRE is the gaming GPU and is never
  a compute target.
- **Why now:** #249 asks whether the standardization leak flattered, hurt, or
  sat neutral to reported PF/IC — "the answer determines whether any pre-fix
  number is quotable." Fixing the design, seeds, and decision rule *before*
  the run prevents a post-hoc choice of comparison that would repeat the
  selection problem this map exists to close.

## What is being tested

D1 (#232): the pre-#244 trainer computed standardization stats as
`X[tr_idx]` — filtered-array positions applied to the FULL panel, so invalid
and out-of-fold rows (including future data) entered mu/sd in every
generation. The fix (`X[idx_keep[tr_idx]]`) is in the tree and verified
(#244). This A/B measures the leak's **effect size** on the reported OOS
metrics, not whether the leak existed (it did — the code demonstrably
changed).

## Design: paired A/B on ONE panel

The same hp config, seed, and warm checkpoint are trained twice, differing
ONLY in the standardization stats source (`leak_standardization=True/False`,
fxexpert/train.py — the leaky arm is DEBUG-ONLY, pinned by
`tests/test_leak_flag.py`). The paired diff isolates the leak; everything
else (panel, folds, warm weights, RNG) is identical across arms.

**Why not recorded-vs-rerun:** the recorded generations ran on a panel that
no longer exists (g137's OOS span covers ~217k rows; the current panel is
~289k rows with a changed feature set — panel_v2 repairs), panel rebuilds
are not snapshotted per generation, and the historical seed is not recorded
(`train_g*.json` "params" is the parameter COUNT, not the seed — an earlier
reading of it as the seed was wrong and is corrected here). Any
recorded-vs-rerun delta would confound panel drift, feature drift, seed
noise, and the leak. The paired A/B on one pinned panel has none of those
confounds; the recorded pre-fix numbers remain context only.

## Fixed choices (nothing below may change after results are seen)

- **Configs:** U and V — the distinct hp of the decision-relevant
  generations (g137/g151/g185 = U, g138 = V), read from their `train_g*.json`.
- **Warm start:** g109 in BOTH arms (the recorded warm source of all four
  named generations; per-fold checkpoints `g109_f{0,1,2}.pt` verified
  present 2026-09-13). Identical across arms, so the paired diff stays clean.
- **Seeds:** 11 + 1009·k for k = 0..4 (the loop's own gseed formula shape).
- **Metrics:** OOS IC mean = PRIMARY (the statistic the hp bandit actually
  selects on since the 2026-09-12 re-spec); gate PF via
  `fxexpert.gate.rescore` = SECONDARY, reported as context.
- **Verdict (sign test over the 10 (config, seed) pairs on
  dIC = leaky − fixed):**
  - ≥ 8/10 pairs dIC > 0 → **"leak flattered IC"**;
  - ≥ 8/10 pairs dIC < 0 → **"leak hurt IC"**;
  - otherwise → **"not resolved at this power (10 pairs)"**.
  dPF medians are reported alongside but never decide the verdict.
- **Quotability consequence (fixed):** pre-fix recorded PF/IC stay
  quarantined if the verdict is "flattered"; they may be quoted with the
  leak caveat only under "hurt" (they understated) or "not resolved", each
  stated with the measured dIC/dPF magnitudes. Nothing here promotes or cuts
  an expert — that remains the forward-accrual test (see
  `forward-accrual-promotion-preregistration-2026-09-12.md`).

## Device contract (human directive 2026-09-13)

- The A/B runs on the **RTX 3070**, via the CUDA torch venv
  (`.venv-cuda`, torch cu128): `.venv-cuda/bin/python scripts/fxexp_leak_ab.py --confirm-idle`.
- The default repo venv is a ROCm build whose "cuda" device is the GRE —
  `scripts/fxexp_leak_ab.py` refuses it **before any GPU initialization**
  (torch.version.hip check), and additionally refuses any CUDA device not
  named "RTX 3070". The GRE hosts the human's game and (when not gaming) the
  warden LLM — never a compute target for this repo.
- Incident, on the record: 2026-09-13 a guard *test* of this script trained
  one leaky fold set (abUL0/gabUF0, config U seed 11) on the GRE through the
  ROCm venv before the guard existed; the run was killed, its artifacts
  deleted, and the device contract above was added. The user directed the
  move to the 3070.

## Hygiene and cost

- A/B tags (`abU0L`, `abU0F`, …) are non-numeric, so the deflation
  populations (`scripts/white_reality_check.py`), the loop's
  history/state/registry, and lane attribution are untouched.
- Cost: 2 configs × 5 seeds × 2 arms = 20 walkforwards ≈ 30–45 min on the
  3070 (recorded per-generation secs on the GRE were 76–122s; the 3070 is
  slower per-step but the same order).
- Run `rcheck check_environment` first; record honestly even if nothing
  promotes. The result artifact is `data/fx_expert/leak_ab_result.json`
  (panel snapshot + all 20 runs + paired diffs + verdict); the verdict is
  recorded on #249 verbatim.

## POST-RUN ADDENDUM (2026-09-13, after the artifact was written — no
## pre-registered choice was altered)

Result: **10/10 pairs dIC > 0, median dIC +0.00305 → "leak flattered IC"**
(median dPF +0.0004, mixed signs — PF ~neutral). One discovery about the
candidate set, recorded here because it changes how the evidence reads:
configs U and V are TRAINING-identical — they differ only in `vol_target`,
a position-rule knob the trainer never sees — so every (U, V) pair shares
the same model per seed (identical ICs; PFs differ only through the gate's
position construction). The IC evidence is therefore **5 independent seeds,
all positive** (+0.00193..+0.00624), not 10 — the verdict is unchanged
under the pre-registered ≥80% rule (5/5 ≥ 4/5). The PF pairs remain 10
position-rule observations, seed-clustered.
