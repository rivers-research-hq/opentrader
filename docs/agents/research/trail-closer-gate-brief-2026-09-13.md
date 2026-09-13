# Decision brief: the live 5-minute REAL-mode trail-closer (human gate)

- **Timestamp:** 2026-09-13. Prepared for the human gate flagged out-of-scope
  in map #243 ("the live 5-min REAL-mode trail-closer decision").
- **Format:** evidence first, then options. The decision stays with the human.

## State of the world (finding, before any option)

**The closer is already live.** `fx-trail-check.timer` fires every 5 minutes
and the service unit's `ExecStart` carries `--once`, which per the binding
cron contract means REAL mode: `fx_trail_check.py` closes venue trades
per-tradeID and writes ledger rows. Journal count since 2026-09-10: **829
runs, every one `(live)`, never dry**. Ledger trail-close rows: **0** — no
trigger has fired yet, so realized damage so far is zero.

Provenance: the unit was created with `--once` from birth (2026-09-10; file
`strategies/fx_trail_check.py` last touched 2026-09-10 19:45, commit
46c5d46). No recorded human approval found for REAL mode. This is the same
provenance-gap class as #246: the gate was crossed silently. Surfaced, not
buried, per the audit rules.

## What the closer is

Per-leg selective trail (2.0 ATR from per-trade peak/trough) + TP (3.0 ATR
from entry), evaluated every 5 minutes against live prices; triggered legs
close surgically by tradeID; ATR is the 14d max(high)/close heuristic from
the accrual store. Scope: the three fxexp lanes, lifecycle-gated.

## Evidence

1. **OOS A/B (run 2026-09-13, `fxexpert/trailing_ab.py`** — same OOS folds,
   scores, and cost model, daily-bar sampling):

   | variant | PF | Sharpe | bp/day |
   |---|---|---|---|
   | baseline (hold to rebalance) | 0.604 | −1.83 | −52.84 |
   | **trail 2.0 ATR (the live config)** | **0.589** | −1.93 | **−53.81** |
   | trail 1.0 / 1.5 / 3.0 | 0.560–0.594 | — | −53.8 to −55.3 |
   | tp 2.0 / tp 3.0 | 0.599–0.603 | — | −53.0 to −53.5 |

   Every forced-exit variant loses to hold-to-rebalance; the live
   configuration costs ≈ **−0.97 bp/day** measured. Directionally identical
   to the equity-tournament rule ("forced exits / trailing stops destroy
   returns"). Boundary, stated: this is ONE generation's OOS scores (gab1)
   in a losing window (baseline PF 0.604) — the delta direction is what
   matters here, not its precision.

2. **Live↔measured sampling mismatch:** the A/B evaluates triggers on daily
   closes; the live job samples every 5 minutes. Same threshold, finer
   sampling → strictly more trigger opportunities → the measured −0.97
   bp/day is an **optimistic** bound for live behavior.

3. **The lanes are unprotected by design** (`fx_expert_lane.py`: "no
   server-side SL/TP (the backtest holds to rebalance)"). The closer is the
   only intraday exit mechanism; without it, positions ride to the next
   daily rebalance — which is exactly the measured baseline world.

4. **Observed live trigger rate: 0 in 829 runs** (the 2×daily-ATR trail is
   wide). Realized harm so far: none. The exposure is contingent, not
   incurred.

5. **Governance:** the repo's claims rule — a backtest claim must clear the
   deflated bar before live behavior changes. Here the deflated-relevant
   evidence points the other way (all variants worse), and the feature went
   live anyway without a gate.

## Options

- **A. Demote to DRY (recommended).** Remove `--once` from the unit
  (`systemctl --user edit fx-trail-check.service` → ExecStart without
  `--once`, daemon-reload, restart timer). Keeps the per-leg peak telemetry
  and the would-close audit trail; stops real order flow; aligns live
  behavior with the measured evidence; fully reversible. Re-adoption
  requires an A/B variant that beats baseline OOS *and* survives the
  deflated bar, per the live↔measured contract.
- **B. Keep live as-is.** Justification would be crash insurance; but the
  measured evidence is negative, the sampling mismatch is unmeasured
  additional downside, and it normalizes the crossed gate.
- **C. Kill the timer entirely.** Also stops the dry telemetry (per-leg
  peaks feed give-back analysis). Strictly more destructive than A.
- **D. Harden and keep live** (TP-only at 3×ATR ≈ measured-neutral). Still
  real order flow on an un-gated feature with a sampling mismatch; the
  measured edge vs baseline is ~−0.2 bp/day. Not recommended.

## Recommendation

**A** — demote to dry today; record the decision on the tracker; fold any
future re-adoption into the exogenous-mining map's raised promotion bar.

## DECIDED (2026-09-13, human): Option A — demoted to DRY

Applied via `~/.config/systemd/user/fx-trail-check.service.d/override.conf`
(ExecStart without `--once`) + daemon-reload + timer restart; verified the
next run reports `(dry)`. The misleading `"... simulated exits (live)"`
print was fixed to `"trail exits (DRY — no orders sent | LIVE — real closes
sent)"` so mode is never ambiguous in the journal again. Re-adoption of any
forced-exit variant requires it to beat hold-to-rebalance OOS **and** clear
the deflated bar, per the live↔measured contract.
