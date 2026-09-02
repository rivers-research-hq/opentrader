# Table of Context — OpenTrader frontier under ADR-0007

> Index of what context costs. Load only what is cheap and relevant.

## Budget

| phase | allowance | spent | remaining | used |
|---|--:|--:|--:|--:|
| oanda | 25000 | 0 | 25000 | 0% |
| _lifetime_ | — | 51218 | — | — |

## Chapters (context cost)

| chapter | est. tokens | size | staleness | status |
|---|--:|--:|--:|---|
| 01-scope.md | 699 | 2.8 KB | 3d ago | hand-written |
| 02-variables.md | 2303 | 9.0 KB | just now | rendered from ledger |
| 03-plan.md | 58 | 0.2 KB | 3d ago | hand-written |

## Raw findings log (append-only, never compacted away)

| file | est. tokens |
|---|--:|

## Checkpoints

last: `checkpoints/ckpt-04.md` (verified)

## Open questions

- Q02: Human decision queued: challenge-mode risk contract (per small-capital plan 1.3) — requires its own ADR + sandbox walkforward per ADR-0008 s4 before any E8/FTUK purchase. Proposed params (0.04 breaker / 0.02 stop / 0.04 target / 0.10 pos / 0.25 kelly) are HEURISTIC, unvalidated
- Q03: Q03 (from V11 run, added by orchestrator 2026-08-29 — operator wrote it in deployability_status.json but did not execute toc open add): paper harness has 0 closed round trips since 2026-08-01 (3 open BUY positions only) — clause 1 cannot pass on trade evidence; is the harness expected to close positions at this stage, or is the 70-day calendar clock the binding constraint (clause 3, currently 0 continuous days due to gaps)?

---

_generated 2026-09-01T17:38:43.239Z · governor: qwen38 @ http://127.0.0.1:5804/v1 · ctxCap 60000 tok_

