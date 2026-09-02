# ADR-0006: DeepSeek pillars — epochs, world-model rehearsal, reasoning track

- **Status:** accepted
- **Date:** 2026-08-07 (revised after grilling session; supersedes the earlier
  "frozen per-regime LoRA experts" draft)
- **Context:** the user wants OpenTrader to adopt DeepSeek's development
  strategy, which rests on three pillars: (1) **continual learning** — models
  keep training on new data instead of being rebuilt from scratch, using
  architecture to avoid forgetting; (2) **reasoning via RL** — R1-style models
  earn chain-of-thought through reinforcement learning with verifiable rewards;
  (3) **world models** — an internal model of the environment's dynamics lets
  the agent train in simulation, decoupling training compute from real
  experience.

  Facts established in the grilling session (2026-08-07):
  - The **edge is the tiny value-head MLP** (~2.9K params: momentum, macro,
    international); the glossary is explicit that "the LLM is never the edge."
    Arena GRPO (`arena/grpo.py`) optimizes the MLP; the Qwen LLM is QLoRA-
    fine-tuned only as a proposer/explainer layer.
  - Today each expert is one globally-trained MLP; per-regime selection lives
    only in the MoT router. There is no time dimension in training.
  - CoT exists only at inference-parsing level (`_extract_thinking()`,
    `_extract_text()`); the RL loop has no reasoning reward and no traces are
    distilled into experts.
  - The Multiverse is already a world model, but synthetic rows are used only
    to break strategies; ADR-0001 quarantines them from the gate/war/evidence.
  - deepseek-r1-7b (R1-Distill-Qwen-7B, SFT-only) is on disk and was the
    planned trace teacher; **superseded (2026-08-11) by
    DeepSeek-V4-Pro-Qwen3.5-9B-MTP Q8_0** (`models/deepseek-v4-pro-qwen3.5-9b/`),
    a native-thinking 9B verified serving on GPU1 with real CoT output
    (see docs/research/reasoning-track-design.md). The existing
    reward-conditioned SFT trainer
    (Qwen2.5-7B) is the substrate for the reasoning track.

- **Decision:** adopt the three pillars, kept distinct, sequenced
  **continual → world-model → reasoning**, with the primary success bar of
  **continuous edge accrual** (each epoch yields a re-gated expert that beats
  the incumbent, with forgetting explicitly measured).

  1. **Continual learning = epoch-based experts.** A new expert spawns per
     **epoch**, where an epoch is the versioned-fidelity cadence (archive
     append / quarterly re-validation / sustained shadow drift). The existing
     global momentum value head is retrained on slice 1 as epoch-1. Training
     uses **replay (rehearsal)** of prior-epoch data so the new fit retains old
     behavior. The MoT router becomes **time-keyed**: best expert per
     (epoch, regime); prior experts stay frozen and eligible, with
     **recency-weighted evidence decay**; all checkpoints are kept (each MLP is
     3.6–11KB, so retention is nearly free).
  2. **World-model training = multiverse as rehearsal (phase 2).** Multiverse
     worlds (≤25% of the replay mix) become a rehearsal source in epoch
     training, with adversarial rotation against the tail library. This does
     **not** reverse ADR-0001: synthetic rows still never enter the gate, the
     war, or the evidence — they only augment training, as ADR-0001 already
     permits.
  3. **Reasoning track = GRPO + reasoning reward, off the edge (phase 3).** The
     LLM (Qwen2.5-7B, reward-conditioned SFT upgraded to true GRPO) earns
     chain-of-thought with a reasoning reward, using local
     DeepSeek-V4-Pro-Qwen3.5-9B-MTP Q8_0 (superseding deepseek-r1-7b, 2026-08-11) to
     mint high-reward thinking traces as cold-start data. Its verifiable reward
     is **war-outcome edge** (the same discriminator as the MLP gate). It is
     gated on **proposer quality** (beats the ADIR/debate baseline on
     war-signal hit-rate) plus trace-outcome alignment. Its deliverable is a
     competing proposer whose traces derive new value-head features. It never
     becomes the edge.

  **The prototype** (proves the mechanism before any other pillar):
  - Reslice the 5y archive into **5× 12-month walk-forward slices**, with
    bear-war overlays supplying down-regime data where a slice lacks it, so the
    gate stays discriminating.
  - **Momentum expert only** for the first run.
  - Bar: the epoch-N expert must (a) clear the existing +1% gate on its own
    epoch holdout, (b) retain prior-epoch edge within **erosion ≤ 0.5%**
    (half-gate) on prior-epoch holdouts, (c) beat the single-global-expert
    baseline on both.
  - On failure: no promotion, log + retry next epoch. Trigger is fully
    automated; promotions are the only human-visible event.
  - The prototype **is** the upgraded versioned-fidelity engine (ADR-0003), not
    a throwaway diagnostic.

  **Prototype findings (2026-08-07, sandbox):**
  - **Slicing granularity was wrong, not the recipe.** At 12-month epochs the
    +1%-both-windows bar is structurally unreachable even for a cheating-oracle
    MLP in the bull-heavy later years (2024–26). 24-month epochs clear it. The
    edge shows up at ≥2y granularity, matching the 5y-scale where the rule was
    originally validated.
  - **Selector sharpness is the real constraint, not regression.** The value
    head (MSE regressor of E[fwd]) dilutes the score-tail edge: the edge lives
    in a sharp ~1% tail of the composite score (the rule floor keeps 14/1599
    and 34/3200 by score ≥ 0.28). Top-1%-by-score clears the +1% bar on the
    failing 2024–25 windows; the smooth regressor does not.
  - **A tail-membership classifier is the first trained expert to beat random
    within the score tail** on both windows of the 2024–25 epoch, across 5
    seeds at 25% keep (+9.2% vs +3.9% random on w1; +1.9% vs +1.5% on w2).
    But it does NOT generalize to the 2022–23 epoch, where it loses the edge
    the plain score tail earned. Research-grade orderer; not yet an all-epoch
    expert.
  - **Verdict: no formulation yet wins all epochs with a trained expert adding
    edge.** Score-tail-only passes every gate but proves the value head
    irrelevant (the gate measures the rule floor). The classifier earns real
    edge on 2024–25 but degrades 2022–23. Prototype not passed; the classifier
    is registered as a candidate expert to battle/GRPO through the normal
    arena gate.

  **Phase 2 result (multiverse rehearsal, 2026-08-07, sandbox):**
  - Synthetic worlds (5–15 per epoch, ~30–90k rows) became an ADDITIONAL
    rehearsal source in epoch training and the classifier's training set
    (real + synthetic). ADR-0001 quarantine held: synthetic rows entered
    training only, never the gate/war/evidence.
  - **Multiverse rehearsal fixed the classifier's epoch-0 degradation** (the
    sparse real tail was too small to learn; inflation made the ordering
    layer learnable) and raised epoch-1's second window.
  - Final state: **epochs 0 and 1 (full 24-month) PASS robustly with real
    trained-expert edge** (+5.7%/+3.4% and +6.9%/+4.4% margins). **Epoch 2
    (partial-2026, truncated year) is evidence-starved** — its second window
    has 1 kept trade and the margin flips with RNG (+0.3% to +3.2%); logged
    inconclusive and deferred to the normal versioned-fidelity cadence, which
    re-gates it as a full 24-month window once 2026 completes.
  - The continual-learning mechanism is now demonstrated: epochs spawn,
    rehearse (real + synthetic + output-match), gate with a trained selector,
    and erosion is ≤0.5% across the passes. Ticket #85 (rehearsal) and #86
    (erosion) are substantively done; the classifier orderer remains a
    candidate pending epoch-2's full-year gate.

- **Consequences:**
  - The rule floor is unaffected: it remains the incumbent that every epoch's
    expert must beat. ADR-0001 fidelity and ADR-0002 deployability criteria are
    unchanged.
  - Expert count grows with epochs; the time-keyed router (`mot/`) selects among
    them, old experts recallable as evidence re-emerges.
  - Training compute increases (rehearsal replay + later reasoning rollouts).
    All training remains sandbox-first per AGENTS.md; the live tree and GPU stay
    untouched until validated.
  - Risk: rehearsal (and later reasoning/world-model training) could overfit to
    synthetic or recycled dynamics. Mitigation: the gate and erosion bars run on
    held-out real data only; the 0.5% erosion bar is the anti-forgetting
    counterweight to the +1% gate.
