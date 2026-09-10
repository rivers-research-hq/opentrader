# Equity expert sketch — agent #2, pre-registered before gen 0 (2026-09-07)

Decision context: the human asked whether to sketch the next asset avenue. Verdict:
**sketch now, build gated on Friday 2026-09-11** — the FX forward week must speak first
(ADR-0009: forward accrual is the only currency that matters; expert #0's first fills
land tonight). This doc is the sketch: one page, gate bars pre-registered BEFORE any
training, so the second expert is born under the discipline the FX loop earned the hard
way (leak era, post-hoc amendment — see fx-expert-loop doc §v0.2/v0.5).

## Avenue: US equities, cross-sectional rank book

Why: (a) data already in-project — `data/setup_search/fullcross.pkl` (9,267 symbols ×
1,300 daily OHLCV bars ≈ 5y, verified 2026-09-07) + `wide_aligned_1300b.pkl`; (b) the
FX lesson transfers directly — the breakthrough was breadth + cross-sectional structure
(the USD factor as a rank book), not a smarter per-name signal; the equity analogue is
the market factor expressed cross-sectionally. Not crypto (out of scope, human 09-02);
not futures/commodities (no store coverage). Honest hurdles, standing as recorded:
SPY buy-and-hold beats every equity timing variant found so far (2026-08-13 finding);
the 08-12 rule-floor contract does NOT generalize across universes — treat any edge as
universe-bound until proven otherwise.

## What reuses vs what's new

| Reuse from fxexpert (unchanged) | New for equities |
|---|---|
| model.py (temporal transformer), train.py (purged expanding walkforward, warm chains, per-fold checkpoints), loop.py (bandit + recursion), gate.py machinery | `equitydata.py`: fullcross → panel (liquidity filter, causal features, xs market factor) |
| leak guards: per-fold warm chains only, NaN guards, measured dollar-neutrality | Cost model: labeled heuristic — 8bp per position change for liquid names, 15bp for ADV < $10M |
| gate verdict machinery + append-only history | Baselines: SPY buy-and-hold, equal-weight universe BH, random rank book (matched turnover), **12-1 classic momentum** (the trained model must beat the known factor to claim it adds anything) |

Feature block (price/volume only at v0 — no fundamentals/sector map in-project; fetching
one is an open item, sector-relative features defer until it exists): momentum lags
(5/10/21/63/126d, skipping most recent 1d — classic 12-1 construction), short-horizon
reversal (1-5d), vol ratios, dollar-volume (liquidity), range/efficiency, and the
cross-sectional market factor (equal-weight mean return + breadth, mirroring xs_mom).

## PRE-REGISTERED GATE (set 2026-09-07, before gen 0)

Protocol: purged expanding-window walkforward, 4 time-ordered folds over the 5y,
purge = label horizon + 1, train-only standardization and thresholds, per-fold warm
chains (fold i inherits only fold i — the FX leak fix is inherited, not re-learned).

1. **Primary bar: OOS Sharpe ≥ 0.8 AND Calmar ≥ SPY-BH Calmar over the same OOS span**
   (risk-adjusted parity with THE benchmark; raw PF vs a long-only book is
   apples-oranges — the FX amendment lesson, applied from birth).
2. **Consistency: ≥ 3/4 folds OOS IC > 0.**
3. **Beat every baseline** on the same protocol net of costs — including 12-1 momentum.
   Dollar-neutral books (measured net/gross ≤ 0.2, computed not assumed) compare against
   the L/S baselines and the risk-adjusted BH bar in (1); BH's raw PF does not gate
   neutral books.
4. **Cost honesty: report gross vs net per generation.** If cost drag exceeds the gross
   edge, the generation fails regardless of IC.
5. **Universe honesty:** survivorship check on fullcross BEFORE gen 0 (does the archive
   include delisted names? if unknown, label the panel survivorship-biased in every
   artifact it produces); liquidity filter (price ≥ $5, median dollar-volume ≥ $2M)
   fixed in code, not searched.
6. **Amendment discipline:** these bars change only by a logged human amendment,
   explicitly marked post hoc. Every searched generation is recorded in the registry
   entry's notes; the forward paper accrual ledger (ADR-0009) remains the only
   promotion evidence.

## Sequencing

1. **Now → Friday:** FX tournament runs; no equity code written.
2. **Friday 2026-09-11:** decision point. FX forward week confirms (positive accrual,
   no lane-vs-backtest drift) → green-light `equitydata.py` + gen 0. Disconfirms →
   fix FX first (breadth/alt-data), the equity sketch waits.
3. **If green-lit:** survivorship check → panel builder → gen 0-9 via the loop →
   first gate verdicts the same week. No orders without human signoff (ADR-0009 §4);
   the venue seam for an equity lane does not exist yet — that's a separate decision.
