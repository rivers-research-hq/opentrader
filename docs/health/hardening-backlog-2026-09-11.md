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

---

**Status at 2026-09-12:** items 3, 5, 6 closed; item 2 closed-NO-GO; item 1
closed-NO-promotion (deflated bar implemented, nothing survives); items 4 and
7 open. The live fxexp tournament (g151/g138/g137, cron 21:25/21:35/21:45 UTC
weekdays) is unchanged — the deflation bears on *promotion*, not on the
running paper accrual.
