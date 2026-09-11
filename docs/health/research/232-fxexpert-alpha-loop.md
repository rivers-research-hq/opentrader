# fxexpert transformer search — panel / training / OOS gate assessment (wayfinder #232)

Read-only assessment of `fxexpert/{data,model,train,gate,loop,serve,trailing_ab}.py` plus the
`data/fx_expert/` artifacts. No training, no loop run, no services touched, GPUs untouched.
Every number below is either read from an artifact with a `file:line` (or a read-only text
reduction of one) or labelled as claimed/derived. Where a claim needs a run to settle it, it is
marked **SHOULD VERIFY** and was not run.

Evidence labels: **VERIFIED** (seen in code/artifact) · **READ-FROM-DOCS** (project record) ·
**CLAIMED** (asserted by a doc/ticket, not independently checked) · **DERIVED** (arithmetic I
performed over a verified artifact — method stated).

---

## Scope

**In scope:** the fxexpert alpha-search stack — panel construction (`data.py`), the transformer
(`model.py`), walkforward training (`train.py`), the OOS gate (`gate.py`), the recursion driver
(`loop.py`), the shadow signal seam (`serve.py`), the stop/TP A/B (`trailing_ab.py`), and the
read-only artifacts in `data/fx_expert/` (`panel_meta.json`, `loop_state.json`, `history.jsonl`,
`gate_g*.json`, `train_g*.json`, `claims.json`, `signals.json`).

**Out of scope:** the crypto paper lane (AGENTS.md, 2026-09-02); the OANDA adapter fork
(ToC Q04, human-gated); the live lane's execution internals (`strategies/fx_expert_lane.py`) —
read only where it consumes this module; the Warden (#218, separate doc).

**Ticket question:** panel/training/OOS-gate design; whether the gate is sound (lookahead,
leakage, multiple testing across the ~28 bandit arms A..AA); the honest record (gens 160-162 all
FAIL); and the strongest next lever (construction/sizing vs new signal inputs).

---

## Verified findings (file:line)

### 1. What the code actually is

| Component | Reality | Evidence |
|---|---|---|
| Panel | 289,351 pair-days × 48 features, 58 pairs, 2008-09-25 → 2026-09-08; 2,751,187 feature cells NaN-filled (= 19.8%) | `data/fx_expert/panel_meta.json:410-411,462-464`; **DERIVED**: 2,751,187 / (289,351 × 48) = 19.81% |
| Model | 3-layer pre-norm transformer, `d_model` 96, 4 heads, one scalar head on the **last** timestep of a T=20 window; 340,513 params for the promoted family | `model.py:26-45`; `data/fx_expert/train_g162.json:18` |
| Label | `fwd{h} / (vol20 · √h)` clipped ±5 — vol-standardized h-day forward return; **sign = direction, magnitude = conviction** | `train.py:121-122`; `model.py:6-7` |
| Folds | Fixed expanding-window quarters 2-4 of unique panel days; `train = day ≤ lo − (horizon+1)` (purge = label horizon + 1); val = last 10% of train (early stop only) | `train.py:131-137,160-161,167-168` |
| Warm start | **Per-fold chains**: fold *i* of gen N inherits only `g{warm}_f{i}.pt` — the same train window. This is the 2026-09-06 leak fix | `train.py:106-110,142-147,176-183` |
| Entry thresholds | `q_long` / `q_short` / `q_mid` are quantiles of **train-fold predictions** | `train.py:187-190` |
| Gate bar | PF ≥ 1.05 **and** beats every baseline **and** ≥ 2/3 folds OOS IC > 0 **and** ≥ 2000 positioned pair-days | `gate.py:36,254-265` |
| Baselines | buy-and-hold, RSI(14) MR, mom20 sign, random-matched — same predictions, same cost model | `gate.py:218-232` |
| Loop | ε-greedy (ε=0.4) bandit over HPARAMS, reward = mean OOS net PF; promote only on gate PASS; warm-candidate = best positive-IC checkpoint even if the gate failed | `loop.py:64,79-87,138,167-188` |
| Serve | Loads `loop_state.json["best"]`'s checkpoint, scores the panel's latest date, writes `signals.json` (rank book → weights) | `serve.py:27-31,56-69` |

### 2. Lookahead and leakage — what is clean, and what is not

**Clean (verified by reading the code paths):**

- Purge is correct: train rows satisfy `t ≤ lo − (h+1)` for an h-day label — one day more than
  the h-day label span (`train.py:160`).
- Entry thresholds come from train predictions only, never test (`train.py:187-190`).
- The hysteresis rule (`thr`, `thr_cont`) and the rank book are sequential in date and charge
  round-trip cost on every position change (`gate.py:77-96,109-133,136-163,48-57`).
- Evidence features are backward-looking: rolling/shift windows, `diff`, causal 252d z-scores
  (`data.py:60-88,93-95,106`), cross-sectional means computed same-date only (`data.py:277-279`).
- The per-fold warm chain is genuinely leak-free: fold boundaries are quantiles of a growing day
  list, so fold *i*'s train window only ever moves later (`train.py:133-137`), and a warm
  checkpoint from gen N saw only data before gen N+1's fold-*i* test window.

**D1 — the standardization statistics are computed from the wrong rows (`VERIFIED`, leak).**
`train.py:124-129` builds `idx_keep`/`win_k` as **global** row indices into the full panel and
then filters `y`, `fh`, `pi`, `day_k` through `idx_keep`. `tr_idx` at `train.py:167` is therefore
a position in the *filtered* arrays — and `train.py:170-171` indexes the **full** panel with it:

```python
X = X_all                                    # train.py:128  (full panel)
tr_idx = np.where(tr_mask)[0]                # train.py:167  (positions in FILTERED arrays)
mu = X[tr_idx].mean(axis=0)                  # train.py:170  ← wrong row set
sd = X[tr_idx].std(axis=0)                   # train.py:171
...
X_tr = torch.from_numpy(Xs[win_k[tr_idx]])   # train.py:176  ← correct rows (global indices)
```

`X[tr_idx]` therefore selects rows `0 … n_train` of the **pair-major** panel — i.e. whole pairs
(alphabetical: `AUD_CAD`, `AUD_CHF`, …) across their **entire** history, rather than the fold's
train rows. For fold 0 of g162 (`n_train` 61,585 ≈ 12 pairs) that prefix spans 2008 → 2026-09-08
while the fold's test window starts 2012-06-20 (`data/fx_expert/train_g162.json:20-33`). The
documented invariant "Standardization uses train-fold stats only" (`train.py:9`) and the doc's
"train-only standardization … no lookahead" (`docs/agents/research/fx-expert-loop-2026-09-06.md:16,90-91`)
are both **false as coded**. Every one of the 163 generations was trained under it, including the
promoted g151. Magnitude is **SHOULD VERIFY** (a re-run with `X[idx_keep[tr_idx]]` would settle
it; not run here). Note the same `mu`/`sd` are what `serve.py:48` and `fx_expert_lane.py:163`
apply to live scoring, so training and serving are at least self-consistent.

**D2 — COT positioning carries a 3-day lookahead (`VERIFIED`, leak).**
`data.py:109` reindexes the CFTC series at its **report date** with no publication lag:
`f["cot_z"] = cot_z.reindex(bars.index)`. The series is dated at the Tuesday report date
(`scripts/fetch_exog.py:40-42,63`; `data/exog_cache.json:1`, `COT:EUR` keys are consecutive
Tuesdays `2006-12-05, 2006-12-12, …`), but CFTC publishes Friday. The project already encodes
the correct convention elsewhere: `scripts/signal_gym.py:71-84` subtracts
`timedelta(days=3)` (`:84`) before using a COT value, and `scripts/worlds.py:16` notes COT "travels with
each source date". Because `reindex` (no ffill) leaves the value only on Tuesdays, the effect is
bounded — roughly 1 row in 5 carries a non-zero `cot_z`, and those rows see ~3 days of future
positioning. Effect size **SHOULD VERIFY**.

**D3 — same-bar close fill (`VERIFIED`, optimistic convention, not lookahead).**
Features at day *t* include `ret_1d = close_t/close_{t-1}`, RSI/MACD/ATR/range on `close_t`/`high_t`/
`low_t` (`data.py:54-88`), and the label is `close_{t+1}/close_t − 1` (`data.py:137`). The gate
earns that return from a position entered on the same `close_t` (`gate.py:48-57`). The project's
own engine contract is stricter — decisions on the **prior** close, fills on the current one
(AGENTS.md, engine integrity commit `1718f33`) — and any pre-`1718f33` metric is documented as
"optimistic by up to ~4-5pp". fxexpert does not follow that convention and its numbers are not
labelled as such.

**D4 — two FRED features are structurally dead constants (`VERIFIED` by code + data dates).**
`data.py:169-183`: `FRED:PIORECRUSDM` and `FRED:PNGASEUUSDM` are monthly, dated the **1st** of
each month (`data/exog_cache.json:1`), reindexed to a daily calendar, shifted 15 days, then put
through `rolling(252, min_periods=60)`. A 252-day window over a monthly series contains ~12
observations, never the required 60, so the z-score is NaN for the entire span and is then
zero-filled (`data.py:285`). `fred_iron_z` and `fred_ttf_z` are constant 0 across all 289k rows.
The 15-day shift is also backwards relative to its own comment ("a monthly value for month M is
public mid-M+1") — it makes the value visible mid-**M**. Moot while the features are dead, but the
lag reasoning is wrong and would bite if the rolling window were ever fixed.

**D5 — zero-fill without masks for three feature blocks (`VERIFIED`, modelling defect).**
Mask features exist only for carry/rate/COT (`data.py:98,107,110`). The H1 block
(`data.py:119-130`), the FRED block (`data.py:133-134`) and the cross-sectional block
(`data.py:277-279`) have **no** mask, so "no data" and "value is 0" are indistinguishable —
which matters precisely because 19.8% of all feature cells were NaN-filled
(`panel_meta.json:462`). This directly contradicts the module docstring's claim that "Missing
exog blocks are 0-filled with an explicit mask feature" (`data.py:9-10`).

**D6 — no financing/swap term in the cost model (`VERIFIED`, material for this book).**
The cost model is a flat per-pair round-trip constant — majors 1.2 bp, G10 crosses 1.8, EM 5.0
(`data.py:25-41`) — charged only on position change (`gate.py:55-57`). A dollar-neutral book held
5 trading days pays or receives overnight financing on every leg, and the rank book's short side
is systematically the high-yield EM crosses (`docs/agents/research/fx-expert-loop-2026-09-06.md:223-224`
notes cost-gating EM "HURTS the rank book: the high-cost pairs carry the short-side of the
factor"). The live lane *does* pay/receive swaps at the venue. Direction and size of the omission
**SHOULD VERIFY**, but it is unmodelled and unsigned in the gate.

### 3. Is the gate sound?

**What is sound:** the bar is pre-registered and unchanged (`gate.py:21-27`); baselines are
simulated on the identical predictions, protocol and cost model (`gate.py:218-232`); the
pass criteria are conjunctions, not a single metric; train-only thresholds; per-fold checkpoints;
an append-only `history.jsonl` with the gate's `reasons` verbatim (`loop.py:189-199`).

**What is not:**

**G1 — the buy-and-hold criterion was amended *post hoc*, and the exemption is not marginal
(`VERIFIED`).** `gate.py:37-45` records the human amendment: a book with `|net|/gross ≤ 0.2` is
"dollar-neutral" and is excused from the buy-and-hold comparison, which "now gates directional
books only" — explicitly "made post hoc with results in view". The promoted book's measured
`net_exposure_ratio` is **0.0356** (g151, `data/fx_expert/gate_g151.json:12`), and g137/g138 sit
at 0.027-0.036 (`fx-expert-loop-2026-09-06.md:249`). Every exempted book is ~6× inside the 0.2
boundary, so the amendment does not admit a marginal case — it exempts the *entire* rank family.
Under the **unamended** bar all three fail on exactly one reason, which is what the loop actually
recorded at the time: `history.jsonl:138,139,152` —
`"gate": "FAIL", "gate_reasons": ["does not beat baselines: {'buy_hold': 1.1427}"]`.

**G2 — the only three PASSes in the record were produced by re-running the amended gate
out-of-band (`VERIFIED`).** `data/fx_expert/gate_g137/g138/g151.json` were rewritten at
`2026-09-06 21:12:47-49 CDT` (`stat`, mtimes within 2 s of each other), i.e. **27 minutes after**
the loop run that logged g151 as FAIL (`history.jsonl:152`, `train_g151.json` mtime
20:45:24 CDT). `gate_g151.json:55-56` now reads `"verdict": "PASS", "reasons": []` while the
loop's own append-only row for the same tag says FAIL/`promoted: false`. **`history.jsonl` contains
no promotion row for g151, and no PASS row for g137/g138 at all** (**DERIVED** read-only reduction:
163 rows = 147 `FAIL` + 16 `PASS`; the 16 PASS tags are `13,14,15,19,20,21,22,25,26,27,28,29,30,32,33,35`
— **all inside the invalidated g12-g35 warm-start-leak era**). The registry entry is real and
timestamped (`data/epoch_registry.json:179-200`, `registered: 2026-09-07T02:13:15Z`,
`registered_by: "agent"`, 30 s after the gate file rewrite) — so the promotion is recorded in the
registry but **not in the loop's append-only history**, and `loop_state.json`'s `best` was set
out of band as well. *How* that edit happened is an open question (see §Open questions Q1).

**G3 — reuse of three fixed OOS folds across 163 evaluations, with no deflation (`VERIFIED`).**
The folds are recomputed each generation but from the same day list and the same three quarters
(`train.py:131-137`); the loop has evaluated the bar 163 times (147 FAIL / 16 PASS, above). The
code is honest about this (`gate.py:24-26`: "Repeated generation search inflates this bar's
effective size — the forward shadow accrual ledger, not this gate, is the real promotion
evidence") and the doc records the load (`fx-expert-loop-2026-09-06.md:93-97,244-246`). But the
consequence is not carried into any decision: the gate bar remains a **fixed** PF ≥ 1.05, so a
per-generation PASS is still treated as evidence in `loop.py:167-188` and, after the amendment,
in the registry.

**G4 — the winning generation is inside the selection noise (`DERIVED`, arithmetic over
`history.jsonl`).** Read-only reduction of the `pf` field per row:

| population | n | mean net PF | sd | max | (max − mean)/sd |
|---|---|---|---|---|---|
| clean era, tags ≥ 36 | 127 | 0.9792 | 0.0513 | 1.0846 (g151) | **2.06** |
| tags ≥ 100 | 63 | 0.9723 | 0.0624 | 1.0846 | **1.80** |
| rank era, tags ≥ 137 | 26 | 1.0008 | 0.0389 | 1.0846 | **2.16** |

The expected maximum of ~127 correlated draws from a mean-0.98 population is ≈ 2.5-3 sd — i.e.
the best-of-127 result is *at or below* what pure selection over this distribution produces. This
is a back-of-envelope argument (PF draws are neither Gaussian nor independent, and generations
are correlated through the warm chain); a formal White's Reality Check / deflated Sharpe is
**SHOULD VERIFY** and is already an open item on map #198 ("the correction statistic … depends on
the sweep's shape").

**G5 — arm count and selection surface (`VERIFIED`).** `HPARAMS` defines **25** arms, not 28:
A-J, K-X, and `AA` — there is no Y or Z (`loop.py:34-62`; `grep -c '^    "[A-Z]*": dict'` = 25).
24 were exercised; `M` never ran (**DERIVED** from `history.jsonl`). The bandit exploits on
**mean OOS net PF** (`loop.py:82,86`) and explores uniformly, so the search surface is
25 configs × 163 generations, with the reward computed on the same three folds it is then gated
on. The promoted g151 came from a config drawn under exploration (hp `U`), not from the bandit's
exploit arm (N, 42 runs, mean PF 1.0103 — `loop_state.json:50-54`).

---

## Health assessment

**The engineering is above the project's baseline; the evidence is not.** This module does the
process things most of the repo's other search efforts do not: per-fold warm chains (the leak was
found and fixed by the project itself), train-only thresholds, baselines on an identical
protocol, an append-only history with the gate's reasons verbatim, atomic state writes
(`loop.py:73-76`), and a gate that has visibly refused to promote for 127 consecutive clean
generations. Nothing here is fabricated; the docs are unusually candid (§v0.2 records a
wrongly-promoted batch and its invalidation; §v0.5 records two sim-layer bugs in the era's own
results).

**But the search's output is not currently admissible as evidence of edge.**

1. **Zero clean-era promotions.** 127 generations since the leak fix, all FAIL; the only 16 PASSes
   in 163 rows belong to the era the project itself invalidated (**DERIVED**, §G2). The one
   promoted expert (g151) passed only after the bar was amended post hoc and the gate re-run
   out of band, and the promotion never reached the append-only history.
2. **The gate's pass criterion has been satisfied exactly once, by 2.3% of PF margin, in the region
   of the selection distribution** (§G4). On the same three folds, the loop's own mean PF is
   **0.9792** (clean era) — i.e. the average generation *loses* money net of the cost model.
3. **Two independent leakage/defect classes are live in every generation trained so far**
   (§D1 train-only standardization violated; §D2 COT 3-day lookahead) plus an unlabelled same-bar
   fill convention (§D3). None of these is large enough to explain the whole result either way,
   and the direction of D1 on the reported numbers is unmeasured — but "0 PASSes in 127
   generations" is a statement about *this* implementation, not about the transformer or the panel.
4. **The live lane is running on this evidence.** `fxexp-g151` is an accreting lane on the OANDA
   practice account (`epoch_registry.json:179-199`), rebalanced every 5 trading days from the
   g151 checkpoint (`fx_expert_lane.py:150-168`), with the Friday 2026-09-11 cut as the only
   guardrail. Being practice/demo and human-gated (ADR-0009 §4), the account risk is bounded —
   but the lane is not currently distinguishable from noise by its own backtest, and its cost
   model omits financing (§D6), which is exactly the term a 57-leg multi-day FX book pays.
5. **The one construction that clears the PF bar loses to the benchmark that was excused from
   gating it.** buy-and-hold is PF **1.143** (g160) / 1.1429 (g161) / 1.1429 (g162)
   (`gate_g160.json:22-27`, `gate_g161.json:22-27`, `gate_g162.json:22-27`) versus the promoted
   book's 1.0846. The amended gate says that comparison does not apply to a dollar-neutral book —
   a human call, correctly flagged as post hoc — but it means no fxexpert artifact, promoted or
   not, currently beats the standing project benchmark (AGENTS.md: buy-and-hold is THE benchmark).

**Severity ranking:** evidence-integrity defects (D1, G1/G2, G3) > unmodelled economics (D6) >
data-quality defects (D4, D5, D2) > convention optimism (D3). Live-account risk stays **low** —
practice venue, shadow-first, human-gated — while *decision* risk is **high**: the subsystem is
being steered by a gate whose verdicts are not deflated, whose one PASS has an out-of-band
provenance, and whose training pipeline leaks information into its own normalization.

---

## Defects & risks

| # | Defect | Evidence | Severity | Status |
|---|---|---|---|---|
| D1 | Train-fold standardization uses rows `0…n_train` of the **full pair-major panel**, not the fold's train rows — future data (and the wrong pairs) enter `mu`/`sd` in every generation | `train.py:128,167,170-171` | **High** (leak, invalidates a documented invariant) | open; magnitude SHOULD VERIFY |
| D2 | COT z used at its Tuesday **report date**; CFTC publishes Friday. Project convention elsewhere is −3 days | `data.py:109` vs `scripts/signal_gym.py:71-84` (`:84`), `data/exog_cache.json:1` | Medium (bounded: ~1 row in 5) | open |
| D3 | Same-bar close fill: features include `close_t`, position entered at `close_t`, return earned from `close_t`. Stricter than the project's own prior-close engine contract | `data.py:54-88,137`; `gate.py:48-57`; AGENTS.md `1718f33` | Medium (optimism, unlabelled) | open |
| D4 | `fred_iron_z`, `fred_ttf_z` are constant 0 for the whole panel (monthly series vs `rolling(252, min_periods=60)`); the 15-day lag is also 1 month too short by its own comment | `data.py:169-183,285`; `panel_meta.json:453-454` | Medium | open |
| D5 | No mask features for the H1/FRED/cross-sectional blocks; 19.8% of cells zero-filled, "missing" ≡ "0" | `data.py:9-10,119-134,277-279`; `panel_meta.json:462` | Medium | open; contradicts the docstring |
| D6 | No financing/swap term anywhere in the cost model; live lane pays swaps | `data.py:25-41`; `gate.py:48-57` | Medium-High for a multi-day 57-leg book | open |
| G1 | Buy-and-hold criterion amended **post hoc**; exemption (`net/gross ≤ 0.2`) is ~6× looser than the promoted book's 0.036, so it exempts the whole family | `gate.py:37-45`; `gate_g151.json:12` | **High** (gate integrity) | recorded as a human decision; consequence not priced |
| G2 | The three amended-gate PASSes were produced by an out-of-band gate re-run 27 min after the loop logged FAIL; **no promotion row exists in `history.jsonl`**; `loop_state.json["best"]` was set out of band | `stat` mtimes; `gate_g151.json:55-56`; `history.jsonl:152`; `epoch_registry.json:179-200` | **High** (provenance) | open |
| G3 | 3 fixed OOS folds reused across 163 gate evaluations; bar is a fixed PF ≥ 1.05 with no multiple-testing correction | `train.py:131-137`; `gate.py:24-26`; **DERIVED** 147 FAIL + 16 PASS | **High** (selection) | acknowledged in code+doc, uncorrected |
| G4 | Best-of-127 PF (1.0846) sits 1.8-2.2 sd above the mean of its own selection population — consistent with selection noise | **DERIVED** from `history.jsonl` | **High** | SHOULD VERIFY formally (deflated Sharpe / White's RC) |
| G5 | Ticket premise "~28 bandit arms A..AA" is wrong: 25 defined, 24 exercised | `loop.py:34-62`; **DERIVED** | Low (record accuracy) | corrected here |
| S1 | `serve.py` writes `signals.json`, which **nothing reads** — the live lane loads the checkpoint directly. Dead seam, and the file is a misleading "shadow signal" artifact | `serve.py:81`; no reader in any `.py`/`.js`; `fx_expert_lane.py:150-168`; `dashboard.py:726` reads `claims.json` | Medium (misleading record) | open |
| T1 | `trailing_ab.py` A/B (the basis for "no SL/TP is MEASURED") runs on `oos_scores_gab1.npz` — a bespoke one-off generation (hp q=0.80/l2 0.05/h10, `warm_from: null`, never gated), **not** the promoted g151 whose scores drive the live lane | `trailing_ab.py:15`; `train_gab1.json:2-16,61`; no `gate_gab1.json` exists | Medium (generalisation gap) | open |
| T2 | Gate denominator differs by rule: `xs` uses `denom="pos"` (mean over deployed legs only), every other rule uses `denom="all"` (flat legs dilute) — the `model_alt_rule` PF in every report is therefore not like-for-like | `gate.py:58-65,188,198,205-207,215` | Low-Medium (misread risk) | open |

---

## Links to existing maps

- **#218 (FX pipeline completion)** — this is the parent context. Ticket **#226** ("Run 3 fxexpert
  generations") is the honest record assessed here; **#225** (Friday scoreboard) and **#222**
  (claims namespace bug) sit on the same loop→lane seam. §G2 (the promotion that never reached
  `history.jsonl`) is an input to #218's "lifecycle enforcement / every consumer reads the
  registry" destination — the registry is right, the *history* is incomplete.
- **#198 (deflated FX signal-family sweep)** — the designated path for the "new signal inputs"
  lever, and the map that already names the correct answer to §G3/G4: "the more hypotheses tested,
  the higher the bar", with White's Reality Check / deflated Sharpe as the undecided statistic.
  Any fxexpert re-run should be folded into this map's correction rather than evaluated against a
  bare PF ≥ 1.05.
- **#206 (exogenous alpha-mining loop, raised bar)** — "the binding constraint is the universe, not
  compute": 58 autocorrelated pairs is a thin cross-section, and the recommended instruments
  (pre-registration per family, similarity penalty vs the dead-probe graveyard V02/V03/V04/V33)
  are exactly what the 25-arm × 163-generation search lacks. §G3 here is a concrete instance of
  the load #206 wants priced.
- **#228 (whole-project health)** — this file feeds the consolidated `docs/health/2026-09-10.md`;
  sibling method and formatting: `docs/health/research/230-oanda-adapter-guards.md`.
- **ToC** — `data/wayfinder/toc/TOC.md:35-52` carries Q06-Q12 (fxexpert v0.1-v0.4, the leak, the
  amended-bar registration, the live tournament) and Q17-Q24 (Warden, claims auction, the
  trailing/TP A/B behind §T1). Q11 already frames g151 as "the first gate-PASSing trained FX
  expert, **amended bar**" and asks the only forward question that still matters.
- **ADR-0007 §3/§6** (new inputs = untested family; ToC governance) and **ADR-0009 §3/§4**
  (shadow-first, live is human-gated) are the scoping rules this assessment assumes.

---

## Open questions

1. **How did g151 become `loop_state["best"]`?** The registry entry (02:13:15Z) and the amended
   gate files (02:12:47-49Z) are timestamped 27 minutes after the loop logged g151 as FAIL, and
   `history.jsonl` has no corresponding row. Was the promotion scripted, hand-edited, or the
   product of a loop run whose history append was lost? Until this is answered, the provenance
   chain for the only promoted expert is incomplete and `loop_state.json` cannot be treated as
   loop-derived. (A read-only `git log -p` on the commit that added `loop_state.json` yields one
   commit — `ffe3978`, 2026-09-10 — so git history does not settle it.)
2. **What is the size of D1's effect?** Fixing `mu = X[idx_keep[tr_idx]].mean(axis=0)` and
   re-running a small fixed set of generations would say whether the leak flattered, hurt or was
   neutral to the reported PF/IC. **SHOULD VERIFY** — deliberately not run here. Until then, no
   fxexpert number should be cited as a leak-free measurement, and no new training lever should be
   evaluated on the current pipeline.
3. **Does the amended bar survive a deflation?** Under a correct multiple-testing correction over
   163 evaluations on 3 fixed folds, does *any* generation survive at the PF ≥ 1.05 level — and is
   the correct comparison for a dollar-neutral book PF at all, or a risk-adjusted spread over the
   financing-inclusive benchmark? This is a human `[known]`-candidate decision, per ADR-0007 §6.
4. **Should the buy-and-hold exemption have a *conditional* form?** E.g. compare the rank book to
   a financing-inclusive long-only carry benchmark at matched gross exposure, rather than dropping
   the comparison because |net|/gross ≤ 0.2 (a book at 0.036 is exempted as if it were a
   market-neutral portfolio).
5. **What is the correct cost/financing model for the live lane's actual fills?** §D6 is unmodelled,
   and the lane's realized PnL (venue journal, per-tag) is the only place it can be measured —
   ideally before the Friday 2026-09-11 cut uses a backtest-shaped scoreboard to choose survivors.
6. **Is the `signals.json` seam (S1) wanted at all?** If the lane reads checkpoints directly, the
   file is dead output that reads like the sanctioned shadow path. Either wire it and make it the
   single source, or delete it and say so.
7. **Which lever, and in what order?** The evidence favours *evaluation integrity first, then
   construction/sizing, then new inputs*: (a) fixing D1 and re-baselining is a precondition for
   trusting anything; (b) the IC is already present and regime-uniform (g151 3/3 folds 0.031;
   g160 3/3 folds 0.030 at PF 0.9976 — `history.jsonl:161`) — i.e. the *same* signal quality
   produces PF 0.998 or 1.085 depending only on the position rule, which is a construction
   result, not an information result; (c) a genuinely new input family is a #198/#206-sized
   deflated sweep at a raised bar, and the current input block is not even fully live (D4: 2 dead
   features; D5: 19.8% zero-filled without masks). **The strongest next lever is construction —
   but only after the evaluation is repaired**, because today's construction comparisons are made
   through a gate whose winner is indistinguishable from selection noise.
