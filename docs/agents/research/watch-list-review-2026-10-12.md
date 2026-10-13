# Watch-list review — tickets #321, #365, #378, #381

**Date:** 2026-10-12 · **Scope:** four papers parked as "watch" on the research board.

**Provenance.** Draft verdicts were emitted by the local worker
(`~/ai/smart-router/dispatch-artifacts/memo-watch-list-review-v1.json`, 1041 tok).
**The draft's method descriptions were unreliable for all four papers.** Each verdict
below was re-derived against the paper's abstract, fetched this session from
`arxiv.org/abs/<id>`. The draft's verdict is kept alongside each corrected one so the
error is auditable, not buried. Nothing here is a trading claim and nothing promotes a
strategy.

---

## #321 — "Finetuning with Sampling: SFT Learns Better Than You Think" (arXiv:2610.02140)

**Draft verdict: Drop** — "rejection-sampling multiplies inference cost; prohibitive."
**Corrected verdict: keep-watching (drop-for-now, for the right reason).**

What the paper actually does: post-training with SFT vs RL; it targets the conventional
claim that RL generalises better while SFT forgets. It introduces an **MCMC sampling
algorithm that tailors the training data distribution** so off-policy expert data suits
the learner — it is a *training-time data-selection* method, not inference-time
rejection sampling. The draft's cost argument (multiplicative sampling at inference) is
therefore aimed at a method the paper does not describe.

Why we still park it: the technique requires a **fine-tuning run**, which this project
does not do (no training pipeline; the worker is a frozen served model). Cost of the
paper's actual procedure is training compute, not per-request latency. Revisit only if
a fine-tune lane is ever opened. The draft reached a defensible verdict from a false
premise — the failure mode this board exists to catch.

## #365 — "Caught in the Act: Probes Effectively Detect Sabotage and Catch Unverbalized Deception" (arXiv:2610.12445)

**Draft verdict: keep-watching** — "needs labeled data from compromised models we lack."
**Corrected verdict: keep-watching, with one concrete cheap check named.**

What the paper actually does: white-box deception detection via **probes**, scaled to
frontier monitoring by collecting the largest deception dataset to date and a probe
architecture that aggregates across many layers and tokens. Reported 98.8% AUC on
SHADE-Arena, above a text-monitoring baseline; efficacy *improves as the model scales*;
it also examines "introspective deception" where ground truth needs elicitation.

Corrected reading for us — two of the draft's implications invert:
1. The paper *built* the dataset; "we lack labeled data" is a sourcing question, not a
   proven blocker. Cheapest check: is the dataset released? (`[unknowable]` from the
   abstract alone — verify before spending.)
2. "Improves as the model scales up" is a **negative** for us: our worker is a 35B MoE
   served on one GRE. The reported advantage may not transfer down.
3. We *do* have white-box access in principle (local `llama-server`), which is the one
   genuine advantage the draft missed — but exposing per-layer activations from
   llama.cpp is real plumbing, not a cheap rung.

Do not adopt yet; the actionable next step is one sourcing question, not a build.

## #378 — "OnTrack: Real-Time Monitoring and Intervention in LLM Agent Trajectories via Streaming Structure-Aware Optimal Transport" (arXiv:2610.12375)

**Draft verdict: Drop** — "measures output consistency over time; needs new data feeds."
**Corrected verdict: adopt the *idea*; keep-watching on the method.**

What the paper actually does: **streaming structure-aware optimal transport** comparing
an agent's steps and dependencies against *recorded successful runs*, to alert or block
in ~1 ms/step — explicitly positioned against (a) a monitor agent per step (cost) and
(b) post-hoc log evaluation (verdict arrives after tokens are burned). It studies three
access regimes: full reference access (historical runs + tool schemas), tool schemas
only, and no prior knowledge.

Corrected reading: the draft's "needs new data feeds" is **wrong** — the full-access
regime needs *recorded successful runs*, and this lane has a year of them in
`~/ai/smart-router/dispatch-artifacts/` plus the ticket ledger. The idea maps onto our
dispatch lane directly: compare a worker's tool/step structure against past successful
cards instead of reading its prose. Blocker: implementing OT-based comparison is
non-trivial; a cheap approximation (step-count and tool-sequence diff) is *not* the
paper's method and must be labelled as an approximation if built.

## #381 — "Accurate but Not Humble: Evaluating Epistemic Humility in LLM Agents under Knowledge Conflict" (arXiv:2610.12360)

**Draft verdict: Adopt** — "flag artifacts with high confidence + high code-block density."
**Corrected verdict: adopt — but the draft's detection rule is invented.**

What the paper actually does: evaluates **epistemic humility (EH)** — an agent's
willingness to recognise, act on and communicate uncertainty — under *knowledge
conflict* (parametric knowledge vs retrieved evidence, or two sources disagreeing).
It operationalises EH as three trajectory-level dimensions, **Identify, Solve, Escalate
(ISE)**, in controlled and naturally-occurring conflict settings, paired with matched
no-conflict controls. There is no "confidence score × code-block density" rule in it.

The adoptable artifact is the **ISE rubric applied to our dispatch artifacts**, and the
cheapest rung is a review checklist:

- **Identify** — does the artifact flag where a source contradicts its prior?
- **Solve** — does it resolve the conflict from evidence, or assert?
- **Escalate** — does it hand off uncertainty instead of papering over it?

This generalises the same night's lesson (see
`keyword-harness-fail-open-2026-10-12.md` §4–5): the worker's own watch-list draft
scored zero on all three dimensions — it asserted four papers' methods without evidence,
resolved nothing, escalated nothing — while passing every text check we have. ISE would
have caught it; the invented confidence heuristic would not have.

---

## Summary

| Ticket | Draft verdict | Corrected verdict | Cheapest next step | Blocker |
|---|---|---|---|---|
| #321 | Drop | keep-watching (same outcome, false premise) | none until a fine-tune lane exists | training compute |
| #365 | keep-watching | keep-watching | one sourcing question: is the deception dataset released? | small-model transfer unknown |
| #378 | Drop | **adopt the idea** | structure-diff vs recorded successful runs | OT implementation; approximation must be labelled |
| #381 | Adopt (invented rule) | **adopt the ISE rubric** | cite-or-escalate checklist in the card contract | reviewer must actually fetch sources |

**The draft's accuracy on method descriptions: 0/4.** It produced confident, well-formed,
wrong prose — and passed every automated check in the lane. That is the finding, not the
verdicts.
