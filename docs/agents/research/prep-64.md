# Research Memo: Opponent Population for HITL Decision #64

**Date:** 2026-08-10 | **Decision:** #64 "Home-grown opponent population: which variants, how generated" | **Status:** Options, facts, recommendation

---

## Executive Summary

The arena's home-grown opponent population is currently fixed per iteration and **does not evolve** between iterations. The population consists of:

1. **The validated rule config itself** — the incumbent `RuleBot(cfg)` 
2. **Jitter variants** — 3 `JitterBot` instances with ±25% param jitter 
3. **Naive baselines** — `AlwaysTake`, `AlwaysSkip`, two `RandomBot` instances 
4. **Hedge-fund personas** — `CitadelBot`, `CitronBot`, `AHLBot` 

**Total: 12 opponents** (1 rule, 3 jitter, 4 baselines, 3 personas).

**How variants are generated:** Jitter is the proven operator (±25% on 7 key params); random config (`random_cfg`) exists in the search pipeline but is **not used in the arena** — only jitter variants populate the battle field.

**Opponent evolution:** None. The field is regenerated from the same validated config each iteration. Opponents are **fixed per iteration** and do not mutate or evolve.

---

## Facts from the Codebase

### 1. Current Population Composition

The `default_field(cfg, seed)` function in `arena/opponents.py` assembles the full field:

```python
def home_grown(cfg, seed=7, n_jitter=3):
    bots = [
        RuleBot(cfg),  # validated config itself
        AlwaysTake(),
        AlwaysSkip(),
        RandomBot(0.5, seed),
        RandomBot(0.75, seed + 1),
    ]
    for i in range(n_jitter):  # n_jitter=3 by default
        bots.append(JitterBot(cfg, seed=seed + 10 + i))
    return bots

def default_field(cfg, seed=7):
    bots = home_grown(cfg, seed)
    bots += personas()  # Citadel, Citron, AHL
    # deduplicate by name
    return ordered
```

**Breakdown:**

| Category | Variants | Count |
|---|---|---:|
| Rule config | `RuleBot(cfg)` | 1 |
| Jitter variants | `JitterBot` (±25%) | 3 |
| Baselines | `AlwaysTake`, `AlwaysSkip`, `RandomBot(0.5)`, `RandomBot(0.75)` | 4 |
| Hedge-fund personas | `CitadelBot`, `CitronBot`, `AHLBot` | 3 |
| **Total** | | **12** |

### 2. How Variants Are Generated

**Proven operator: Jitter** (7 params × ±25%)

```python
class JitterBot(RuleBot):
    def __init__(self, cfg, seed=None, jitter=0.25):
        rng = random.Random(seed)
        jc = dict(cfg)
        for k in ("w_mom", "w_rev", "w_rsi", "w_brk", "w_z", 
                  "buy_thresh", "sell_thresh"):
            jc[k] = cfg[k] * (1.0 + rng.uniform(-jitter, jitter))
        super().__init__(jc)
```

- **7 parameters jittered:** weight coefficients (w_mom, w_rev, w_rsi, w_brk, w_z) + thresholds (buy_thresh, sell_thresh)
- **Jitter magnitude:** ±25% (0.25)
- **Seed isolation:** Each jitter bot gets its own RNG seed, ensuring independent behavior

**Random config (`random_cfg`) — exists but unused**

```python
def random_cfg(rng):
    return {
        "w_mom": rng.uniform(0.2, 1.0),
        "w_rev": rng.uniform(-0.5, 0.0),
        ...
    }
```

This function exists in `setup_search/loop.py` but is **not passed to `default_field()`**. It's used in the search pipeline (walkforward, crypto_leg) but not in the arena opponent population.

### 3. Opponent Evolution Between Iterations

**Evidence: None — opponents are fixed per iteration.**

- `default_field()` is called once per `run_iteration()`, using the **same** validated config (`best.json`)
- No code path updates or regenerates the opponent field between iterations
- The `cfg` argument is immutable — no mutation or snapshotting of earlier configs
- **No momentum snapshots** of the agent's own config are stored or reused
- **No trap-test negative candidates** are populated as opponents

The only "evolution" in opponents is:
- **Jitter seeds shift** (+10, +11, +12) per iteration — but this is just seed bookkeeping, not actual evolution
- **New personas** could be added (requires code change)

### 4. The 875-Config Ledger

The `data/setup_search/ledger.jsonl` contains exactly **875 entries** — each a different config with its score/summary. This is the **search ledger**, not the arena opponent population.

These configs exist in the ledger but **none are used as arena opponents** except the validated `best.json` config.

---

## Options for Population Composition

### Option A: Status Quo (Current)
- **Population:** 12 opponents (1 rule + 3 jitter + 4 baselines + 3 personas)
- **Variants:** Jitter only (±25%); random_cfg unused
- **Evolution:** None — fixed per iteration
- **Pros:** Stable, reproducible, well-tested
- **Cons:** Limited diversity; jitter magnitude may need tuning

### Option B: Expand Jitter Variants
- **Population:** Add 10–20 jitter variants (±10%, ±30%, ±50%)
- **Variants:** Multiple jitter levels per config
- **Evolution:** None — fixed per iteration
- **Pros:** Better coverage of parameter space around the validated config
- **Cons:** Higher compute; risk of overfitting to jitter patterns

### Option C: Include Random Configs
- **Population:** Replace jitter with 10 random configs + jitter
- **Variants:** `random_cfg` from search pipeline
- **Evolution:** None — fixed per iteration
- **Pros:** Broader exploration beyond validated config
- **Cons:** May be too stochastic; loses connection to the incumbent

### Option D: Include Momentum Snapshots
- **Population:** Add 2–3 snapshots of the agent's own config from prior epochs
- **Variants:** Config at epoch N-1, N-2, N-5
- **Evolution:** Yes — opponents reflect agent's own history
- **Pros:** Creates feedback loop; tests self-consistency
- **Cons:** Requires storing snapshots; may bias against own patterns

### Option E: Trap-Test Negative Candidates
- **Population:** Add 1–2 "deceptive" configs designed to trap the agent
- **Variants:** Configs that pass initial validation but fail in war
- **Evolution:** None — static
- **Pros:** Stress-test robustness; reveals hidden weaknesses
- **Cons:** Adversarial by design; may not reflect real opponents

### Option F: Evolving Opponents
- **Population:** Opponents mutate between iterations
- **Variants:** Jitter + small random mutations
- **Evolution:** Yes — opponents adapt to the agent
- **Pros:** Co-evolutionary pressure; more realistic arms race
- **Cons:** Non-stationary training; harder to analyze; requires careful seeding

---

## Recommendation

**Recommendation: Stick with the current setup for the arena, but expand the jitter variants.**

**Rationale:**

1. **The current 12-opponent field is sufficient** for the arena's purpose:
 - The rule config + jitter variants test robustness to parameter perturbations
 - The baselines provide floor/ceiling benchmarks
 - The personas provide regime-specific adversarial behavior

2. **Add 5–10 more jitter variants** at ±10% and ±30%:
 - Lower jitter (10%) tests sensitivity to small changes
 - Higher jitter (30%) tests robustness to larger perturbations
 - This is a low-risk modification that improves coverage

3. **Do not include momentum snapshots or trap-test candidates** in the arena:
 - Snapshots would require storing state; the arena is CPU-only and should stay lightweight
 - Trap tests are valuable for the **gate** but not for the **battle** — the gate already has dedicated trap holdouts

4. **Keep opponents fixed per iteration** — no evolution needed:
 - The arena trains the agent's value head, not the opponent field
 - Co-evolution adds complexity without clear benefit
 - The curriculum already provides enough progression

5. **Do not use `random_cfg` variants** in the arena:
 - These are too stochastic for a training opponent
 - The search pipeline already uses them; the arena needs more structured perturbations

**Implementation:**
- Modify `home_grown()` to add jitter levels at 0.10 and 0.30
- Keep the 0.25 default for compatibility
- Document the full population in `arena/opponents.py` with a comment block

---

## Background Research

### Key Files Examined

| File | Lines | Purpose |
|---|---:|---|
| `arena/opponents.py` | 172 | Opponent definitions, `home_grown()`, `default_field()` |
| `arena/train.py` | 501 | Arena iteration loop, opponent field creation |
| `arena/battle.py` | 114 | Battle mechanics, opponent voting |
| `arena/curriculum.py` | 306 | Curriculum, iterations, progression |
| `data/setup_search/ledger.jsonl` | 875 | Config search ledger |
| `data/setup_search/best.json` | 44 | Validated rule config |
| `docs/agents/research/arena-persona-playbooks.md` | 213 | Hedge-fund persona definitions |

### Key Findings

- The **875-config ledger** is the search result ledger, not the arena opponent set
- **Jitter is the proven operator** — `random_cfg` is a red herring for the arena
- **No momentum snapshots** are stored or used
- **No trap-test candidates** are used as opponents
- **Opponents are fixed per iteration** — no evolution mechanism exists
- **12 total opponents** is a reasonable number for the compute budget

---

## Appendix: Full Population Breakdown

| # | Type | Name | Description |
|---|---|---|---|
| 1 | Rule | `RuleBot(cfg)` | Validated config — incumbent |
| 2 | Baseline | `AlwaysTake` | Always votes TAKE |
| 3 | Baseline | `AlwaysSkip` | Always votes SKIP |
| 4 | Baseline | `RandomBot(0.5)` | 50% TAKE, seed=7 |
| 5 | Baseline | `RandomBot(0.75)` | 75% TAKE, seed=8 |
| 6–8 | Jitter | `JitterBot(±25%)` | ±25% param jitter, seeds 17–19 |
| 9 | Persona | `CitadelBot` | Quant/MM: contrarian within uptrend |
| 10 | Persona | `CitronBot` | Adversarial fade: contrarian on extensions |
| 11 | Persona | `AHLBot` | Systematic trend: pure momentum |

**Total: 12 opponents**

---

## Memo Path

`/home/mrc/opentrader/docs/agents/research/prep-64.md`
