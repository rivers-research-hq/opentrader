# RLHF spec v1 — FX learning loop (2026-08-31)

Human decision on record (2026-08-31): adopt an RLHF-style strategy for
developing and refining the trading model; Qwen3.8-27B is out of every role.
This document pins the concrete criteria the previous iteration never had
(the "training loop" that ran for a month and produced zero artifacts —
see `docs/agents/postmortem-2026-08-31.md`, root cause 1).

## 1. What learns (and what never does)

- **Target: the MoT value head** (per ARCHITECTURE: rule floor + value-head
  experts). It scores candidate entries/exits; trained experts enter through
  the signal gym + epoch registry + human signoff like every rule-based
  candidate. **The model never self-promotes and never touches the venue
  directly.** Incumbent order flow is human-gated (ADR-0009 §4).
- **Not an LLM finetune.** The dead August trainer was an LLM pipeline
  (unsloth/trl) with no feedback source. Until there is a real reason to
  finetune a language model, none is trained.

## 2. Reward structure — where each signal comes from

| Signal | Source | Trust |
|---|---|---|
| Environment reward | realized PnL per round trip, real OANDA ids (`data/fx_ledger.jsonl`) | ground truth |
| Simulated reward | shadow paper PnL, spread-adjusted (`data/fx_shadow_ledger.jsonl`) | labeled `paper: true`, never mixed with real fills |
| Counterfactual | fired-but-not-selected signals (`data/fx_shadow_fires.jsonl`) | off-policy; value-head training data only |
| Human feedback | approve/veto rows (`data/fx_review.jsonl`) via `strategies/fx_review.py` | preference layer; overrides reward shaping, never overrides the ledger |

The market is the primary reward (objective, dense enough at trade
granularity). RLHF's role is what humans are actually better at: vetoing
degenerate behavior early, risk-shape constraints, promotion judgment.
Sentiment/positioning (COT) enters as gym candidates with exogenous,
point-in-time data — `scripts/fetch_exog.py` (weekly, cron Sat 09:00).

## 3. Data schema (frozen now, so collection starts immediately)

Trajectory row (built from ledgers + OANDA bars at entry/exit):
```
{ts, lane: fx|shadow, symbol, action: enter|skip|exit,
 state: {closes[21], atr14, fade_depth, cot_z, spread, day_of_week},
 outcome: {r_multiple, pnl, hold_bars, exit_reason},
 counterfactual: bool,               # fire not selected
 label: {verdict: approve|veto, note, ts} | null}
```
Preference pair (DPO input, built from label rows on the same state or
same-day ranking): `(state, chosen_action, rejected_action)`.
Builder: `scripts/build_trajectories.py` (to be written when volume gates
pass — schema is pinned now so the ledgers already record what it needs).

## 4. Gates — nothing trains until all volume gates pass

| Gate | Bar | Why |
|---|---|---|
| V1 shadow volume | ≥30 closed shadow round trips | PF estimate needs n |
| V2 incumbent volume | ≥10 closed real round trips | real-execution transfer check |
| V3 human labels | ≥50 labeled decisions, ≥10 of them vetoes | a reward model with 10 examples is a coin |
| V4 ledger reconciliation | shadow state vs ledger vs venue snapshot drift = 0 | postmortem root cause 1 |

## 5. Training gates — a trained model must clear all of them

| Gate | Bar |
|---|---|
| T1 veto recall | value head reproduces ≥90% of held-out human vetoes (rank features below the entry cut) |
| T2 rank agreement | ≥80% Kendall-τ agreement with human labels on a 20% holdout, split by time (no random split — nonstationarity) |
| T3 non-inferiority | on the gym walkforward + shadow replay, model-scored selection PF ≥ candidate's own top-2 PF − 0.1 |
| T4 no lookahead | all features point-in-time (COT 3-day publication lag enforced in Ctx.exog; decisions on prior close) |
| T5 seam | promotion only via epoch registry + human signoff; auto-promotion into shadow registry with full artifact log (ADR-0009 §4) |

Stage order: SFT on outcomes first (value head regression on r_multiple,
V1–V4 data), then DPO on preference pairs (V3 volume). If SFT alone clears
T1–T5, DPO is optional — measure, don't assume the preference layer helps.

## 6. Timeline — parallel, not gated on the A/B

The shadow A/B verdict (c08 vs incumbent) and the RLHF data engine run at
the same time; the A/B does not block training prep:

- **Now**: fires + ledger events accumulate; human labels accumulate via
  `fx_review show` / `fx_review label ...` (2 min/day is sufficient).
- **~2–3 weeks**: V1 likely met (16-instrument book ≈ 2× signal frequency
  of the 7-major book); COT weekly refresh feeding gym candidate variants
  (threshold sweeps are NEW candidates, each falsified independently —
  c08's z=1.5 was a single a-priori threshold, not a sweep).
- **~3–4 weeks**: `build_trajectories.py` + first SFT pass; T1–T5 measured
  on the walkforward harness, not on vibes.

## 7. Honest risks (recorded, not hidden)

- Small n everywhere: PF CIs at n=20–40 are wide; the equities program's
  lesson (single-window OOS lies) is why V1/T3 use walkforward + forward
  replay, and why threshold variants are treated as new candidates.
- Preference noise: human labels late at night are data too; the note field
  and timestamps let the builder down-weight low-effort sessions.
- Reward mismatch: shadow PnL is simulated (no requotes/slippage); V2 exists
  to catch optimistic transfer before anything trains on it.
- A crowded-COT filter that worked over 2024–26 may decay with the rate
  cycle; c08 stays subject to the same decay watch as every expert.

## 8. Artifacts of record

- Preference store: `data/fx_review.jsonl` (append-only, sole writer
  `strategies/fx_review.py`)
- Fire log (counterfactuals): `data/fx_shadow_fires.jsonl`
- Exogenous cache: `data/exog_cache.json` (regenerable, `scripts/fetch_exog.py`)
- Registry: `data/epoch_registry.json` + append-only `data/epoch_registry_log.jsonl`
