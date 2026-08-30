# Go-Live Game Plan — assembled 2026-08-30 (night)

**Purpose:** the sequenced path from tonight's state to first real money, built
ONLY from gates the project has already accepted (ADR-0001 faithful-replica,
ADR-0002 deployability, ADR-0005/0008 venue, ADR-0007 re-ground, evolution-thesis
R2, Runway). No new gates invented; every step cites its source. Where reality
diverged from a gate's assumptions, the gap is named and given an owner.

**The one-sentence version:** going live is not a project you start — it is
ADR-0002's three clauses passing, then real money at 1%. Everything below is
the shortest honest path to those three checkmarks.

---

## Where we are tonight (measured, not remembered)

| Gate clause | Requirement | Status now | Blocking item |
|---|---|---|---|
| **C1 Plumbing** | ≥3 closed paper trades, ≥2 exit paths, zero fatal defects, reconciliation <0.1% | 0 closed trades (book reset Aug 29 by restart; 3 positions open) | continuity ticket (fills reset) + positions must actually exit |
| **C2 Edge persistence** | up-regime rule-floor edge ≥ +0.9% mean/trade, not decayed | **NOT MEASURABLE** → measurable after 5 shadow-driver accrual days (starts Mon) | measurement protocol must exclude static seed (see Gap 1) |
| **C3 Calendar** | ≥10 weeks continuous paper | 0 continuous days (10 gaps >24h logged) | continuity ticket (no more resets) + no restarts |
| Revenue vehicle | FTMO 2-Step (ADR-0005) + TradeLocker class (ADR-0008) | simmed PASS; adapter unbuilt; bridge unbuilt | sequenced behind C1–C3 by ADR-0008 |

Machinery now live: harness paper (19 staged syms, $500), shadow_scaled unit,
lanes cron (7 experts), **shadow driver cron (first real accrual: next weekday
17:30)**, V11 recompute (Fridays), headroom proxy, eval 35/35 config.

---

## Phase 0 — Repair the evidence machine (this week)

Everything else is worthless if the evidence resets again.

1. **Continuity ticket** — card ready: `docs/agents/job-continuity-ticket.md`.
   Paste into fresh qwen session. Fix: append-only `data/fills_ledger.jsonl`,
   resume-not-reinitialize semantics, explicit opt-in reset flag.
   *Done when:* simulated restart preserves cash/positions/fills (test in card).
2. **C3 clock discipline** — after the fix lands, the restart counter goes to
   zero. Rule for everyone (human included): **no harness restarts** without
   logging a gap annotation. The 10-week clock starts at the fix, not before.
3. **#156 decision** — memo is in `data/wayfinder/promotion-path-memo.md`;
   reviewer recommendations on record (seam C, marked seed, compete-not-
   displace, auto-to-shadow + signoff at live boundary, rule-floor hold).
   Human answers 5 questions → short implementation card for qwen.
4. **Close the paper trail** — post gh comments on #155/#157 (drafts exist),
   file the continuity issue, apply triage labels per
   `docs/agents/triage-2026-08-28.md`.
5. **Ops hygiene** — C2 stays suspended; watcher alerts stay on; no config
   churn on the harness (faithful replica, ADR-0001).

## Phase 1 — Accrue the evidence (weeks 1–10)

Let the machine run. Touch nothing that writes state.

- **Weekly:** V11 recompute (Fridays) updates
  `data/wayfinder/deployability_status.json` — this is the scoreboard.
  Human reads it in 60 seconds: three clauses, pass/fail, drift flags.
- **C1 accrues naturally:** the validated exit ladder (12.28% stop / 17.81%
  target / 14-day max hold, ADR-0001) guarantees positions eventually close —
  every close adds a trade + an exit path. Expect ≥3 closes and 2 exit paths
  within 2–4 weeks of normal volatility.
- **C2 measurement protocol — Gap 1, needs pinning (decision point D1, human,
  within a week):** ADR-0002's "+0.9% mean per-trade impact" was coined for the
  archive shadow engine. The forward track's current `sum/n = 0.348` mixes
  UNITS: seeded calmar-×10 values with real 1-day returns (~0.003). Required:
  measure **fwd-only** — `fwd_sum / fwd_n` (the counter the #157 fix added).
  Recommended protocol: `fwd_mean ≥ +0.9%` over a rolling 20-window sample,
  evaluated weekly by V11. Pin it as a one-paragraph annotation to ADR-0002
  (human approves; qwen drafts).
- **C3 accrues:** 10 uninterrupted weeks from the continuity fix.
- **Parallel (non-blocking):** research track (macro/sector-relative probes,
  #92) may run in the sandbox — never touches live evidence.

## Phase 2 — The gates event (week ~10+, when V11 says 3/3)

ADR-0002: *"first real money is a gates event, not a date."* When V11 reports
C1 ✓ C2 ✓ C3 ✓ with zero fatal defects in the window:

1. **Human review session** — read the V11 JSONs and the raw ledgers (audit
   gate: trust the machine-verified appendix, not prose). Human declares
   deployable (or names the failed clause and we iterate).
2. **Pre-deposit checklist** (all items traceable):
   - Real slippage measurement vs backtest model (>15bps realized = fatal,
     ADR-0002 clause 1)
   - **Exchange ledger exists** — reconciliation <0.1% finally becomes
     measurable (C1's `null` turns into a number)
   - Kill switch: absolute-$ stop = 10% of account → halt + review (Runway)
   - Faithful-replica confirmation: live config == validated config, diff shown
   - Records/tax: fills ledger export path agreed
3. **First deposit sizing** — evolution-thesis §6: crypto spot is the first
   instrument unlock at this scale; stocks need ~$1k+ for the $0.35 fixed fee
   to amortize. Default: **crypto spot, faithful config, 1% size.**

## Phase 3 — Real money at 1% (DUAL-TRACK — amended 2026-08-30, human decision)

Both books accrue ADR-0002 evidence in parallel; first real money goes to
whichever book passes its gates first. Rationale (human decision 2026-08-30):
forex is the prop instrument class (ADR-0008) — practicing it on real money
transfers directly to the challenge — and its entry bar is lowest. Crypto was
sequenced first only because its plumbing predates this plan.

- **Track A — crypto spot (head start).** Kraken spot, plumbing + fills
  evidence already accruing. Faithful config, 1% size, kill switch.
- **Track B — FX (strategic priority).** Build the venue adapter as the next
  implementation job after the continuity follow-up: TradeLocker
  (`job-157`-unblocked, card pattern proven) or OANDA v20 REST (FTMO US path,
  ADR-0005). Then paper-accrue the same three clauses on the FX book. The
  verified expert set (laggard, multiasset, bayes, kalman…) already maps to
  this instrument class per ADR-0008.
- Same gates for both books: ADR-0002's three clauses through *that book's*
  real plumbing — no instrument goes live on borrowed evidence.
- **Ladder: 1% → 10%** per book on continued fidelity + shadow persistence.
- Start the data pipeline (trades/context/fills → parquet) at first deposit.
- What "going live" does NOT include yet: prop challenge purchase (Phase 4),
  size above 10%, US stocks (fee drag at this capital), ADR-0007 §7 park list.

## Phase 4 — Prop / multi-venue (parallel, slow lane)

- ~~TradeLocker adapter~~ **promoted to Phase 3 Track B** (2026-08-30 human
  decision): the FX adapter is now on the critical path, sequenced after the
  continuity follow-up. Sandbox → demo paper-validation before any challenge
  purchase.
- FTMO bridge: OANDA-universe expert variants per `universe-bridge-matrix.md`.
- A challenge purchase requires: verified current firm rules (they change),
  venue-specific sim (`prop_challenge_sim.py` extension), trust check, and the
  challenge-mode risk reconfiguration decided via its own ADR (Q02 — still
  open). Baseline expectation stays the sim's ~939-day cadence.
- C2 stays suspended. Monetization remains behind the deployability gate.

---

## Decision points that need YOU (nothing here moves without them)

| # | Decision | When | Input ready? |
|---|---|---|---|
| D1 | Pin C2 measurement protocol (fwd-only, ≥+0.9%, rolling window) | within 1 week | yes — Gap 1 documented above |
| D2 | #156 seam + promotion rules | after memo review | memo + 5 answers drafted |
| D3 | Venue for first real money (default: Kraken spot) | at the gates event | thesis §6 |
| D4 | First-deposit amount (default: $500, 1% size) | at the gates event | Runway caps |
| Q02 | Challenge-mode risk contract (own ADR) | only before a challenge purchase | plan §1.3 + ADR-0008 §4 |

## Standing rules while this plan runs

- The 27B operates (V11, accruals, probes); cloud agents architect/review on
  request; you decide and gate (AGENTS.md role division).
- No numeric claim repeats without the ledger; no synthetic data enters gates;
  sandbox-first, always.
- The scoreboard is one file: `data/wayfinder/deployability_status.json`.
  If a V11 run stops appearing, that is the bug to fix before any other.
