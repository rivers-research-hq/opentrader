# Adoption Memo: Finetuning with sampling — SFT learns better than you think

**Date:** 2026-10-12  
**Ticket:** #321  
**Reference:** arXiv:2610.02140  
**Verdict:** Pilot  
**Provenance:** local worker `qwen36-35b-agentic` via smart-router dispatch; artifact `~/ai/smart-router/dispatch-artifacts/memo-321-v1.json`, card `/tmp/memo_321_card.md`, 1724 completion tokens. Memo body is the worker's text; this header was added by the API integrator.

---

## 1. The failure mode this addresses

The OpenTrader system relies on a strict separation of concerns: a rule-based floor, value-head experts, and an agentic layer managed by dispatch cards, a supervisor/verifier, and audit gates. The primary failure mode in agentic systems is not just "hallucination" in the generative sense, but **instructional drift and integrity degradation** during complex tool-use sequences.

This paper addresses the failure mode where standard Supervised Fine-Tuning (SFT) fails to robustly internalize complex, multi-step reasoning patterns or safety constraints because the model overfits to the exact token sequences in the training data rather than learning the underlying logical structure of the task. In the context of OpenTrader, this manifests as:
1.  **Dispatch Worker Lane:** The local LLM worker ignoring subtle constraints in "dispatch cards" when faced with novel market conditions, leading to invalid tool calls.
2.  **Supervisor/Verifier Lane:** The verifier failing to catch subtle logical errors in the worker's output because it was trained on "clean" examples that didn't reflect the noise of real-world execution.
3.  **Audit Gate Integrity:** The binding audit gates failing to enforce compliance because the underlying model's reasoning path is brittle.

The paper proposes that "Finetuning with Sampling" (generating multiple candidate outputs during training and selecting/optimizing for the best) yields better generalization and robustness than standard SFT. This directly targets the need for **agent integrity** under distribution shift, ensuring that the automated work products (trades, audits, verifications) remain reliable without constant human intervention.

## 2. What the paper claims — and only what the supplied text supports

Based strictly on the ticket summary and title:

*   **Claim:** Post-training methods, specifically Supervised Fine-Tuning (SFT), can be improved by introducing sampling during the finetuning process.
*   **Claim:** This method, termed "Finetuning with Sampling," allows the model to learn better than standard SFT.
*   **Claim:** The improvement is in the context of introducing new capabilities to frontier models.
*   **UNVERIFIED:** The specific magnitude of improvement, the exact algorithmic details of "sampling" (e.g., self-consistency, best-of-N, or something else), the specific benchmarks used, or the computational overhead. The ticket does not provide the full text, only the abstract/summary.
*   **UNVERIFIED:** Whether this applies specifically to tool-use, safety, or general reasoning. The title suggests general capability, but the authors (Karans, Chen, Du) have work in reasoning and safety, so it is plausible it applies to agent integrity.

## 3. Concrete adoption into OpenTrader's agent stack

This paper is **not** about FX signal generation. It is about **Agent Integrity**. The adoption path is into the **Training Data Pipeline** for the local LLM worker and the supervisor/verifier models.

### 3.1. Dispatch Worker Lane (Local LLM Worker)
*   **Current State:** The worker is likely fine-tuned on historical dispatch cards and successful tool-calling sequences.
*   **Adoption:** Re-train the worker model using "Finetuning with Sampling." Instead of feeding the model a single correct tool-call sequence, generate multiple candidate sequences (via sampling during data preparation or synthetic data generation) and use the sampling-based SFT objective to train the model to prefer robust, logically consistent paths.
*   **Goal:** Reduce instruction drift when encountering novel FX market states not seen in the frozen research dataset.

### 3.2. Supervisor/Verifier Lane
*   **Current State:** The verifier checks worker output against rules.
*   **Adoption:** Train the verifier model using the same sampling-based SFT. This should improve its ability to detect subtle logical inconsistencies or safety violations that standard SFT might miss because it overfits to "obvious" errors.
*   **Goal:** Increase the precision of the audit gate, reducing false positives (blocking valid trades) and false negatives (allowing invalid trades).

### 3.3. Binding Audit Gates
*   **Adoption:** The audit gates themselves are rule-based, but the *interpretation* of ambiguous rules may be handled by the LLM. Improving the LLM's reasoning robustness via this method ensures that the audit gate's "soft" checks are more reliable.

## 4. What is NOT claimed (guardrails)

*   **NOT a Trading Strategy:** This paper does not provide any alpha, signal, or edge for FX trading. It is a method for improving model training.
*   **NOT a Backtestable Hypothesis on FX Data:** The pre-registered hypothesis in the ticket ("adapted to a frozen OpenTrader FX research dataset... improve the held-out metric") is a **category error**. You cannot backtest "finetuning with sampling" on FX price data. You can only backtest the *agent's performance* after retraining.
*   **NOT a Guarantee of Safety:** While it may improve robustness, it does not guarantee immunity to adversarial attacks or novel failure modes.
*   **NOT a Replacement for Rule Floor:** The rule floor remains the hard constraint. This method improves the LLM's ability to operate within those constraints.

## 5. Implementation sketch and rough cost

### Phase 1: Verification (Low Cost)
1.  **Acquire Paper:** Obtain the full text of arxiv:2610.02140.
2.  **Reproduce Baseline:** Implement the "Finetuning with Sampling" method on a small, open-source reasoning benchmark (e.g., GSM8K or a simple tool-use benchmark like WebShop) to verify the claim that it outperforms standard SFT.
3.  **Cost:** Minimal. Use existing GPU resources for a small-scale experiment. Time: 1-2 days.

### Phase 2: Pilot (Medium Cost)
1.  **Data Preparation:** Create a synthetic dataset of "dispatch cards" and tool-calling sequences. Introduce noise and variations to simulate real-world conditions.
2.  **Training:** Retrain the local LLM worker and verifier using the sampling-based SFT method on this synthetic dataset.
3.  **Evaluation:** Run the OpenTrader system in **paper mode** (no live orders) on the FX arm. Compare the agent's performance (success rate of dispatch cards, accuracy of verifier) against the baseline model.
4.  **Cost:** Moderate. Requires GPU time for training and extended paper trading runs. Time: 1-2 weeks.

### Phase 3: Integration (High Cost)
1.  **Full Retraining:** Retrain all LLM components (worker, verifier) using the full OpenTrader dataset (frozen research data + synthetic data) with the new method.
2.  **Audit:** Conduct a thorough audit of the new models' behavior, focusing on edge cases and failure modes.
3.  **Deployment:** Gradually roll out the new models to the live FX arm, starting with low-risk instruments.
4.  **Cost:** High. Significant GPU time and engineering effort. Time: 1-2 months.

## 6. Verdict: adopt / pilot / watch / no

**Verdict: Pilot**

**Rationale:**
The paper addresses a critical need in OpenTrader: improving the robustness and generalization of the agentic layer. The pre-registered hypothesis in the ticket is flawed (category error), but the underlying idea is sound. However, the full details of the method are UNVERIFIED. We must first verify the paper's claims on a small scale before investing in a full retraining of the OpenTrader agent stack.

**Next Steps:**
1.  Read the full paper.
2.  Run Phase 1 (Verification) to confirm the method works as claimed.
3.  If Phase 1 is successful, proceed to Phase 2 (Pilot) on the FX paper lane.
4.  If Phase 1 fails, mark as **Watch** and revisit if new evidence emerges.
