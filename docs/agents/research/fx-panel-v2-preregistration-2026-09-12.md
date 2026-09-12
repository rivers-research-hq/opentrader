# Pre-registration: fxexpert panel v2 round (new exogenous information)

- **Timestamp:** 2026-09-12T03:5x UTC, written BEFORE any v2 panel build, probe or
  training run. Author: agent session (subscription lane).
- **Decision context:** #243 (measurement repair) landed the deflated bar
  (V-WRC): no clean-era generation survives (best g185 PF 1.2923 → RC
  p(PF) = 0.119). The recorded ceiling is information-limited at the current
  input set, so the next round must add *information*, not hyperparameter
  draws. The human asked for a generation that passes and authorised new data
  sources (2026-09-12).

## Finding that motivates the round (measured before this document)

The training panel's exogenous blocks are close to vacuous — the model has
been fitting price-derived features almost exclusively:

| block | non-zero rows in `panel.npz` (289,467 × 48) | why |
|---|--:|---|
| `carry` / `carry_z` / `carry_mask` | 7.2–7.4 % | only 6 `CARRY:*` series exist (EUR_USD, GBP_USD, USD_CAD, EUR_GBP, EUR_CAD, GBP_CAD) |
| `rate_diff` / `rate_mask` | **0.0 %** | the rate table is keyed `US/EA/GB/CA` (FRED codes) while pairs use `USD/EUR/GBP/CAD` (ISO) → every lookup misses |
| `events_5d` | **0.0 %** | `releases_history.currency` uses calendar codes (`JN/SZ/UK/EZ/CH`) while the join uses ISO (`JPY/CHF/GBP/EUR/CNH`) → 17,960 `high`-impact events never join |
| `cot_z` / `cot_mask` | 14.9 % | 7 currencies only |
| `fred_hy_z` | 8.7 % | FRED `BAMLH0A0HYM2` now only serves 796 rows (2023-09+) — licence truncation, not a bug |

So the search has been ranking 58 pairs on **price-only** information plus
sporadic carry/COT. Carry — the classic FX cross-sectional factor — exists for
~10 % of pair-days.

## Pre-registered plan

**Information to add (all point-in-time safe, source: BIS daily central-bank
policy rates, `stats.bis.org/api/v1/data/WS_CBPOL`, free/citation, plus FRED
and the existing store):**

1. **Policy-rate coverage for every currency in the universe** — BIS daily
   policy rates for US, XM, GB, JP, AU, NZ, CA, CH, SE, NO, CZ, HU, PL, TR, ZA,
   CN, TH, MX (SGD has no policy rate by design — MAS targets the S$NEER).
   Lagged 1 day. This takes carry from 6 pairs to ~57 of 58.
2. **Carry block per pair**: level (`pv_carry`), causal 252d z (`pv_carry_z`),
   20d change (`pv_carry_chg20`, hike/cut momentum), and the cross-sectional
   demeaned carry (`pv_carry_xs`) that a dollar-neutral rank book actually
   harvests.
3. **Terms of trade block per currency** (commodity exporters/importers):
   per-currency commodity basket z (oil, copper, iron ore, dairy, gold, gas),
   per-pair differential `pv_tot_diff` + 20d change.
4. **US curve / real-rate state** (global dollar factor): `DGS2`, `DFII10`,
   `DGS5` where available — level z and 20d change, lagged 1 day.
5. **Repaired joins**: the two currency-code maps above (rate legs + event
   counts), so `rate_diff` and `events_5d` are live for the pairs they belong
   to. Repaired joins alone are not new data, but they are information the
   system already claimed to hold.

**Bounded round (fixed now, not extended after seeing results):**

- Panel: `data/fx_expert/panel_v2.npz` (a NEW file; `panel.npz` is left
  untouched so the live lanes' checkpoints stay consistent).
- 8 generations, fresh init (warm-start is impossible across a feature-count
  change; within-round chaining is not used so each generation is an
  independent evaluation — this is deliberately conservative for the
  deflation population): hp `U`, `U` (seed 23), `V`, `X`, `AA`, `N`, `S`, `W`
  from `fxexpert.loop.HPARAMS`, same protocol/hyperparameters as the standing
  search.
- Tags: `v2-01` … `v2-08` (numeric-safe tag form `v201`…`v208` in file names so
  every existing consumer — gate, deflation script — can read them).

**Acceptance (both required, no post-hoc adjustment):**

1. the standing raw gate: PF ≥ 1.05, beats every applicable baseline,
   ≥ 2/3 folds OOS IC > 0, ≥ 2000 positioned pair-days; and
2. the deflated bar (#245, V-WRC): return-series White's Reality Check
   p < 0.05 over the **combined** clean-era population (existing generations +
   the 8 pre-registered ones), block 20d, B = 20 000, re-scored consistently
   from artifacts.

**Ablation (reported, not gating):** the same 8 hp on the v1 panel (existing
recorded generations) vs the v2 panel — the difference is the round's honest
estimate of what the new information bought.

**Out of scope:** live order flow (human-gated, ADR-0009 §4); the live lanes'
checkpoints; replacing `panel.npz`; any promo/cut decision.

**Honest expectation, stated before the run:** the classic FX factors are
well known and priced-in to a degree; the model may exploit the new blocks
only weakly at 340k parameters. If nothing clears the bar, that is the
answer, and it is recorded as such.

---

## RESULT (2026-09-12, appended after the run)

**Verdict: all 8 generations FAIL the raw gate; nothing promotes.**

| tag | hp | rule | IC | PF | bps/day |
|---|---|---|--:|--:|--:|
| 201 | U | rank | 0.0141 | 1.0225 | +0.087 |
| 202 | U (seed 23) | rank | 0.0266 | 1.0122 | +0.049 |
| 203 | V | rank+voltarget | 0.0141 | 1.0184 | +0.066 |
| 204 | X | rank+costcap | 0.0141 | 1.0089 | +0.018 |
| 205 | AA | rank+vt+cap | 0.0141 | 1.0084 | +0.016 |
| 206 | N | thr | 0.0173 | 0.9787 | −0.096 |
| 207 | S | thr_cont | 0.0141 | 0.9809 | −0.101 |
| 208 | W | thr_cont+vt | 0.0141 | 0.9520 | — |

**Round defect (found after the fact, recorded):** hp `U/V/X/AA` share all
*model* knobs and differ only in the position *rule*; with fresh init and the
same seed they produce identical weights (visible as identical IC 0.01409 for
201/203/204/205/207). The round therefore evaluated **4 distinct models**, not
8. The pre-registration did not catch this.

**Control (run after the round, to make the ablation fair):** fresh-init `U` on
the **v1** panel = PF 1.0202 (IC 0.0180), fresh-init `N` = 0.9919 — versus their
v2 twins 1.0225 / 0.9787. **The new information is worth ≈ +0.00–0.002 PF at
fresh-init strength — i.e. nothing measurable.**

**Probe evidence (before the round):** the new blocks arrive but are weak. Rank
book on the raw feature through the gate's own simulation: carry PF 0.965,
carry_z 1.077, ToT 1.069, COT 1.051 (vs the trained g185's 1.286). No new
feature ranks in the top-5 by PF.

**Follow-up (separate pre-registration addendum):** the feature-transfer test
on a strong (warm-started) model.
