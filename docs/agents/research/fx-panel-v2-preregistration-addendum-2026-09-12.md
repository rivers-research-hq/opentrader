# Pre-registration addendum: weight-transfer test of the panel-v2 information

- **Timestamp:** 2026-09-12T04:3x UTC, written AFTER the v2 round completed and
  BEFORE the transfer generations were trained. Author: agent session.
- **Supersedes nothing**; the first pre-registration
  (`fx-panel-v2-preregistration-2026-09-12.md`) stands as written, including the
  round that failed.

## What the completed round showed (facts, before this test)

- All 8 pre-registered v2 generations FAIL the raw gate; best g201 PF 1.0225
  (+0.087 bps/day), IC 0.0141. Recorded in `history.jsonl` with `round=panel_v2`.
- **The pre-registered list was partly redundant**: hp `U/V/X/AA` share every
  *model* knob (d_model 96, 3 layers, 4 heads, dropout 0.15, lr 7e-4, 40 epochs,
  batch 4096, T 20, score_l2 0.05, horizon 10) and differ only in the position
  *rule* (vol_target / cost_cap) and seed. With fresh init and the same seed
  they train identical weights — visible as identical IC (0.01409 for g201,
  g203, g204, g205, g207). Effective distinct models in the round: 4, not 8.
  The pre-registration did not catch this; recorded as a defect of the round.
- **Fresh-init control on the v1 panel** (not pre-registered, run to check the
  design): tag 211 = hp `U` seed 11 fresh on `panel.npz` → PF 1.0202, IC 0.0180
  — statistically indistinguishable from its v2 twin g201 (PF 1.0225, IC
  0.0141). So at fresh-init strength the new information is worth ≈ +0.002 PF.
- For scale: the recorded best g185 (PF 1.2862, IC 0.0298) is a warm-started
  descendant of a ~150-generation chain, while its identical config trained
  fresh lands at 1.02. The recorded edge lives in the recursion, not in a
  single training run.

## Hypothesis for this test

A fresh-init model at PF ~1.02 is weak enough that its score ranking is
dominated by noise; marginal new inputs cannot show up in its book. The fair
test of "does the new information add anything?" is on a **strong** model.

**Test:** transfer the v1 best (g185) per-fold checkpoints into the 61-feature
architecture — copy the input-projection rows by feature *name*, zero the
columns for the new features — then fine-tune on panel v2 with the standing
protocol (hp `U`, folds, purge, early stopping all unchanged).

- Generations: tag 221 (seed 11) and 222 (seed 23), warm = transferred g185
  fold weights. Two, not more: this is a directional test, not a search.
- Reference points, fixed now: the transferred model with the new features
  must (a) clear the standing raw gate, and (b) beat g185's recorded PF 1.2862;
  a transfer that merely matches it is evidence the new features are neutral.

**Acceptance:** unchanged — standing raw gate + the deflated bar (return-series
WRC p < 0.05 over the combined population: the 89 existing clean-era
generations + the 8 v2 generations + 2 v1 controls + these 2 transfer
generations = 101 evaluations, all re-scored from artifacts).

**Honest expectation, stated before the run:** zeroing the new input rows means
fine-tuning starts from the same function as g185; the new features can only
enter through gradient updates. If they carry nothing (as the standalone probe
suggests: carry rank book PF 0.96, ToT 1.07), the transfer will converge back
to ≈ g185 — which would settle the question against the information hypothesis
at this horizon and construction.

---

## RESULT (2026-09-12, appended after the run)

| tag | seed | IC | PF | bps/day | gate |
|---|--:|--:|--:|--:|---|
| 221 | 11 | 0.0291 | 1.0337 | +0.132 | FAIL |
| 222 | 23 | 0.0326 | 1.0291 | +0.114 | FAIL |

The transfer **recovered the signal** (IC back to g185's level: 0.029–0.033 vs
g185's 0.0298) and stayed far below g185's book (PF 1.03 vs 1.286). So the
expectation above was wrong in an informative way: it is not that the new
features fail to help — it is that **the same signal quality converts to a
completely different PF depending on the model instance**.

Diagnostics ruled out the obvious explanations for that gap: rank churn is
0.097–0.098 for g221/g222 vs 0.099 for g185, and within-pair score
autocorrelation is 0.940 in all three. The scores are equally stable; the
books differ anyway.

**Population evidence (§V-WRC population, 101 generations, 58-pair era):**
corr(IC, PF) = **0.168**; within each IC quartile PF spans 0.76–1.29 (e.g. the
0.0291–0.0309 quartile: mean 1.063, sd 0.156, min 0.762, max 1.286). Two models
with IC 0.0291 and 0.0298 score PF 1.034 and 1.286.

**Conclusion:** the gate's PF≥1.05 bar is dominated by variance that is
unrelated to signal quality; the search has been selecting that variance. This
is why the deflation (§V-WRC, p(PF)=0.119) kills the winner and why new
information cannot show up in the metric. The bar itself is the next thing to
fix — an HITL decision, filed as an issue.