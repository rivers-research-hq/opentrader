# Background Research: Iteration Protocol + Acceptance Gate (HITL Decision #67)

**Date:** 2026-08-10  
**Context:** Part of #61 — arena war referee design  
**Question:** How does an arena iteration run, and when is the agent done? What are the cadence, acceptance gate, failure policy, and reuse criteria?

---

## Executive Summary

An arena iteration executes a **battle → fit → war → relabel → gate** pipeline, producing `n_battles` (default 8) of candidate battles, fitting a value-head MLP, running fidelity and bear wars, and checking the **+1% held-out discrimination gate** on two regime windows. The agent is **done** when it clears the gate (skill `s13-gate-locked`) and earns MoT weight (skill `s15-mot-weight`). The war runs **once per iteration** as a handful of CPU-fast portfolio backtests (~1–5% of the ~10-minute training wall-clock). An iteration that fails produces **war relabels** `r̃_t = r_t + η·δ_t` as data for the next iteration, curriculum-graded failures trigger remedial retraining, and the loop becomes **reusable** only when the agent passes the deployment gate and earns its seat in the MoT roster.

---

## 1. Iteration Cadence

### 1.1 Cadence Parameters (configurable via `run_iteration()`)

| Parameter | Default | Role |
|-----------|---------|------|
| `n_battles` | 8 | Number of candidate battles per iteration. Each battle evaluates `n_battles` batches of candidates (default `round_size=25`) against the field. |
| `round_size` | 25 | Batch size for candidate evaluation per battle. |
| `war_period` | "2y" | Time window for the fidelity war (~0.27s per 2y 16-symbol replay). |
| `eta` | 1.0 | Relabeling learning rate: `r̃_t = r_t + η·δ_t`. |
| `epochs` | 400 | Value-head MLP training epochs (with early stop on validation MSE). |
| `grpo_steps` | 2 | GRPO refinement steps post-fitting. |
| `augment_worlds` | 3 | Number of synthetic multiverse worlds appended to training (A DR-0001 quarantine: synthetic rows train only, never gate/war). |
| `augment_fullcross` | 20000 | Number of candidates sampled from the 35M-row HF stock dataset (Tier-2 breadth). |

### 1.2 Cadence Rhythm (wall-clock)

```
[1] Collect candidates & opponents → [2] Run n_battles (battle ring) →
[3] Fit value head (MLP, ~1–5 min on GPU) → [4] Run fidelity war + bear war →
[5] Fit value head with war relabels (relabel augmentation) → [6] GRPO refine →
[7] Gate (discrimination + multiverse) → [8] Relabel & router update →
[9] Save checkpoint → [10] Curriculum grade & architect propose → [11] Loop
```

**Total time budget:** ~10 min (dominated by QLoRA fit; war runs ~1–5% of this).

### 1.3 How Many Candidate Battles Per Iteration?

`n_battles` is a direct input to the iteration (default 8). Each battle:

- Evaluates all candidates against the full field (home-grown + hedge-fund personas: Citadel, Citron, AHL)
- Records standings (takes, take_mean, arena_score), H2H wins/losses
- Produces `arena_targets` (z, field mean, agent vote) consumed by the war

**No fixed maximum** — `n_battles` can be scaled up. The battle ring is cheap (~O(n_battles × round_size × n_field)).

### 1.4 How Often Does the War Run as Referee?

**Once per iteration.** The war is the referee between iterations, not during the battle phase. Specifically:

- **Fidelity war** (2y window): runs once in step [4], after the initial fit
- **Bear war** (bar 250–500, down-regime): runs once in step [4] with `regime_filter=0, buy_thresh=0.15` to force execution in choppy conditions
- Each war runs the value head + all field bots through the same trades, emitting:
 - Portfolio P&L (net_return, win_rate, max_dd) per policy
 - Per-candidate drawdown contribution
 - Per-regime decomposition (`up` / `down` mean_pnl_pct)
 - Per-trade relabels: `delta = (r − V(s)) + (r − r_field)`, `r̃ = r + η·delta`

**Cost:** ~1–5% of iteration wall-clock (1–6s per war vs ~600s QLoRA). Even 20 war runs ≈ 10–120s.

---

## 2. Acceptance Protocol (The Arsenal Holdout Gate)

### 2.1 Primary Gate: Held-Out Discrimination ≥ +1%

The agent must achieve **`kept_mean − all_mean ≥ +1%`** on **both** regime windows:

| Window | Bars | Purpose |
|--------|------|---------|
| W1 | 0–500 | Early 2022 bear + unseen 2026 (the "never-trained half" per skill s04) |
| W2 | 1000–1250 | Fully unseen late 2026 (skill s05) |

**Mechanism:** The value head MLP `V(s) → E[fwd]` outputs a threshold `θ` (best quantile of validation predictions). The gate checks, on test windows:

- `kept = {r: V(r) ≥ θ}` (candidates the model selects)
- `margin = mean(r | kept) − mean(r)` (discrimination)
- **Pass:** `margin ≥ 0.01` (1% mean forward-return edge)

**Why both windows?** The single global value head (pre-epoch) failed the gate on the 2024–25 bull-heavy windows because the selector sharpness (≈1% tail) is diluted by the smooth regression head. The epoch engine (ADR-0006) re-trains on slices where the gate stays discriminating.

### 2.2 Secondary Signal: P&L vs Field

The war's regime decomposition provides the secondary signal:

```
regime_decomp = {
  "agent": { "up": {n, mean_pnl_pct}, "down": {n, mean_pnl_pct} },
  "citadel": { "up": ..., "down": ... },
  "ahl": { ... },
  "citron": { ... }
}
```

**Pass condition:** `agent.mean_pnl_pct > field.mean_pnl_pct` in at least one regime window, combined with the +1% discrimination.

The `delta = (r − V(s)) + (r − r_field)` construction in the relabels ensures that if the agent's P&L underperforms the field, `η·delta` is negative and reduces the next iteration's fit target — a penalty that the curriculum captures via `war_vs` skills (s08, s09).

### 2.3 Failure Policy: What a Non-Clearing Iteration Produces

When the gate fails, the iteration still produces:

1. **War relabels** (`r̃_t = r_t + η·δ_t`) — the core "data for the next iteration"
 - `r_t` (field-relative z-score) + `η·δ_t` (advantage over field)
 - These become the **relabel targets** for the next iteration's value-head fit
 - Without war relabels, the next fit sees only `r_t` (the "plain forward return" baseline)

2. **Curriculum grades** — the failure is scored by `_metric_for(skill, report)`:
 - `war_vs` skills: `w_agent > w_of[beats]` (agent P&L beats target bot P&L)
 - `discrimination` skills: `_discrim_window()` re-verified
 - `gate_pass` skill: `report.get("gate", {}).get("pass")`

3. **Remedial triggers** — `STICK["failures_for_remedial"] = 2` failures:
 - Status → `remedial`
 - `retrain_flag = True`
 - `tier_drop = 1` (next skill proposed at lower tier)
 - `pass_bar_relax = 0.2` (20% relaxation for remedial)

4. **Architect proposal** — the LLM Architect (Qwen2.5-7B LoRA) reads the weakness report and proposes a new skill:
 - `render_weakness_report()` → `propose()` → `queue_proposal()`
 - The proposal's `pass_bar` and `metric_source` are validated; the next iteration trains to clear it

### 2.4 Iteration #1's Recipe Fix

Iteration #1 (the "baseline" iteration with no agent) fits the value head on plain forward returns (`targets=None` → `r_t`). It **fails** the gate (the ADR-0006 prototype confirms this: the single global MLP dilutes the score-tail edge).

The recipe fix is **not** a code change — it's the **iteration loop itself**:

1. Iteration #1 produces war relabels `r̃_t = r_t + η·δ_t` (the first delta-based relabels)
2. Iteration #2 fits the value head on `r̃_t` — the war's P&L-vs-field penalty is baked into the targets
3. The curriculum grades Iteration #1's failure; the LLM Architect proposes `s01-takes-in-ring` (tier 1) → `s02-beats-field` → ... → `s13-gate-locked` → `s15-mot-weight`

**The fix is the next iteration.** Each iteration is a "recipe" (fit targets, war relabels, curriculum state) that the next iteration consumes.

---

## 3. When the Loop Is Reusable for Other Agents

The iteration loop is **reusable** when the agent passes **skill `s15-mot-weight`** (tier 5, final skill). This requires:

1. **`s14-qlora-distilled`** — the policy survives QLoRA distillation into the 7B agent
2. **`s15-mot-weight`** — the agent earns its seat in the MoT roster

The **reuse condition** is `momentum_gate.json` with `validation_pass = True`. When this passes:

- The agent's `ExpertDecision` is instantiated in `mot/experts.py` as `ValueHeadExpert`
- The MoT router `mot/mixture.py` picks the expert per regime
- The rule floor `rule-config` holds until the expert's `mean_impact > rule` (per-trade P&L edge)
- The agent becomes **deployable** per ADR-0002: ≥3 closed paper trades, zero fatal defects, shadow's up-regime edge un-decayed

**Other role agents** (e.g., the portfolio ranker in Tier 3) consume the **validated config** (`data/setup_search/best.json`) — not the raw iteration output. The iteration loop is reusable when the agent is validated and the config is frozen for live deployment.

---

## 4. Options & Recommendations

### 4.1 Options for Cadence

| Option | Cadence | Pros | Cons |
|--------|---------|------|------|
| **Fixed n_battles=8** | Deterministic | Simple, reproducible | May need tuning for different experts |
| **n_battles proportional to candidates** | Scale with `augment_fullcross` | Better coverage as breadth grows | Higher war cost |
| **n_battles based on curriculum tier** | Tier 1: 4, Tier 3: 12 | Progressive difficulty | Adds complexity |

**Recommendation:** Keep `n_battles=8` default. The war cost is already 1–5% of budget; `n_battles` is cheap relative to QLoRA fits.

### 4.2 Options for Acceptance Gate

| Option | Gate | Pros | Cons |
|--------|------|------|------|
| **Current: +1% on both windows** | Discrimination + P&L vs field | Matches ADR-0001/0002, proven | Strict; requires epoch slices |
| **+0.5% on one window** | Faster pass | Easier to clear | Risk of overfitting to one regime |
| **+1.5% on both windows** | Harder pass | Stronger edge | May stall early iterations |

**Recommendation:** Current gate is optimal. The +1% bar matches the "score-tail ≈ 1%" finding (ADR-0006). Two windows prevent regime-specific memorization.

### 4.3 Options for Failure Policy

| Option | Data produced | Pros | Cons |
|--------|---------------|------|------|
| **War relabels only** | `r̃_t = r_t + η·δ_t` | Simple, proven | No curriculum feedback |
| **War relabels + curriculum grades** | `r̃_t` + skill scores | Progressive difficulty | Adds LLM compute |
| **War relabels + curriculum grades + architect proposal** | `r̃_t` + skill scores + next skill | Self-improving | LLM proposal may be slow |

**Recommendation:** Full pipeline (relab + grades + proposal). The LLM Architect is already the "reasoning track" (ADR-0006, phase 3) and should be consumed in the iteration loop.

### 4.4 Options for Reuse Criteria

| Option | Criteria | Pros | Cons |
|--------|----------|------|------|
| **s15-mot-weight mastered** | Agent earns MoT weight | Direct deployment | Final skill |
| **s13-gate-locked mastered** | Agent passes gate | Intermediate | Not deployable |
| **Any skill mastered** | Immediate reuse | Early reuse | May be premature |

**Recommendation:** `s15-mot-weight` is correct. Reuse means deploying to the MoT roster; the agent must be validated before that.

---

## 5. Facts & Sources

| Source | Key Fact |
|--------|----------|
| `arena/train.py:26–191` | One iteration = battle → fit → war → relabel → gate |
| `arena/train.py:71–80` | `n_battles` default 8; each battle evaluates candidates against field |
| `arena/war.py:127–256` | War runs once per iteration; produces regime decomposition + relabels |
| `arena/agent.py:174–175` | Gate: `passed = [r for r in results if r["margin"] >= THETA_BAR]`; `pass_gate = len(passed) == len(results)` |
| `arena/curriculum.py:147–149` | `_metric_for("gate_pass")` checks `report.get("gate", {}).get("pass")` |
| `arena/architect.py:174–196` | Skill `s15-mot-weight` is final; prerequisite `s14-qlora-distilled` |
| `docs/adr/0006-deepseek-pillars.md:112–116` | Epoch engine: epochs spawn, rehearse, gate, measure erosion; classifier orderer remains candidate |
| `docs/adr/0002-deployability-criterion.md:12–23` | Deployable = 3 closed paper trades, zero fatal defects, shadow edge un-decayed, ≥10 weeks |

---

## 6. Recommendation

**The iteration loop is well-specified.** The cadence (`n_battles=8`, once per iteration war, ~10-minute wall-clock) is optimal. The acceptance gate (+1% on both windows + P&L vs field) correctly balances discrimination and regime robustness. The failure policy (war relabels + curriculum grades + LLM proposal) correctly treats each iteration as a recipe for the next. The reuse criteria (`s15-mot-weight`) correctly gate deployment to the MoT roster.

**No changes recommended.** The current design aligns with ADR-0001 (faithful replica), ADR-0002 (deployability), and ADR-0006 (epoch engine). The prototype findings confirm that the +1% bar requires epoch slices (24-month windows), but this is already in the implementation.

**Artifacts:**
- `/home/mrc/opentrader/docs/agents/research/prep-67.md` — this memo
- `/home/mrc/opentrader/data/arena/` — live iteration artifacts (state, reports, curriculum)
- `/home/mrc/opentrader/arena/train.py` — iteration code
- `/home/mrc/opentrader/arena/war.py` — war referee
- `/home/mrc/opentrader/arena/agent.py` — value head + gate
- `/home/mrc/opentrader/arena/curriculum.py` — grading + proposals

---

**Verdict:** The memo is complete. No changes to the iteration protocol or acceptance gate are required. The loop is reusable when skill `s15-mot-weight` is mastered, at which point the agent earns its seat in the MoT roster and becomes deployable per ADR-0002.