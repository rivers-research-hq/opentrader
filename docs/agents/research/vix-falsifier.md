# VIX Exogenous Falsifier — Verification & Final Verdict (issue #91)

Status: VERIFIED / FINALIZED (research-only pass, no code changes). Ticket #91 on
darylerivers/opentrader: "Exogenous data falsifier — VIX day-regime rule is a
SIGNIFICANT capturable edge".

## 1. Verdict (one line)

**REAL and capturable within the tested fullcross window** — the VIX day-regime rule
clears the pre-committed 95th-percentile date-clustered bar (98.6th/96.2nd, z=+2.31/+2.38)
with a coherent fat-right-tail mechanism and reproduces bit-for-bit on re-run; however the
later full-history 3-era battery (registry universe) and the ticket's own OOS comments show
the edge is strongest in the early era — treat as candidate gate, not confirmed live edge.

## 2. Artifact paths

| Artifact | Path | Notes |
|---|---|---|
| Fullcross rows (400k / 1,988 syms) | `/home/mrc/opentrader-sandbox/data/setup_search/fullcross_shards/shard_{0..3}.pkl` (100k rows each) | 7,522 dates, 1996-07-01 → 2026-05-28, bar range 0–7634 |
| FRED backfill cache (7 series) | `/home/mrc/opentrader-sandbox/data/fred_backfill.pkl` | vix, 10y, 2y, breakeven, cpi, unemp, fedfunds; through 2026-08 |
| Raw-signal falsifier script | `/home/mrc/opentrader-sandbox/scripts/exogenous_falsifier.py` | FRED backfill → as-of ffill → z(250) → deep-tail DSR |
| Day-level capturability test | `/home/mrc/opentrader-sandbox/scripts/vix_capturability.py` | tests A (hit rate), B (regime PnL), C (tradeable rule), D (tail share) |
| Date-clustered bootstrap | `/home/mrc/opentrader-sandbox/scripts/vix_rule_bootstrap.py` | shuffles DAY labels, N=2000, seed 7 |
| Residual-selector deep-tail DSR (predecessor, #90) | `/home/mrc/opentrader-sandbox/scripts/dsr_fullcross_tails.py` | |
| Older/thinner extraction (39,994 rows, 150 syms) | `/home/mrc/opentrader-sandbox/data/setup_search/fullcross_rows.pkl` | NOT the universe used for #91 verdict |
| Full-history registry (2.7M rows, 478 syms) | `/home/mrc/opentrader-sandbox/data/full_history_registry_rows.pkl` | used by the generalized 3-era battery (post-ticket) |
| Evidence ledger (generalized battery results) | `/home/mrc/opentrader/data/accumulator/catalog.db` (table `evidence`) | 19 lake datasets × era × direction; VIX latest run 2026-08-09T19:57 |
| Lake parquet of VIXCLS | `/home/mrc/opentrader/data/accumulator/lake/fred.VIXCLS.parquet` | |
| Live-path gate (prototype, not wired) | `/home/mrc/opentrader/data/vix_gate.py` + `vix_daily.pkl` (9,246 pts) | implements threshold 0.5 allow_trading |

No saved stdout log of the original run was found; all ticket numbers were
re-verified by re-running the scripts (deterministic, seed 7).

## 3. Completed tables (re-run, Aug 10 2026)

### 3a. Raw signal (test A/B) — deep-tail DSR, window bar 0–500

Ticket values are reproduced to within bootstrap noise; the closest variant is
margin-vs-screen-mean with seed 7 (exact match: VIX 99.6th).

| feature | mean margin (ticket) | margin (re-run, screen-mean) | date-boot pctile (ticket) | pctile (re-run) | verdict |
|---|---|---|---|---|---|
| VIX z | +16.03% | **+16.13%** (win-mean variant +19.93%) | 99.6 | **99.6** (win-mean variant 100.0) | mean-edge, median-flat |
| unemp z | +10.75% | +10.84% | 91.4 | 92.8 | weak |
| cpi z | ~-1% | -1.12% | 56-60 | 55.8 | dead |
| breakeven z | ~-1% | -3.95% | 56-60 | 37.4 | dead |
| 10y z | -6 to -8% | -7.61% | 0.2-4.6 | 0.2 | dead (anti) |
| 2y z | -6 to -8% | -7.51% | 0.2-4.6 | 0.2 | dead (anti) |
| fedfunds z | -6 to -8% | -5.62% | 0.2-4.6 | 4.8 | dead (anti) |

Window 1000-1250 (OOS half of the fullcross data): VIX +5.16%, 98.6th — direction holds.

### 3b. Capturability (test C — day-level rule: trade score tail only on high-VIX-z days)

**Reproduces bit-for-bit** from `vix_rule_bootstrap.py` (date-clustered, N=2000, seed 7):

| thr | hi-days | hi-day-pnl | diff vs rest | date-boot | z | verdict |
|---|---|---|---|---|---|---|
| >=0.5 | 204/704 | +12.47%/day | +11.74pp | 98.6th | +2.31 | **SIG** |
| >=1.0 | 141/704 | +10.81% | +8.35pp | 88.9th | +1.49 | no |
| >=1.5 | 91/704 | +17.79%/day | +15.69pp | 96.2nd | +2.38 | **SIG** |
| >=2.0 | 52/704 | +3.52% | -0.66pp | 69.5th | -0.04 | no |

Rule-vs-always totals (thr=0.5): +2,543.4pp over 204 days vs +2,909.1pp over 704 days —
~29% of days capture ~87% of total PnL at 3.02x the per-day rate (+12.47% vs +4.13% always).

### 3c. Mechanism (test A/D)

| measure | VIX-z >= 1 | VIX-z <= -1 | all days |
|---|---|---|---|
| n (score-screen rows, bar 0-500) | 360 | 680 | 2,115 |
| hit rate (fwd > 0) | 49.2% | 33.7% | 37.2% |
| mean fwd | +23.65% | +0.31% | +5.75% |
| median fwd | 0.00% | 0.00% | 0.00% |
| >+5% tail share | 20.8% | 14.7% | — |
| >+10% tail share | 11.1% | 9.4% | — |
| <-5% | 16.4% | 17.2% | — |

Day-aggregated (test B): high (z>=1) 141 days +10.81%/day, mid 349 days +3.55%, low (z<=-1)
214 days +0.69%.

## 4. Methodology check (as claimed in the ticket)

- **FRED backfill → as-of daily alignment**: confirmed. `exogenous_falsifier.py` backfills
  the 7 series via FRED API (cached in `fred_backfill.pkl`, full history through 2026-08)
  and reindexes with `ffill` onto the fullcross date axis — no lookahead (a value is only
  known after its own date).
- **Trailing-250 z-score**: confirmed; VIX z finite after ~250-bar warmup (2,128 screen rows
  → 2,115 with finite z; 716 → 704 days).
- **Deep-tail DSR (test B)**: ranking screen rows by exogenous z, top-quartile mean fwd
  minus base, 500-row-permutation null, seed 7. NOTE: test B's null is a **row-level
  permutation**, not date-clustered — the DATE-clustered bootstrap lives in test C
  (`vix_rule_bootstrap.py`), where day labels are shuffled (N=2000, seed 7). The ticket's
  "date-boot pctile" label on the raw-signal table therefore refers to the row-permutation
  pctile; the significant capturability verdicts rest on the truly date-clustered test.
- **Internal consistency**: every margin/pctile pair hangs together — hi-day-pnl minus
  rest-day-pnl equals the stated diff at every threshold (e.g., 12.47 − 0.73 = +11.74pp;
  17.79 − 2.10 = +15.69pp; 3.52 − 4.18 = −0.66pp); the 2,543pp/204d vs 2,909pp/704d rule
  totals re-derive exactly; hit-rate/tail-share mechanism re-derives exactly.

## 5. Caveats (why "SIGNIFICANT capturable edge" needs the qualifier)

1. **Era-dependence**: the ticket's own later evidence (generalized falsify battery,
   `data/falsify.py`/`gpu_falsify.py` on the 2.7M-row registry, 3 eras
   0-2500/2500-5000/5000-7635, evidence DB run 2026-08-09T19:57) shows VIX level-gate:
   era0 +2.156pp **100.0th survived**, era1 −0.125pp 38.1, era2 +0.593pp 94.1 → **fails the
   ">=95th in >=2 eras" survivor standard** (1/3 eras). The fullcross test window is early
   data; the edge weakens out-of-window. Ticket comment 2 reaches the same conclusion for
   industry-matched channels (in-sample SIG, OOS dead) and rates VIX as "direction held,
   thin sample".
2. **Row-bootstrap vs date-cluster** in test B (see §4): the raw-signal pctiles would be
   flattered by row-shuffle; the decision table (test C) is not affected.
3. **No live wiring**: `vix_gate.py` exists as a prototype gate (threshold 0.5, allow-trading
   on high-vol days) but is not yet in the harness rule path.

## 6. Recommendation for ticket resolution

- Close #91 as **verified/resolved for the research question**: the falsifier was run
  correctly, numbers reproduce, methodology is sound, and the VIX day-regime rule is the
  only exogenous signal to clear the bar on the fullcross deep tails.
- Carry forward as a **candidate**, not a confirmed live edge: (a) re-validate the
  0.5-1.5 band on the later eras (2500-7635) before wiring `vix_gate.py` into the harness
  rule_primary path; (b) the 3-era survivor standard (`falsify.py`) is the correct gate for
  any future exogenous claim.
