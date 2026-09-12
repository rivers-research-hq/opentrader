# Pre-registration: forward-accrual promotion test

- **Timestamp:** 2026-09-12, written after the gate re-specification (#257,
  human-delegated) and before any forward window has been evaluated. Author:
  agent session.
- **Why now:** with the backtest promotion bar retired, "passing" needs a
  definition that is fixed *before* the evidence arrives — otherwise the same
  selection problem reappears on the forward data (choose the horizon and the
  threshold after seeing the curve). This document fixes them.

## What is being tested

That an **already-registered, eligible** expert earns a positive net return on
**forward** data — the only evidence not used to select it.

Candidates (registered before this document, nothing added after):
`fx-expert-g185`, `fx-expert-g163` (shadow candidates, no lane wired yet), and
the three live demo lanes `fx-expert-g151`, `fx-expert-g138`, `fx-expert-g137`
(tag-attributed venue accrual, running since 2026-09-06).

## The statistic (fixed)

Per lane, from the venue journal (resolver-attributed fills,
`strategies/lane_attribution.py` — never the ledger's FIFO):

- series: **daily net P&L of the lane's book**, in account currency, per unit
  of gross notional, so lanes of different size are comparable;
- primary: **mean daily net return**, its t-statistic (i.i.d. SE) and a
  stationary-bootstrap 95% CI (block 20 days, B = 20 000 — the same resampling
  as `scripts/white_reality_check.py`, so the machinery is already calibrated
  by `tests/test_wrc_calibration.py`);
- reported alongside: closed round trips, win rate, PF, max drawdown — for the
  record, not gating.

## The test (fixed)

- **Window:** the first **120 trading days** of accrual per lane, starting at
  the lane's first resolver-attributed fill under this protocol. For the live
  lanes that start is 2026-09-06; for the unwired candidates it starts when a
  lane is wired (human-gated) — none is wired today.
- **Pass condition (per lane):** forward mean daily net return > 0 with a
  one-sided bootstrap p < 0.05 **and** at least 20 closed round trips.
- **Multiple candidates:** with k lanes under test, the max-statistic must
  clear a **deflated** threshold — the same White's Reality Check logic applied
  to the k forward series (B = 20 000, block 20). Testing five lanes and
  reporting the best one without this correction would repeat exactly the
  error the deflated bar was built to catch.
- **Power, stated in advance so a null result is interpretable:** at the
  backtest-observed effect (≈1.1 bps/day) and book volatility (≈3.8 bps/day),
  ~120 trading days gives a t of ≈ 1.1/3.8 × √120 ≈ 3.2 per lane before the
  multiple-testing correction (≈2.9 after five-way deflation). A true zero-edge
  lane is expected to land near t = 0. Failing this test at 120 days is
  therefore informative, not merely "not yet".
- **What a pass buys:** eligibility for the human promotion gate (ADR-0009 §4)
  — a weight/order-flow decision that remains human. It does not change any
  live allocation by itself.

## Rules

- No candidate is added, removed, or re-tuned after its first forward fill.
- The window is wall-clock/trading-day based, not "until it looks good".
- If a lane is cut early (e.g. the demo tournament's bottom-two rule), its
  partial series is still reported in the final table — removing it silently
  would re-introduce survivorship selection.
- Any change to this protocol requires a new dated pre-registration that says
  what changed and why.

## Status

Pre-registered, not yet evaluated (0 of 120 days elapsed). The unwired
candidates cannot start until a lane decision is made; that decision is the
next human-gated step, and until it happens the honest statement is that the
system has *no* forward evidence for the fxexpert family beyond the three live
demo lanes.