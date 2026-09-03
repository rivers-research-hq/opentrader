# Plan — phases

> One phase at a time. Each phase consumes part of the token allowance;
> `toc phase start <name> --allowance N` opens a budget window.

## Phase oanda (open) — FX first-trader evidence
- goal: accrue clean FX trade evidence on the OANDA practice account
  (venue-authoritative), through the five lanes; feed ADR-0002 clause-1
  evidence and the crash-test gap measurements.
- state after 2026-09-02 session: accounting venue-derived end to end
  (runner guard #162/#165, adapter fill-truth + fresh prices #167,
  crashtest tracker #163); TUI = npm/Ink client only (`tui/index.js` —
  do NOT fix tui.py and call it the TUI; AGENTS.md binding).
- open decisions: Q04 adapter fork merge (human); Q05 tag-stamping at
  reconcile time (design, small); Q02/Q03 untouched (pre-existing).
- next steps: let the crons accrue; daily reconciliation at 17:10 UTC;
  review crash-lane evidence after the first real gap event.
- success exit: ADR-0002 clause-1 evidence accruing with zero fatal
  fx_defects; crash-lane curve venue-reconciled continuously.
