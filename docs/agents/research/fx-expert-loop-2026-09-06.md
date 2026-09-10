# fxexpert — recursive FX expert training loop v0.1 (2026-09-06)

The user's directive: a **recursively training and improving** system, first
expert on FX, parameter scale growing toward 10B, trained on the project's own
data. This doc records what was built, what 12 generations measured, and the
honest verdict. Everything here traces to artifacts in `data/fx_expert/`.

## What was built

Package `fxexpert/` (untracked; commits are human-gated):

| File | Role |
|---|---|
| `data.py` | Panel builder from the accrual store (`store.duckdb`): 80,000 pair-days × 36 causal features, 16 pairs, 2008-10 → 2026-09. Features: RSI/MACD/stoch/breakout/z/momentum/vol-regime/efficiency + carry + policy-rate differentials + COT z + high-impact-event proximity + **cross-sectional USD-factor means** (mom/vol/RSI breadth across all pairs) + day-of-week. Exog blocks carry explicit mask features. Labels: fwd1/fwd5, vol-standardized. |
| `model.py` | `FXExpert`: temporal transformer over a T-day window → one scalar head predicting vol-standardized 5d forward return. Params scale with d_model/layers. |
| `train.py` | Purged expanding-window walkforward: test folds = calendar quarters 2-4 (same spans as the XGBoost reference), train = everything before the fold minus a 6-day purge, val = last 10% of train (early stop only). Standardization from train-fold stats only. Warm-start from the previous promoted/warm-candidate checkpoint when the architecture matches. |
| `gate.py` | OOS portfolio sim: long top-quintile / short bottom-quintile of each fold's TRAIN score distribution (leak-free thresholds), per-pair round-trip cost heuristic (majors 1.2 pips ≈ 1.2bp, EM 5 pips). Baselines on the identical protocol: buy-and-hold, RSI(14) mean-reversion, mom20 sign, random matched to the model's position frequencies. Pre-registered bar: PF ≥ 1.05, beats every baseline, ≥ 2/3 folds OOS IC > 0, ≥ 2000 positioned pair-days. |
| `loop.py` | The recursion: each generation rebuilds nothing (panel cached), picks hyperparameters ε-greedy (ε=0.4) on past OOS IC, trains warm-started, runs the gate, promotes only on PASS, and tracks a "warm candidate" (best positive-IC checkpoint, gate or not) so failed generations still seed the next. Promoted generations register a shadow challenger in the ADR-0009 epoch registry. Append-only `history.jsonl` + atomic `loop_state.json`. |
| `serve.py` | Shadow signal seam: best promoted expert → `data/fx_expert/signals.json`. Refuses to run without a promotion — no gate PASS, no signals, by design. |

Runs on the RX 7900 GRE via the repo `.venv` torch (ROCm). ~30-50s per
generation for 0.2-0.3M params; the 2.2M-param config took ~3 min.

## What 12 generations measured

Every number below is from `data/fx_expert/{train,gate}_g*.json` and
`history.jsonl`. Baselines are OOS over the same 3 test folds (2012-17,
2017-21, 2021-26), identical cost model.

| Gen | hp | params | warm | OOS IC | folds IC>0 | net PF | verdict |
|---|---|---|---|---|---|---|---|
| 00 | B | 339k | — | 0.0040 | 1/3 | 0.904 | FAIL |
| 01 | B | 339k | g00 | 0.0231 | 2/3 | 0.944 | FAIL |
| 02 | B | 339k | g01 | 0.0227 | 2/3 | 0.953 | FAIL |
| 03 | B | 339k | g01 | 0.0204 | 2/3 | 0.946 | FAIL |
| 04 | D | 202k | g01 | 0.0058 | 3/3 | 0.902 | FAIL |
| 05 | H | 2.23M | g04 | −0.0085 | 0/3 | 0.898 | FAIL |
| 06 | G | 228k | g05 | 0.0039 | 1/3 | 0.951 | FAIL |
| 07 | B | 339k | g05 | 0.0269 | 2/3 | 0.997 | FAIL |
| 08 | H | 2.23M | g07 | 0.0001 | 2/3 | 0.894 | FAIL |
| 09 | B | 339k | g08 | 0.0279 | 3/3 | 0.962 | FAIL |
| 10 | B | 339k | g09 | **0.0291** | 2/3 | 0.956 | FAIL |
| 11 | G | 228k | g10 | 0.0153 | 2/3 | 0.974 | FAIL |

Baselines (net PF, same protocol): **buy-and-hold 1.167**, mom20 sign 0.952,
RSI(14) MR 0.877, random-matched 0.56-0.64, XGBoost reference 0.974
(`walkforward_ml_results.json`, OOS acc 0.496 ≈ random).

### Findings

1. **The recursion measurably improves the expert.** Scratch → 0.004 IC;
   warm-started chain → 0.029 IC (7×), with the best generation (g09)
   positive in 3/3 folds. Every warm-started B generation beat the XGBoost
   reference. The loop is resumable — `python3 -m fxexpert.loop
   --generations N` continues from `loop_state.json`, and the accrual store
   grows under it, so each future generation sees more data.
2. **No generation earned promotion — the gate held.** Net PF 0.90-1.00 vs
   the 1.05 bar; buy-and-hold (carry + drift) still leads everything,
   consistent with the standing project finding that buy-and-hold is THE
   benchmark. Zero registry entries is the correct outcome, not a failure of
   the registry.
3. **The failure mode is costs, not (only) signal.** Best-generation
   decomposition (g10): gross pair-day mean +0.36 bps, cost drag −0.48 bps,
   net −0.13 bps. Gross PF 1.038 → net 0.987. The model ranks weakly
   positively OOS and gives it back in turnover (~40% of pair-days
   positioned).
4. **Parameters are data-bound.** The 2.23M-param config (H) was the WORST
   performer (IC ≈ 0). ~80k training rows support ~0.1-0.4M params. **The
   10B-parameter target is data-gated, not code-gated**: the growth path is
   (a) more data — H1 panel, more pairs, the alt-data conditioning layer from
   `fx-alt-data-inventory-2026-09-05.md` (EPU/PCPS/ONI), (b) the text branch
   over the research corpus (`data/training/*.jsonl`), (c) then scale — the
   architecture already parametrizes d_model/layers, and 16GB VRAM supports
   ~1B-class training when data justifies it.

## Next levers (in expected-value order)

1. **Cost-aware training** — turnover penalty in the loss or wider
   thresholds / longer holds; the gross edge exists, the conversion is the
   problem (ToC open question Q06).
2. **Cross-sectional construction** — rank-based portfolio (long top-k /
   short bottom-k by daily cross-pair score) instead of per-pair thresholds;
   matches how FX risk is actually carried.
3. **Text branch** — distillates from the research corpus + event feeds as
   additional tokens/features (the "all of the data and research" mandate).
4. **Data engine** — H1 features, alt-data conditioning layer, more pairs.

## Protocol notes / caveats

- Purged expanding-window walkforward, train-only standardization,
  train-only thresholds: no lookahead in features (verified: all features
  are functions of data at or before t; labels are forward).
- Multiple-testing: 12 generations × 8 configs searched against the same
  OOS folds inflates the apparent IC. The gate bar (and the ADR-0009
  forward-accrual ledger for anything promoted) is the defense; g10's 0.029
  IC should be treated as an upper bound until a future generation
  re-earns it on newly accrued data.
- Costs are a labeled heuristic (flat per-pair round trips), not venue
  spreads. Venue (OANDA) stays authoritative for anything live; live order
  flow requires human signoff (ADR-0009 §4).

## v0.2 — levers 1+2, a warm-start leak, and the honest convergence (2026-09-06)

Levers 1+2 implemented: score-magnitude penalty (`score_l2`), entry-quantile
knob, hysteresis exits (hold until the score decays to the fold's train
median), dollar-neutral cross-sectional top-k/3 rule, bandit reward switched
to net PF. First run with them (g12-g35) produced OOS IC up to 0.10 and ten
gate PASSes — **invalidated**. Diagnosis: the warm-start checkpoint (saved
from the LAST fold, trained through 2021) initialized every fold of the next
generation, leaking future data into folds whose train windows end years
earlier. Fingerprint: folds 1-2 ICs 0.14-0.17 while fold 3 (no future
available to leak) stayed ~0.01. `fx-expert-g13`/`g15` registrations set to
`fail` (never traded); loop state reset.

Fix: per-fold warm chains — fold i of generation N+1 inherits only fold i of
generation N (same train window). 24 clean generations (g36-g59):

| metric | clean value |
|---|---|
| OOS IC | 0.007 (fresh) → **~0.0145 steady state**, best 0.0222 (g54, 3/3 folds: 0.056/0.008/0.003) |
| net PF | mean 0.969, best 1.021 — **0 PASSes** (bar 1.05; buy_hold 1.167 unbeaten) |
| convergence | plateau reached by ~g45; warm chains stable (no degradation), ceiling is data-limited |
| rule | thr+hysteresis > xs top-k everywhere (xs pays breadth + costs at 16 pairs) |
| params | 339k (B/J) best; 2.2M ≈ 0 IC; 14k negative — data-bound, again |

**Convergence verdict:** the recursion converges — honestly and stably — to
IC ≈ 0.015 / net PF ≈ 0.98. That is a real, small, cost-aware improvement
over the v0.1 scratch baseline (IC 0.004/PF 0.90) and over the XGBoost
reference (acc ≈ random), but it is not a tradable edge. The contaminated
batch's PF 1.30 was the leak, not learning. Hysteresis cut turnover
(pairdays ~24k → ~38k at similar IC, PF +~0.05) — lever 1 worked
mechanically; the binding constraint is signal strength per unit of cost at
16-pair daily breadth.

## v0.3 — data levers and the 100-generation picture (2026-09-06)

Data changes: panel 36 → 48 features (H1-derived daily structure: range%,
close-position-in-range, AM/PM session returns, 24h realized vol; FRED
conditioning: VIX, HY OAS, EPU, WTI ±20d, iron ore, TTF — cached in
`data/exog_cache.json` via `scripts/fetch_fred_cond.py`, materialized into
the store exog, publication-lagged 1d/15d, causal 252d z). Labels extended
to 10d/20d; purge scales with horizon. Search space grew to 18 configs
(horizon ∈ {5,10,20}).

Campaign: 40 generations (g60-g99; loop state at generation 100). **0
PASSes** — bar 1.05, buy-hold 1.165. But the plateau moved up again and the
best family is stable:

| | v0.1 scratch (g00) | v0.2 clean plateau (g36-59) | v0.3 plateau (g60-99) |
|---|---|---|---|
| best config | B (339k, h5) | B/J | **N: 340k, h10, l2 0.05** |
| OOS IC | 0.004 | ~0.0145 | **~0.021 (20 N runs; best 0.0255)** |
| net PF | 0.904 | ~0.97 | **~1.02 (best 1.039)** |
| Sharpe | −0.48 | ~−0.1 | **+0.02..+0.20** |
| folds IC>0 | 1/3 | 2/3 | **3/3 (most runs)** |
| maxDD | −0.24 | −0.14..−0.24 | **−0.08..−0.17** |

Horizon ladder (mean over runs): h5 PF 0.956 / IC 0.009 < **h10 PF 1.021 /
IC 0.021** > h20 PF 1.008 / IC 0.019 — ten days is the sweet spot; costs
amortize faster than signal decays. Params: 340k still optimal (2.2M →
0.94/0.005, 800k → 0.95/−0.006, 103k → 0.91-0.95). xs rule still loses to
thr+hysteresis. N vs P (the h5 control) differ in horizon and q — the
horizon effect is directional, not perfectly isolated.

**Convergence verdict after 100 generations:** the recursion is stable and
reproducible — from many seeds it re-finds the same plateau (N-family IC
0.016-0.026, PF 1.00-1.04, 3/3 folds). The system converges; the plateau is
below the gate. The binding constraint is now unambiguously information at
16 pairs × daily decisions, not optimization: parameter scaling from 100k to
2.2M degrades, and three rounds of data/feature/loss levers each bought
+0.05-0.07 PF with diminishing slope.

## v0.4 — universe expansion: signal up 54%, construction is the bottleneck (2026-09-06)

Data engine expanded per the human's decision ("1"): the store now holds all
42 additional tradable pure-FX practice pairs (58 total; HKD/DKK pegs
excluded by the currency whitelist) — 289k D1 bars, 6.79M H1 bars, fetched
via `scripts/fx_expand_universe.py` (guarded, resumable, additive; the venue
stays authoritative). Cost model extended to three tiers (USD majors 1.2
pips, G10 crosses 1.8, EM/others 5.0). Panel: 80k → 289k pair-days.

Campaign: 24 generations (g100-g123), loop state at generation 124.

| N-family (10d horizon, thr+hysteresis, 340k params) | 16 pairs | **58 pairs** |
|---|---|---|
| OOS IC | 0.0206 | **0.0318 (+54%), best 0.0354** |
| best gen's fold ICs | mixed | **[0.035, 0.037, 0.034] — regime-uniform** |
| net PF | 1.0210 | 1.0016 |
| Sharpe | +0.108 | +0.009 |
| maxDD | −0.120 | **−0.078** |

0 PASSes (bar 1.05; wide-universe buy-hold 1.14). Best wide generation: g121
(K) PF 1.047 / Sharpe +0.246.

## v0.5 — the construction layer works; one gate criterion stands (2026-09-06)

Position-layer levers (the v0.4 verdict said construction, not data, was the
binding constraint): `thr_cont` (conviction-sized threshold entries),
`rank` (dollar-neutral cross-sectional rank weights across all 58 pairs)
with rebalancing period, vol targeting, and EM cost-gating. Two sim-layer
bugs were caught and fixed on the way, both visible in the gate's own
baselines: a short-sign flip in `thr_cont` (short entries opened LONG
positions — negative divided by negative) and a row-position scramble in the
rank rebalance (pairs inherited other pairs' weights after day 1). The
buggy-era generations (g124-136, g139-140 vol-gated no-ops) are in history
as recorded; every number below is post-fix.

Campaign: g137-g156 (loop state at 157). The weekly-rebalanced rank
portfolio is the first construction that converts the wide-universe IC into
PF:

| rank-rebal-5 runs (post-fix) | PF | Sharpe | maxDD | OOS IC | verdict |
|---|---|---|---|---|---|
| g137 | 1.079 | +0.26 | −0.064 | 0.028 (3/3) | FAIL: buy_hold only |
| g138 (+vol target) | 1.085 | +0.28 | −0.072 | 0.031 (3/3) | FAIL: buy_hold only |
| g151 | 1.085 | +0.28 | −0.066 | 0.031 (3/3) | FAIL: buy_hold only |

All three clear the PF ≥ 1.05 bar, beat RSI-MR (0.92), momentum (0.89) and
random (0.36), and pass the fold-consistency and pair-day criteria. The
single failing criterion is the pre-registered "beat every baseline"
including buy-and-hold (1.143 on the 58-pair panel) — a dollar-neutral
long-short book versus a long-only carry-harvesting book compared on PF
alone. Cost-gating the EM legs HURTS the rank book (1.085 → 1.014-1.047):
the high-cost pairs carry the short-side of the factor. Vol targeting is
roughly neutral. Daily rank rebalancing (churn) and daily re-sizing (thr_cont)
both destroy PF — turnover is the enemy, confirming the v0.4 diagnosis.

**State of the question (ToC Q10):** the loop now holds a reproducible
construction rule (rank, weekly) that clears 4 of 5 pre-registered gate
criteria every run, at Sharpe +0.28 and half the drawdown of the
alternatives, and loses only the buy-and-hold comparison. Whether the
gate's buy-and-hold criterion should apply unchanged to a dollar-neutral
book is a human call on the human's pre-registered bar — as is option (b):
shadow-accrue the rank book under strict caps per ADR-0009 §4, which is the
only forward-looking test left. The loop, the bugs, and the evidence are on
record in `data/fx_expert/history.jsonl` (157 generations).

### Amendment and first registration (2026-09-06, human decision: "Amend")

The human amended the gate: **dollar-neutral books are excused from the
buy-and-hold criterion**, which now gates directional books only. Guard
rails on the amendment: neutrality is MEASURED (|net|/gross ≤ 0.2, not
assumed), buy-and-hold stays in the report for every rule, and the
amendment was made post hoc with results in view — acknowledged, with the
157-generation multiple-testing load, in the registry entry; the forward
shadow accrual ledger remains the real promotion evidence (ADR-0009 §4).

Under the amended bar, g137/g138/g151 all PASS (neutrality measured at
net/gross 0.027-0.036; a NaN-guard was added to the position layer after
NaN model outputs were found poisoning the neutrality measure — gross NaN
had been silently reading as 1.0). **fx-expert-g151** (PF 1.0846, Sharpe
0.281, IC 0.0309, 3/3 folds, weekly rank-rebalanced dollar-neutral book,
340k params, 10d horizon) is PROMOTED and registered as an accruing
challenger (epoch registry, accrual ledger `data/fx_expert/shadow_fills.jsonl`).
`fxexpert.serve` now emits daily rank-weighted shadow signals
(`data/fx_expert/signals.json`, 58 pairs, net +1.0 unit on 29 gross — the
pct-rank convention's structural residual, measured and within the
amendment bound). It is the first gate-PASSing trained FX expert in the
project. It has NOT traded and live order flow remains human-gated.

### Wired live — the three-expert demo tournament (2026-09-06, human directive)

Human signoff granted for demo (practice-account) trading. All three
amended-gate experts — **g137, g138, g151** (all registered accruing,
epoch 1) — are wired as lanes via `strategies/fx_expert_lane.py`:

- **Schedule**: cron 21:25 / 21:35 / 21:45 local (CDT) weekdays — cron is LOCAL time, not UTC (staggered after
  the 21:00 UTC D1 close; lane 1 does the incremental store refresh + panel
  rebuild, once daily, shared via a marker). `--once` = REAL per the
  binding cron contract; flagless = dry.
- **Book**: 2000 units of account currency per unit weight (≈$58k gross per
  expert, ≈$175k total, ~$9k margin on the $100k demo account); every order
  tagged (`fxexp-g137` etc. — tag-based attribution; the legacy fill-size
  matcher untouched); rebal every 5 trading days mirroring the backtest;
  no server-side SL/TP — holds to rebalance, all closes lane-initiated and
  tagged.
- **Arbitration** (single netted account): a symbol held by ANOTHER tag is
  only traded in the direction that increases the account net; reducing
  deltas defer to a later run. First dry-run already exercised this —
  g151's USD_CAD short deferred behind mom-k5's +2000 hold.
- **Known side effect**: the legacy lanes (mom-k5, c08-fade, h1-mom) skip
  foreign-held symbols at entry, and the rank books hold ~57 of 58 pairs —
  they will mostly sit flat this week (their open positions still close
  normally on max-hold/out-of-target). Inherent to a netted single
  account; revisit after Friday's cut.
- **Documented backtest deviations**: foreign-held legs deferred, dust
  legs (<100 units) skipped, econ-blackout not applied (the book holds
  through events by design).
- **Friday 2026-09-11, market close**: human cuts the bottom two performers
  (per-tag PnL from the ledger / venue, tags `fxexp-*`). Surviving lane
  continues; ADR-0009 accrual proceeds for all three in the meantime.

## Architectural correction — netted account vs sibling live books (2026-09-09)

The forced re-size rollout exposed a structural constraint that overrides the
three-live-books tournament design: **OANDA accounts carry one NET position
per instrument**. When sibling lanes (g137/g138/g151 — near-identical weight
vectors, but a few sign-conflicting legs from different checkpoint ranks)
hold or rebuild positions on the same symbols, netting orders close each
other's trades FIFO — three passes silently corrupting each other's books
(divergence evidence: off-target symbols 26→40, gross overshoot to $67k,
cross-lane "foreign-held" deferrals on sibling symbols).

Resolution (per ADR-0009 shadow-first doctrine):
- **fxexp-g151 (promoted best) = the live book** — 50 trades, one per symbol,
  gross $50.0k, net +$2.5k vs the +$2.0k residual, rebuilt cleanly.
- **g138/g137 = paper competitors** — their weight vectors are scored daily
  against real prices with the same cost model (same strategy family,
  disclosed). Same Friday cut, no netting war.
- **True multi-live** requires separate OANDA accounts per lane (2-min portal
  task, human-gated) — the lane script takes an account_id and the failure
  mode disappears.

Permanent fix shipped with this: the lane's exit path must use per-tradeID
closes (surgical, zero FIFO ambiguity) — proven live today (229 fragments
closed surgically, legacy lanes untouched); netting orders remain only for
same-sign opens. Also shipped: the anti-churn drift filter (skip legs whose
delta is <3% of target — price drift between passes was churning dozens of
noise fills).

## Generations 160-162 — gate FAILs on PF bar, honest record (2026-09-10)

Three-generation run (requested by human 2026-09-09 after the timer stalled
without a new PASS). All three trained on the refreshed panel (58 pairs,
date_max 2026-09-08), warm-started from g151's checkpoint (per-fold chains —
no future leak). Results:

| gen | hp | OOS IC | folds IC>0 | net PF | Sharpe | gate |
|-----|----|--------|------------|--------|--------|------|
| 160 | S (thr_cont, cap 2.0, h10) | 0.0298 | 3/3 | 0.998 | -0.01 | FAIL (pf < 1.05) |
| 161 | L (thr, h20) | 0.0217 | 2/3 | 0.943 | -0.27 | FAIL (pf < 1.05) |
| 162 | L (thr, h20) | 0.0246 | 2/3 | 0.958 | -0.19 | FAIL (pf < 1.05) |

Verdict: signal is present (IC 0.02-0.03, consistent with the wide-universe
evidence of ~0.032) but the rank-book construction does not convert it into
PF ≥ 1.05 on the current 58-pair panel. The gate held — nothing promoted.
No new expert registered. The binding constraint remains: positive IC with
PF < 1 means the position rule is leaving money on the table (or paying it
away in costs) — the next lever is construction, not more training.

Also recorded this session (enforcement wiring, map #218):
- expert_lifecycle v2 wired into lane/trail/warden/auction/mid-train;
  probation+reprieve sync (warden → registry, cap 0.5/1.0).
- `_release_claims` namespace bug FIXED: registry IDs (`fx-expert-*`) vs
  auction tags (`fxexp-*`) never matched — a cut released 0 claims silently.
  Now maps between spellings and warns on 0-release.
- Sizing-fidelity audit was comparing all 57 weighted pairs per lane;
  with the claims auction each lane trades only its claimed subset, so
  unclaimed pairs counted as "missing" and fidelity read ~30%. Fixed to
  audit claimed pairs only — honest numbers: g137 94%, g138 86% (TRY
  halt-deferrals), g151 83% (foreign-net deferrals).
- Mid-week forced rebalance (human asleep, agent-executed 04:30 UTC):
  77 fills, live books now claim-aligned (g137 18/18, g138 20/22,
  g151 16/18 + 1 halt-deferred USD_TRY exit pending).
