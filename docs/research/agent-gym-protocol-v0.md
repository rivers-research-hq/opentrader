# agent_gym protocol v0 — internal FX agent gate (frozen 2026-08-31)

- **Status:** accepted (human decisions: internal gate first, FX-only v0)
- **Claim of record:** ToC variable `BM1` — no public LLM benchmark fulfills
  the FX-agent needs (FinBen = equities task-level; InvestorBench =
  stocks/crypto/ETF, no FX; Alpha Arena = live crypto one-off). This protocol
  is the groundwork for the missing thing, scoped as an **internal gate** for
  the MoT/RLHF loop, written to public-grade rules because an ungameable gate
  is the entire point. External-facing artifacts (leaderboard, outsider docs)
  are deliberately cut until the human says otherwise.

## 1. What it evaluates

Any **policy** — an LLM served over an OpenAI-compatible endpoint, or a local
callable (rule, gym candidate, future RL value head) — acting as the sole
decision-maker of an FX book. The policy competes on *decisions* (what to
open, what to close, when), not on order-crafting: the harness owns the
uniform risk shape, exactly like the signal gym.

## 2. Environment (frozen)

- **Data:** OANDA practice D1 candles, 7 majors (the gym's cached set,
  `data/signal_gym/candles.json`, 2024-09-24 → 2026-08-27). Point-in-time: a
  policy at bar `t` sees only bars ≤ `t`.
- **Exogenous:** COT leveraged-money z-scores (`data/exog_cache.json`) with
  the 3-day publication lag — identical accessor semantics to the gym.
- **Decision cadence:** once per completed daily bar. Decisions on bar `t`'s
  close; fills at bar `t`'s close (gym convention — same verified prior art,
  no lookahead either way).
- **Execution model (deterministic matching engine):** entries at close;
  server-style exits checked on each later bar's H/L — **stop before target**
  (pessimistic); 14-bar max hold; spread cost 0.0001 × units on every exit
  (conservative; the gym's target-branch sign bug is NOT replicated).
- **Uniform risk shape (policy cannot change it):** $10k notional per
  position; ATR-14 stop 1.5× / target 2.5× (ATR over the 15 bars before the
  signal bar, gym convention); **max 3 open positions; max 1 new open per
  day.**
- **Actions:** `OPEN sym`, `CLOSE sym`, `HOLD`. Invalid output = counted as a
  protocol violation and treated as `HOLD`. Violations are a first-class
  score, not a footnote.

## 3. Episodes (v0)

Three 60-bar decision windows spread across the cached history (early /
mid / late), each with 21 bars of warmup context. Per policy: 3 episodes.
Every episode appends an **append-only ledger** (`fills` with timestamps,
reasons, PnL) and, for LLM policies, a **verbatim response log** — artifacts
or it didn't happen (postmortem rule 1).

## 4. Scoring (from the ledger only — never from self-report)

Per policy, pooled across episodes: closed trades `n`, PF, WR, total PnL,
max drawdown on the daily marked equity curve, protocol violations, token
spend (LLM policies). **Baselines run under the identical pipeline and
appear on the same scoreboard** — a policy that cannot beat `random` or the
basket buy-and-hold has failed the gate regardless of its absolute PF.

v0 baseline set: `buy_hold` (basket from day 1), `random` (seeded),
`mom_k5` (the incumbent Expert #0 rule), `c08_mr_fade_cot` (the gym
survivor rule = rule ceiling). LLMs must clear: zero unforced violations,
beat `random` net, PF > 1 pooled. Gate values are human-settable and
recorded per run.

## 5. Model harness (any model, same harness)

OpenAI-compatible `chat/completions` at a configurable `base_url` (v0 smoke
target: the local Qwen3.8-4B researcher at `http://127.0.0.1:5802/v1` — free;
subscription models come later via the same interface). Fixed, versioned
state-serialization template; JSON-action response contract (no tool-call
API dependency, so any provider works); temperature 0; token budget logged
per decision. The raw completion is logged verbatim — no metric is derived
from anything the model *says about itself*.

## 6. Integration with the existing seams (this is gate infrastructure, not a lane)

- Rules load **directly from the signal gym's candidate files** (single
  source of truth, no drift — same principle as fx_shadow).
- A trained value head enters as just another policy; RLHF spec gate **T3
  (non-inferiority)** is literally "value-head policy ≥ c08 policy on this
  scoreboard."
- A benchmark run can promote a policy into the **epoch registry** as a
  challenger with the run as `source` — same human signoff boundary as
  everything else (ADR-0009 §4).
- Daily decisions from live lanes remain with fx_runner/fx_shadow; agent_gym
  is **episodic and offline** — it gates, it does not trade.

## 7. Anti-gaming rules (frozen now, cheap to enforce, expensive to retrofit)

1. Point-in-time slicing enforced in the state builder — no code path may
   hand a policy future bars.
2. Deterministic matching engine; same fills logic for every policy.
3. Ledger + raw-response logs are append-only; the scoreboard is derived,
   never hand-edited.
4. Template version + policy version + data window hashes recorded in every
   run directory.
5. Multiple-policy survivorship: when many LLMs are scored, the winner's
   edge must be reported with n and dispersion, not just the best run.

## 8. What v0 deliberately does NOT do

No slippage model (spread-only), no leverage/margin simulation, no
intraday bars, no news inputs, no multi-asset, no public leaderboard. Each
is a protocol version bump requiring a human decision.
