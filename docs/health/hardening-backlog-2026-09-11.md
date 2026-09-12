# Hardening backlog — first full week findings (2026-09-11)

Post-mortem backlog from the first full FX week. Markets closed; this is the
standing work queue for the next open. Each item is a concrete finding with a
verdict and an owner/next step. Ordered by leverage.

## 1. fxexp — deflated bar implemented; no generation survives (closed, NO promotion)

- **Finding:** the leak-free search converges to hp `U` (rank, horizon 10).
  Best g163 PF 1.2774 pre-round; the 2026-09-11 round (g167–g188) pushed it to
  **g185 PF 1.2862** (IC 0.0298). The raw gate beats buy-hold (1.144) and the
  alt-rule (1.0046), but the margin over break-even is thin.
- **Deflation history:** the first script (population-max bootstrap over the
  recorded PF *scores*) was degenerate — the observed max is always a member of
  the resampled population, so p ≈ 0.63 regardless of the data. Replaced with
  the **return-series** implementation (#245 decision: White's Reality Check):
  every clean-era generation's daily OOS P&L re-simulated through
  `fxexpert.gate.daily_pnl_series`, then resampled in **joint** stationary
  blocks (Politis-Romano, mean block 20 trading days) so warm-start chains,
  shared folds and the shared universe keep their cross-model dependence.
- **Result (B = 20 000, era-matched population = the 89 generations that
  produced g185, 58-pair universe, 3841 common days, observed max PF 1.2923):**
  - White RC p(mean daily return) = **0.198**
  - White RC p(PF) = **0.119** (null max-PF median 1.094, 95th pct 1.448)
  - marginal (uncorrected) p of g185: 0.140 on the mean, 0.112 on PF
  - to clear α=0.05 the winner needs **≥ 2.00 bps/day**; it has 1.12.
- **Robustness:** block length 5/10/20/40/60d gives p(PF) 0.099–0.130 and
  p(mean) 0.189–0.213 — the verdict is not a block-length artifact. Full
  clean era (153 gens, 16- and 58-pair universes pooled): p(mean) 0.228,
  p(PF) 0.105.
- **Registered experts re-judged (the #245 ask):** g151 marginal p(PF) 0.137
  (mean 0.149), g137 0.155, g138 0.182. None survives; as members of the
  searched population their corrected p is ≥ the winner's.
- **Calibration (`tests/test_wrc_calibration.py`):** on synthetic zero-edge
  nulls the RC statistic rejects 0.050 at α=0.05 and the PF-space null 0.113
  at α=0.10; 73% power on a planted 4 bps/day edge. The studentized
  (Hansen-SPA-style) variants measure **liberal** (0.13–0.20 at α=0.10) and
  are reported as diagnostics only — the verdict rests on RC/PF.
- **Verdict:** no promotion, and no re-promotion of g151. The raw gate PASS is
  a best-of-89 selection and does not clear the data-snooping bar.
- **Owner:** human — decide whether the search continues (it is plateaued and
  cannot promote under the deflated bar) or the next round changes the
  information set (new inputs, not more hyperparameter generations).
  Artifacts: `scripts/white_reality_check.py`,
  `data/fx_expert/wrc_return_series.json`.

## 2. CB-speech Warden fine-tune — thesis dead (closed, infrastructure kept)

- **Finding:** QLoRA (Granite 4.2-8B, NF4 r=8, train ≤2022 = 739 docs) commits
  to directions but is **anti-predictive OOS**: directional hit-rate 36.51%
  on 2025-26 vs 50% chance (base abstains at 8.13%). Policy replay worse than
  base. Label signs verified correct → regime nonstationarity, not a bug.
- **Verdict:** NO-GO. No shadow, no `:5802` swap.
- **Kept:** the harvest→label→QLoRA→eval pipeline (`scripts/fetch_cbspeeches.py`,
  `label_cbspeeches.py`, `train_cbspeech.py`, `eval_cbspeech.py`), the
  temporal-split guard, and the parser hardening. Reusable for a different
  label or base model.
- **Docs:** `docs/agents/research/cb-speech-eval-2026-09-11.md`.
- **Owner:** human (decide if the line is worth another round with a different
  label design, e.g. minutes-not-speeches or a basket-relative target).

## 3. Attribution — resolver now complete (closed)

- **Finding:** two gaps remained after the #243 measurement repair:
  - `resolve_fill_tag` walked `tradesClosed` only — the fxexp lane's per-trade
    partial closes (`tradeReduced.tradeID`) resolved to None, leaving **55
    post-09-03 fills wrongly "unattributed"**.
  - `fx_crashtest._venue_crash_pnl` still used a 5,000-unit size matcher.
- **Fixed (2026-09-11):** resolver now walks `tradesClosed`/`tradeReduced`/
  `tradeOpened`; crash lane routed through the resolver; accrual store rebuilt
  (1591 fills, full 4104-txn journal). **0 unattributed post-09-03.**
- **Residual (pre-09-03, grandfathered):** 4 setup-period fills (08-31..09-02,
  100u USD_CAD/USD_JPY) stay "unattributed" — correctly loud, never silently
  credited to mom-k5. Not worth rewriting the append-only ledger.
- **Owner:** done (#250 closed). AGENTS.md ledger note updated.

## 4. Data-leak discipline — two leaks caught this week (standing lesson)

- **fxexpert leak:** `train.py` standardized with `X[tr_idx]` instead of the
  fold's training split — fixed (#244).
- **CB-speech leak:** the QLoRA trainer consumed the full corpus including the
  2025-26 holdout — fixed with `--year-lt` temporal split.
- **Standing rule:** every supervised loop must name its train/val/test split
  in its run log and refuse to run without an explicit temporal boundary.
- **Owner:** agent (enforce in any new trainer).

## 5. Venue-journal ingestion — fixed, but re-verify the cursor

- **Finding:** the OANDA `sinceid` endpoint caps at 1000 txns/call with no
  `pages` field; the old single-call reader silently truncated the journal to
  the first 1000 txns (masked realized P&L as "0" / cross-lane netting).
- **Fixed:** `_walk_transactions` cursor-loops via `id=`; accrual store now
  holds the full 4104-txn journal.
- **Guard added (2026-09-11):** `journal_shrink_guard()` in
  `scripts/build_accrual_store.py` refuses to write a store whose `txns` or
  `fills` count is below the previous manifest's (`--allow-journal-shrink`
  opts out; `--skip-venue` rebuilds are exempt). Unit-tested in
  `tests/test_accrual_journal_guard.py`; live read-only check the same day:
  venue 4105 txns / 1591 fills vs manifest 4104 / 1591 — monotonic.
- **Owner:** done.

## 6. Warden parser — Granite reasoning artifact handled (closed)

- **Finding:** the tuned model leaks `</think>` + a duplicated JSON answer; the
  live Warden's greedy `\{.*\}` regex would have failed on it.
- **Fixed:** `_extract_json` (string-aware balanced-bracket) in `fx_warden.py`
  and `eval_cbspeech.py`. Harmless for the un-tuned base, but protects any
  future model swap.
- **Owner:** done.

## 7. Search history is not reproducible for g124–g136 (open, disclosed)

- **Finding:** for 10 of the 153 clean-era generations the PF recorded in
  `history.jsonl` (and in the run-time `gate_g*.json`) is not reproducible
  from the stored `preds_g*.npz` + `train_g*.json` under the current gate
  code — the recorded value is lower by +0.10…+0.17. Every generation from
  g139 on reproduces exactly, and g137/g138/g151/g185 were re-stamped at the
  time (their gate files were rewritten minutes-to-hours after the run).
- **Cause:** the gate's `thr_cont`/`rank` position construction changed
  mid-search (the `gate_g124.json` written at run time shows `short_frac: 0.0`
  and no dollar-neutral amendment — the pre-fix path opened longs only). The
  window is the fix boundary, not a data defect.
- **Impact:** the recorded leaderboard for that window is stale — the hp
  bandit consumed those rows when choosing S/T/W/U/V/X — and any prose
  quoting a g124–g136 PF is quoting the pre-fix code. The deflation is
  **unaffected**: it re-scores every generation from the stored predictions,
  and the winner g185 is inside the reproducible window.
- **Owner:** agent. **Next:** annotate the ten stale rows (do not rewrite
  `history.jsonl` — it is the run log; add a sidecar `stale_scope` note) and
  have the loop's write path assert that a recorded row re-scores to itself,
  so a gate-code change can never silently invalidate history again.

## 8. Panel v2: the exogenous layer was dead; repairing it did not add edge (closed)

- **Finding (2026-09-12):** the training panel's exogenous blocks were nearly
  vacuous — `rate_diff` 0.0% non-zero, `events_5d` 0.0%, `carry` 7.4%, `cot_z`
  14.9%. Two joins were broken by currency-code mismatch: the rate table was
  keyed `US/EA/GB/CA` (FRED codes) against ISO pair codes, and the event table
  is keyed `JN/SZ/UK/EZ/CH` (calendar-feed codes) against ISO. The model had
  been fitting price-derived features almost exclusively while the docs
  claimed carry/rate/COT blocks.
- **Repaired + extended:** BIS daily central-bank policy rates for 18 of the 19
  currencies (SGD has no policy rate by design) via
  `scripts/fetch_policy_rates.py`; FRED `DGS2/DGS5/DFII5/DFII10/PCOPPUSDM`;
  gold from the accumulator lake; commodity terms-of-trade baskets for
  AUD/NZD/CAD/NOK/ZAR/JPY. Coverage now: carry 65%, rate_diff 65%,
  events_5d 67%, ToT 15% (commodity pairs only), curve/real 60%. Panel v2 =
  61 features, built to `panel_v2.npz` (the live `panel.npz` and the running
  lanes' checkpoints are untouched).
- **Verdict:** NO promotion and no measurable gain. All 8 pre-registered
  generations FAIL the raw gate (best PF 1.0225); matched fresh-init controls
  on the v1 panel score 1.0202/0.9919, so the new information is worth
  ≈0.00–0.002 PF. A weight-transfer test (g185 → 61-feature model) recovered
  the IC (0.029–0.033) but not the PF (1.03 vs 1.286).
- **The round's own defect:** hp `U/V/X/AA` differ only in the position rule;
  with fresh init and one seed they train identical weights, so 8 evaluations
  were 4 distinct models. Recorded in the pre-registration addendum.
- **Docs:** `docs/agents/research/fx-panel-v2-preregistration-2026-09-12.md`
  (+ addendum with the results).
- **Owner:** done (agent).

## 9. The gate's PF bar was noise-dominated — retired (closed 2026-09-12)

- **Finding:** across the 101-generation 58-pair population, corr(IC, PF) =
  **0.168**, and within an IC quartile PF spans 0.76–1.29 (the
  0.0291–0.0309 quartile: mean 1.063, sd 0.156). Two models with essentially
  the same IC (0.0291 vs 0.0298) score PF 1.034 and 1.286.
- **Deeper measurement (`scripts/gate_stat_study.py`, `gate_stat_study2.py`):**
  PF, Sharpe, mean return and their t-stat are **one statistic**
  (Spearman ≥ 0.985), so swapping PF for a "better" P&L statistic would have
  changed nothing; and its cross-generation ranking **does not persist** —
  year-to-year Spearman **+0.019** (225 year-pairs), first-half vs second-half
  **−0.227**, even/odd weeks +0.499. A backtest winner is a regime fit.
  An equal-weight score ensemble of all 101 generations reproduces the best
  single member (PF 1.2836 vs 1.2862) — ensembling is not a lever either.
- **Decision (human-delegated, #257):** PF ≥ 1.05 is retired as a promotion
  bar. The gate is now an **eligibility (coherence) check** — OOS IC > 0 with
  ≥2/3 folds positive, net mean return > 0 after costs, dollar-neutral book,
  ≥2000 pair-days, beats the random-matched control. Eligibility grants
  accrual, **not** promotion; promotion evidence is the forward shadow accrual
  ledger (ADR-0009 §3-4), and any *claim* of backtest edge must still clear
  the deflated bar (V-WRC) — none does.
- **Implemented:** `fxexpert/gate.py` (criteria + verdict + `write=False`
  audit mode), `fxexpert/loop.py` (no backtest ranking: hp picks by IC as a
  heuristic, registration on eligibility, `promoted` is always False),
  `scripts/gate_eligibility_audit.py`, `tests/test_gate_eligibility.py`.
  Audit: **53 of 101 generations eligible**; 48 fail on a losing net book.
- **Registered** (bookkeeping only — no lane wired, wiring stays human-gated):
  `fx-expert-g185`, `fx-expert-g163` as shadow-accrual candidates.
- **Owner:** done (agent, human-delegated). Ref ToC `V-GATE`, `V-WRC`,
  `V-PANEL2`.

---

**Status at 2026-09-12:** items 3, 5, 6, 8 closed; item 2 closed-NO-GO; item 1
closed-NO-promotion (deflated bar implemented, nothing survives); items 4, 7
and 9 open — **item 9 is the leverage item**. The live fxexp tournament
(g151/g138/g137, cron 21:25/21:35/21:45 UTC weekdays) is unchanged — the
deflation and the v2 round bear on *promotion*, not on the running paper
accrual.
