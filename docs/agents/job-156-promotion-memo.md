# TASK — Ticket #156 "Promotion path" — DECISION MEMO ONLY (prep for human grilling)

You are the OpenTrader analyst (Qwen3.8-27B). ONE bounded task: produce a
decision memo for the human on THE promotion seam — how a gate-passing expert
enters the router's expert set. This is prep for a HITL grilling decision:
**you decide nothing, implement nothing, register nothing.** Your deliverable
is one memo file plus a question list. Faithful citation is the whole game.

## PRECONDITION — freshness

Any prior conversation above this message → STOP, reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## STEP 0 — Orient (≤4 calls)

```bash
cd /home/mrc/opentrader/data/wayfinder/toc && toc status && cat chapters/01-scope.md
cd /home/mrc/opentrader/data/wayfinder/toc && toc phase start 156-memo --allowance 25000
```
Then read (sandbox tree): `gh issue view 156` output if pasted, else work from
this card; `strategies/evolve_weights.py` (SCALE / MIN_EVIDENCE / reconciliation
pattern); `mot/mixture.py` (RegimeRouter registration + step()); ledger V06,
V07, V10 — quote them exactly.

## THE MEMO — one file: `/home/mrc/opentrader/data/wayfinder/promotion-path-memo.md`

For EACH of the three candidate seams, one section with: mechanism, what
ADR/ledger evidence supports it, failure mode if wrong, and reversibility.

1. **ValueHeadExpert registration** — gate-passing MLP becomes a live expert
   class in the harness router.
2. **VERIFIED append** — promote into `strategies/experts.py::VERIFIED` with
   gate margin as seed evidence (this is what evolve_weights reconciles from).
3. **Separate epoch-expert registry** — ADR-0006's per-(epoch, regime) keyed
   registry, shadow-first, competing-not-displacing `laggard`/`multiasset`.

Binding evidence you MUST cite (verbatim from the ledger, never paraphrased
numbers):
- V07: epoch engine verdict is **no-promotion** — both epochs FAIL (+0.945%/
  +0.533% vs the +1% gate; epoch-2 erosion 1.006% > 0.5%). ADR-0006's PASS
  narrative is corrected/unverified — the bar still stands, no candidate has
  cleared it yet.
- V06: 9 OOS-verified experts exist; `laggard` champion (OOS Calmar 1.666);
  routing/monitoring only, never live order flow.
- V10: the loop is seeded once from static evidence; #157 (shadow driver) is
  the accrual mechanism — memo must state its dependency: promotion evidence
  quality depends on #157 existing first.
- ADR-0006 bar: kept-trades mean minus candidate mean ≥ +1% on BOTH regime
  windows; erosion ≤ 0.5% on prior holdouts; beat single-global-expert
  baseline. Real data only; synthetic never enters the gate.

## DECISION QUESTIONS for the human (end of memo, max 5)

Each must be answerable with one choice, e.g.: which seam; what evidence
seed (gate margin as `sum`, `n`=min_evidence vs n proportional to sample);
compete-vs-displace; auto-promote with logged gate artifacts vs human signoff
per promotion; what happens on first regime where the new expert has no
evidence.

## CAPS AND RULES

- ≤ 25 tool calls. No implementation. No file writes outside the memo +
  ToC workspace + one heartbeat line
  (`156 heartbeat <N> did:<one line> next:<human reviews memo>`).
- Cite file:line for every code reference; ledger IDs for every claim.
- End: `toc checkpoint --allowance 4000`.
- Final reply: the memo's decision-questions section verbatim + call count.
