# Hardening backlog — first full week findings (2026-09-11)

Post-mortem backlog from the first full FX week. Markets closed; this is the
standing work queue for the next open. Each item is a concrete finding with a
verdict and an owner/next step. Ordered by leverage.

## 1. fxexp — deflated bar not yet cleared (active)

- **Finding:** the leak-free search converges to hp `U` (rank, horizon 10),
  best g163 PF 1.2774 (IC 0.0306). g164-166 cluster at 1.27 — the search has
  plateaued just under the deflated bar.
- **Deflation:** White's Reality Check (population-max bootstrap, demean-to-1.0,
  131 clean-era gens) gives **p = 0.9821** → does NOT survive. Survival
  threshold **PF ≥ 1.2892**; g163 is 0.012 short.
- **Verdict:** no deployable edge yet. The current search round (20 gens,
  `--refresh`, started 2026-09-11) is probing whether a wider bandit sweep or
  the rank variants (V/X/AA: vol-target, cost-cap) clear 1.2892.
- **Owner:** agent. **Next:** deflate the round's best with
  `scripts/white_reality_check.py`; register only a survivor.

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
- **Owner:** agent. **Next:** add a one-line guard asserting
  `len(txns) >= last_known_count` on rebuild so a silent truncation can never
  recur.

## 6. Warden parser — Granite reasoning artifact handled (closed)

- **Finding:** the tuned model leaks `</think>` + a duplicated JSON answer; the
  live Warden's greedy `\{.*\}` regex would have failed on it.
- **Fixed:** `_extract_json` (string-aware balanced-bracket) in `fx_warden.py`
  and `eval_cbspeech.py`. Harmless for the un-tuned base, but protects any
  future model swap.
- **Owner:** done.

---

**Status at 2026-09-11:** items 3, 5, 6 closed; item 2 closed-NO-GO; items 1
and 4 open (item 1 = the active search round).
