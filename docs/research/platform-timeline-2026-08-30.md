# Platform go-live timeline — 2026-08-30 (evening)

Companion to `go-live-game-plan-2026-08-30.md`. Human directive: **OANDA FX
demo trading goes live today; first real deposit initiates once demo proves
out.** Dates below are commitments with owners, not aspirations.

## Track B — OANDA FX (priority)

| When | What | Owner | Proof |
|---|---|---|---|
| **Today (Sun 08-31)** | `exchange/oanda.py` built (ExchangeBase: balance, D1 candles, market orders, close, restore_ledger) + round-trip proof on practice API | cloud agent (direct, division v2) | verbatim API output: BUY 100 EUR_USD → position → close → net 0 |
| **Today** | FX demo book live: fills ledger + daily cycle cron (weekdays, mirrors lanes pattern) | cloud agent | first fills in `data/fx_ledger.jsonl`; cron line installed |
| Mon 09-01 – Fri 09-05 | Expert strategy mapped onto FX majors (ADR-0008 bridge: laggard/multiasset class) — qwen opentask job | local 27B (bounded card) | FX book positions carry the expert's name in the track |
| **Week of 09-01** | Exit paths observed live: stop / target / 14-day hold. ADR-0002 permits force-testing rare exits with synthetic positions — done in sandbox, not on the demo book | qwen card | ≥3 closed trades, 2 exit paths, reconciliation: OANDA API balance vs local book <0.1% (real venue reconciliation — the one C1 field that was always null) |
| **Gate review: Sep 7–14** | Human reads the FX scoreboard; if plumbing fidelity holds → **first real deposit decision (D4)** and practice→live switch | HUMAN | checklist: slippage measured, kill switch set (10% halt), faithful-replica diff, ADR-0005 entry bans encoded if FTMO-bound |
| Sep 14+ | Real money at 1% on FX majors; ladder 1% → 10% per Runway on continued fidelity | machine + human gates | Runway log |

**Fastest realistic real-money date: Sep 14.** It is gated on ~2 weeks of
clean demo evidence, not on build time — the build lands today.

## Track A — Crypto spot (running, head start)

| When | What | Proof |
|---|---|---|
| Running now | Paper book accruing (3 positions, fills ledger clean) | `data/fills_ledger.jsonl` |
| Mon 09-01 17:30 | First shadow-driver accrual (fwd_n=1) | `live_router_state.json` fwd_n fields |
| ~Fri 09-05 | 5 accrual days → **C2 becomes measurable** (fwd-only protocol, D1) | V11 run reports it |
| ~Sep 12 | Current positions hit 14-day max hold → closes → C1 trades accumulate | closed_trades ≥ 3 |
| **~Nov 8** | C3: 10 weeks continuous (clock started Aug 30, restart-safe since) | V11 clause 3 ✓ |
| **Nov 8+** | Crypto gates event → real money at 1% if 3/3 green | human review |

## After both books are live — what comes next (sequence, not speculation)

1. **Runway ladder 1% → 10%** per book, gated on continued fidelity + shadow
   persistence (ADR-0002 consequences). Each rung is a review, not a date.
2. **Prop challenge prep** (the revenue vehicle, ADR-0005/0008): challenge-mode
   risk ADR (Q02 — unresolved), venue-specific sim extension, verified current
   firm rules, trust check. The FX real-money track record from Track B is the
   application evidence. Purchase only after that ADR.
3. **Capital-gated unlocks** (thesis §6): Kraken futures paper-validation at
   ~$1–5k; US stocks when fees amortize; options far-future.
4. **The self-improvement loop starts earning its name**: fwd_n evidence
   accrues → #156 seam (decided per memo) → gate-passing experts enter the
   registry → weights evolve on forward data. The loop that was "seeded once
   from static evidence" (V10) closes on real books.
5. **Ops quality queue**: Q4_K_XL partial-offload A/B (serving quality),
   opentask base-context trim, 4B-tier routing for compaction calls.

## Standing rules (unchanged)

- Sandbox-first for code; demo/practice accounts are the proving ground.
- No real deposit without the Phase-2 checklist signed by you.
- The scoreboard is `data/wayfinder/deployability_status.json` + Friday V11.
- C2 monetization stays suspended until deployability (ADR-0007 §7).
