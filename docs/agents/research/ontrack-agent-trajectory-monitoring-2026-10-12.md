# Adoption Memo: OnTrack — real-time monitoring and intervention in LLM agent trajectories

**Date:** 2026-10-12  
**Ticket:** #378  
**Reference:** arXiv:2610.12375  
**Verdict:** Pilot  
**Provenance:** local worker `qwen36-35b-agentic` via smart-router dispatch; artifact `~/ai/smart-router/dispatch-artifacts/memo-378-v1.json`, card `/tmp/memo_378_card.md`, 1177 completion tokens. Memo body is the worker's text; this header was added by the API integrator.

---

## 1. The failure mode this addresses

OpenTrader’s agentic architecture relies on a local LLM worker executing "dispatch cards" under the supervision of a verifier lane. The primary failure mode addressed by this paper is **latent trajectory divergence and silent policy drift** during complex, multi-step agent executions.

In the current FX research workflow, an agent may generate a sequence of tool calls (e.g., data fetch -> analysis -> draft order) that appears syntactically valid but deviates from the intended logical structure or safety constraints. Traditional logging captures the final state or individual tokens, but fails to detect when the *semantic path* taken by the agent has drifted from the optimal or safe trajectory in real-time. This paper targets the inability to monitor and intervene in the *structure* of the agent's reasoning process as it unfolds, specifically preventing the agent from entering invalid or unsafe states before they result in erroneous outputs or audit failures.

## 2. What the paper claims — and only what the supplied text supports

Based strictly on the provided ticket text and title:

*   **Claim:** The method "OnTrack" enables real-time monitoring of LLM agent trajectories.
*   **Claim:** It uses "Streaming Structure-Aware Optimal Transport" to detect deviations.
*   **Claim:** It supports intervention in these trajectories.
*   **Claim:** It is applicable to agents deployed in applications such as trip planners, stock trading, and IT incident triage.
*   **Constraint:** The paper does *not* claim to improve financial alpha, PnL, or signal accuracy. It is an agent-safety and structural integrity paper.

## 3. Concrete adoption into OpenTrader's agent stack

This method is **not** a trading signal generator. It is a component for the **Agent-Integrity Stack**. Specifically, it maps to:

1.  **Supervisor/Verifier Lane:** The "Streaming Structure-Aware Optimal Transport" metric can serve as a real-time loss function or anomaly score for the supervisor. Instead of waiting for the final output to verify correctness, the supervisor can monitor the *trajectory structure* of the dispatch worker.
2.  **Dispatch Worker Lane:** The "Intervention" capability implies the ability to halt or redirect the worker if the optimal transport distance between the current trajectory and the "safe/expected" manifold exceeds a threshold.
3.  **Binding Audit Gates:** The streaming nature allows for pre-computation of integrity scores before the final result is committed to the append-only ledger.

**Integration Point:** The metric should be computed on the fly during the generation of dispatch cards. If the structural deviation score spikes, the supervisor can trigger a "re-think" or manual review gate before the action is executed.

## 4. What is NOT claimed (guardrails)

*   **NOT a Trading Strategy:** This paper does not provide alpha, edge, or predictive power for FX or crypto markets.
*   **NOT a Backtestable Signal:** The "held-out metric" mentioned in the templated hypothesis is a structural integrity or safety metric, not a financial performance metric.
*   **NOT a Replacement for Rule Floor:** It does not replace the hard-coded rule floor; it monitors the value-head experts' adherence to structural norms.
*   **NO Live Trading:** As per the triage source, this is research-only. No result promotes a strategy.

## 5. Implementation sketch and rough cost

**Phase 1: Falsifiable Proof-of-Concept (POC)**
*   **Goal:** Verify if the "Streaming Structure-Aware Optimal Transport" metric can detect known structural failures in synthetic agent trajectories.
*   **Data:** Use a frozen subset of OpenTrader’s FX research logs (dispatch cards and agent responses).
*   **Method:**
    1.  Define a "correct" trajectory structure for a standard dispatch card (e.g., Input -> Analysis -> Output).
    2.  Inject structural errors (e.g., missing analysis step, circular tool calls).
    3.  Implement the OT distance calculation from the paper.
    4.  Measure if the metric significantly separates "correct" from "incorrect" trajectories.
*   **Cost:** Low. Requires only CPU/GPU for OT computation on small batches. No API token cost if using local logs.

**Phase 2: Supervisor Integration (Pilot)**
*   **Goal:** Integrate the metric into the supervisor verifier lane as a real-time anomaly score.
*   **Method:** Run the metric in parallel with the LLM worker. Log the OT distance for each step.
*   **Cost:** Moderate. Requires engineering effort to integrate the streaming OT library into the existing supervisor loop.

## 6. Verdict: adopt / pilot / watch / no

**Verdict: Pilot**

**Rationale:**
The paper addresses a critical gap in OpenTrader’s agent integrity: real-time structural monitoring. The templated hypothesis in the ticket is a **category error** (as noted in the scope correction) and should be discarded. The method is not suitable for FX backtesting. However, its application to the **Supervisor/Verifier lane** is highly relevant for ensuring the trustworthiness of automated work products.

We should **pilot** the implementation of the OT metric as a structural anomaly detector in the supervisor lane, using frozen logs for validation. Do not attempt to adapt it for financial signal improvement. If the metric proves effective at detecting structural drift in synthetic tests, proceed to a limited pilot in the live dispatch worker lane with strict intervention guards.
