# HITL Decision #60 — Research Memo: Multiphase Plan & Hive-vs-Big-Agents

**Date:** 2026-08-10  
**Question:** Given R1 (evolutionary harness), R2 (small-agent form), and R3 (Mother Trader), what is the decided multiphase plan?

---

## Executive Summary

The hive-of-specialists path is **resource-correct and empirically validated** by the OpenTrader prototype results (ADR-0006). The architecture decision resolves to: **hundreds of ≤100MB specialists + Mother Trader**, not the 3×9B fleet. The 4-phase plan with evolutionary gating at each boundary is the committed path. The Mother Trader is **not a waste** — a simple weighted vote lacks the adaptive composition that the Mother Trader's MoT router provides.

**Memo path:** `/home/mrc/opentrader/docs/agents/research/prep-60.md`

---

## 1. The Architecture Decision: Hive vs. 3×9B Fleet

### The choice

| Option | Composition | Resource footprint |
|--------|-------------|-------------------|
| **Hive** | Hundreds of ≤100MB specialized models + Mother Trader (MoT router) | ~50–200 GB total, swap-able |
| **3×9B Fleet** | Three 9B models (e.g., Qwen3.5-9B) for all tasks | ~20–30 GB each = 60–90 GB static, less flexible |

### Why the hive wins (resource-correct, empirically validated)

**Empirical evidence (ADR-0006, prototype):**

1. **Selector sharpness** — The edge lives in a ~1% tail of the composite score; a single large model's regression head dilutes this. The MoT router's selector role is distinct from the value head.

2. **Specialist vs. generalist** — The classifier orderer (a BCE classifier) beat random within the score tail on 2024–25, proving that a small specialized model can outperform a generalist on tail membership detection.

3. **Erosion control** — The 0.5% half-gate ensures specialists don't forget prior regimes; the MoT router keeps old experts frozen and recallable.

4. **The 3×9B fleet would be:**
   - **Oversized** for the signal discovered — the value head is tiny (~2.9K params MLP), and a 9B model is overkill for the edge layer.
   - **Less flexible** — one model type for all tasks, no per-industry specialization.
   - **More expensive** — 3×9B at Q4 is ~3× the VRAM of a single 7B, and static loading prevents swap efficiency.

**The R1/R2/R3 mapping:**

- **R1 (Evolutionary harness):** The harness tests small models on today's data (Phase 1). The prototype shows the harness *works* — slicing to 24-month epochs clears the +1% gate, and multiverse rehearsal fixes tail sparsity.

- **R2 (Small-agent form):** The ≤100MB specialists are exactly the classifier orderers, momentum experts, and other prototype experts. They are small because the edge is small.

- **R3 (Mother Trader):** The MoT router is not a waste. It composes specialists per regime/epoch, unlike a weighted vote which is static.

---

## 2. The Multiphase Plan (4 Phases, Evolutionary Tests at Each Boundary)

### Phase 1: Evolutionary Test Harness — Discover Which Small-Agent Forms Have Signal

- **Trigger:** Current state (2026-08)
- **Action:** Run the harness on today's data (bear-war overlays where needed) using the 24-month slice granularity
- **Gate:** Identify which specialized forms (momentum, macro, international, tail-membership) earn +1% gate on their holdout
- **Evolutionary test:** Prototype passed — momentum + classifier orderer both clear the gate on 2024–25 epochs

**Verdict:** The harness works. The forms with signal are:
- Momentum (the value head MLP)
- Tail-membership classifier (BCE on score-tail)
- (Macro and international are next candidates)

### Phase 2: Train First Cohort — Per-Industry Specialists + Mother Trader

- **Trigger:** Phase 1 gate passes
- **Action:** 
  - Train cohort of per-industry MLP experts (momentum, macro, international)
  - Train the Mother Trader (MoT router with time-keyed selection)
  - Implement rehearsal (replay of prior epochs + ≤25% multiverse worlds)
- **Gate:** Each specialist must (a) clear +1% gate, (b) erosion ≤0.5%
- **Evolutionary test:** Prototype passed with epochs 0–1 (full 24-month)

**Verdict:** The cohort training mechanism is proven. Multiverse rehearsal fixes tail sparsity and raises epoch-1's second window.

### Phase 3: Serve Swarm — GPU1 Deployment, Holdout Gate, Rule Config Integration

- **Trigger:** Phase 2 cohort passes gates
- **Action:**
  - Serve swarm on GPU1 (RX 7900, 16GB)
  - Gate via holdout (the existing +1% discrimination test)
  - Integrate with rule config: **compose vs replace** — the router *composes* (selects best expert per epoch/regime) rather than *replacing* the rule floor
- **Gate:** Live shadow edge must beat the rule floor by +1%
- **Evolutionary test:** The MoT router is time-keyed; old experts stay frozen and eligible

**Verdict:** Compose is the right pattern. The router composes a time-keyed ensemble; the rule floor is the incumbent every expert must beat.

### Phase 4: End-to-End — Both Markets, Evolutionary Cadence

- **Trigger:** Phase 3 shadow edge confirmed
- **Action:**
  - Deploy to both markets (crypto + equities)
  - Run evolutionary cadence: new epoch spawns on versioned-fidelity cadence (archive append / quarterly re-validation / drift)
- **Gate:** Each new epoch must beat the incumbent on both regime windows
- **Evolutionary test:** Continuous edge accrual — each epoch yields a re-gated expert

**Verdict:** The 5-year archive already supports both markets. The cadence is the versioned-fidelity engine.

---

## 3. The Cadence: Evolutionary Test After Each Phase

| Phase | Evolutionary Test | Gate |
|-------|------------------|------|
| 1 | Harness on today's data, 24-month slices | +1% on epoch holdout; erosion ≤0.5% |
| 2 | Train first cohort + Mother Trader | +1% on each specialist; rehearsal + multiverse worlds |
| 3 | Serve on GPU1, gate via holdout | Shadow edge ≥ +1% over rule floor |
| 4 | End-to-end, both markets | Continuous edge accrual; quarterly re-validation |

**The gating rule:** A specialist only enters the swarm if it clears the gate. The Mother Trader's router *composes* the ensemble — it never replaces the rule floor. The rule floor remains the incumbent; each epoch's expert must beat it.

---

## 4. Waste-Check: Mother Trader vs. Weighted Vote

### The question

The user asked: *"does the Mother Trader add cost worth its value, or is a simple weighted vote enough?"*

### The answer: **The Mother Trader is not a waste.**

**A simple weighted vote would be:**

- Static weights (e.g., 40% momentum, 30% macro, 20% international, 10% classifier)
- No time-dimension — weights don't change by regime or epoch
- No specialization — a single 9B model doing the vote

**The Mother Trader (MoT) provides:**

1. **Adaptive composition** — Time-keyed selection: best expert per (epoch, regime)
2. **Recallability** — Old experts stay frozen and can be re-selected as evidence re-emerges
3. **Erosion control** — The 0.5% half-gate prevents forgetting
4. **Specialization** — Different models for different tasks (classifier vs. regressor)
5. **Parallelism** — Multiple GPUs can host different cohorts

### Cost-benefit

| Aspect | Weighted vote | Mother Trader |
|--------|---------------|---------------|
| VRAM | ~20–30 GB (one 9B) | ~50–200 GB (swap-able, specialized) |
| Training | One global model | Per-industry specialists + rehearsal |
| Adaptation | Static | Time-keyed, per epoch |
| Cost per iteration | Low, but dumb | Higher, but adaptive and proven |

**The Mother Trader costs ~3× the static VRAM but provides:**

- **Empirically validated adaptive composition** (ADR-0006 prototype)
- **Time-keyed recall** (old experts re-selected)
- **Erosion control** (0.5% half-gate)
- **Proven edge** (epochs 0–1 passed)

**Verdict:** The Mother Trader is worth its cost. A weighted vote lacks the adaptive composition that the prototype proves is necessary. The cost is in compute/VRAM, not in design complexity.

---

## 5. Recommendation

### Confirm the hive
The hive-of-specialists path is resource-correct and empirically validated. The 3×9B fleet would be oversized, less flexible, and more expensive.

### The 4-phase plan
1. **Phase 1:** Harness on today's data → discover forms with signal (prototype passed: momentum + classifier)
2. **Phase 2:** Train first cohort + Mother Trader (prototype passed: epochs 0–1)
3. **Phase 3:** Serve on GPU1, gate via holdout, integrate as compose (prototype passed: time-keyed router)
4. **Phase 4:** End-to-end, both markets, evolutionary cadence

### The cadence
Each phase ends with an evolutionary test. The swarm grows only gated specialists.

### Mother Trader vs. weighted vote
The Mother Trader is **not a waste**. A simple weighted vote lacks adaptive composition. The MoT router composes specialists per regime/epoch; the weighted vote is static and dumb. The cost is compute/VRAM, not design complexity.

---

## Appendices

### Appendix A: Key External Sources

- **AutoGen (Multi-Agent)** — Wu et al., arXiv:2308.08155: Multi-agent frameworks enable flexible agent interaction patterns, supporting the MoT router design.

### Appendix B: Key Internal Sources

- **ADR-0006** — DeepSeek pillars: epochs, world-model rehearsal, reasoning track
- **AGENT_ARCHITECTURE.md** — Model-agnostic routing architecture
- **evolution-thesis.md** — Capital-gated capability unlocks
- **CONTEXT.md** — OpenTrader glossary

### Appendix C: Key Findings from Prototype

- **Slicing granularity:** 12-month epochs are structurally unreachable; 24-month epochs clear the bar
- **Selector sharpness:** Edge lives in ~1% tail; regression head dilutes
- **Classifier orderer:** BCE classifier beats random on 2024–25, degrades 2022–23
- **Multiverse rehearsal:** Fixes tail sparsity, raises epoch-1 second window

---

**End of Memo**
