# Reasoning track (ADR-0006 phase 3): feasibility + minimal recipe against primary sources

**Status:** Research decision — ready for the reasoning-track grilling to consume.
**Date:** 2026-08-11
**Builds on:** [Chinese-lab RL foundations](chinese-lab-rl-foundations.md) (GRPO Eqs. 3–4, hyper-parameters, R1 pipeline — already verified against the papers; not re-verified here), [Arena reward + war-relabeling protocol](arena-reward-protocol.md) (δ_t advantage, war-gates-before-relabel), ADR-0006 phase 3 (lines 50–58, 118–130).

## Verdict

**Feasible as a phased pipeline, but only on the RX 7900 GRE (16GB, ROCm) — the RTX 3070 (8GB, CUDA) is minting-only, not a GRPO card.** Minimal recipe: **(1)** mint cold-start traces with the local **DeepSeek-V4-Pro-Qwen3.5-9B-MTP** Q8_0 GGUF via llama.cpp, rejection-sampled on realized war P&L; **(2)** true GRPO (Qwen2.5-7B QLoRA) on the 16GB card, ORM-style outcome reward (per-regime group z-score of pnl_pct) + reasoning-format reward — not PRM; **(3)** the proposer gate, whose metric **must first be defined** (it exists only as a phrase in ADR-0006:56).

Three surprises that change the plan:

1. **The local "deepseek-r1-7b" is DeepSeek-R1-Distill-Qwen-7B** (Qwen2ForCausalLM, 7.6B; `config.json`) — an SFT-only model with **no RL stage** (R1 §2.4: "we apply only SFT and do not include an RL stage"). It is a trace *teacher*, not a copy of the R1 RL pipeline. **Superseded as teacher by the user's model**: `models/deepseek-v4-pro-qwen3.5-9b/DeepSeek-V4-Pro-Qwen3.5-9B-MTP-Q8_0.gguf` — 9.8GB Q8_0, qwen35 arch (33 layers), 262K ctx, native thinking template (`enable_thinking`/`reasoning_content`, R1-style think→answer). **Verified live (2026-08-11)**: serves on GPU1 via the existing llama.cpp HIP build alongside qwythos (:5802) at 8.1KB ctx (15.3GB/16GB combined); a smoke prompt produced 6.9KB reasoning + a final "TAKE" answer. Note: reasoning is verbose — minting needs `max_tokens >= 2000` or the answer never surfaces (at 300/800 tokens it hit `finish_reason: length` with an empty `content`).
2. **`/home/mrc/rocm_venv` is actually CUDA** (torch 2.10.0+cu128); the real ROCm stack is `/home/mrc/venv` (torch 2.13.0+rocm7.2) — which has **no transformers/trl/peft/unsloth**.
3. **trl 0.24.0's GRPOTrainer import is broken** in the CUDA venv (`trl/mergekit_utils.py:22`: `No module named 'mergekit'`; mergekit 0.1.4 pip-installable). unsloth 2026.7.3 loads with a torch-version warning (wants ≥2.11, found 2.10; cpp extensions skipped).

---

## Findings

### 1. Cold-start trace minting — the R1 pipeline, reproduced at 1/1000 scale

- **The R1 mechanism (arXiv 2501.12948):** four stages — (§2.3.1) cold-start SFT on **thousands** of long-CoT examples (few-shot prompting, prompting for reflection/verification, R1-Zero outputs post-processed by humans); (§2.3.2) reasoning RL with GRPO + rule rewards; (§2.3.3) **rejection sampling from the converged RL checkpoint** — ~600k reasoning trajectories keeping only correct ones, filtered for language-mixing/long-paragraph/code-block output, + ~200k non-reasoning, then **2 epochs of SFT of V3-Base** on the ~800k set; (§2.3.4) a second RL stage. That is the "R1 → R1-sft" loop: RL checkpoint → reject-sample → SFT → RL. R1-Zero (§2.2) proves RL alone works (AIME 15.6→71.0%) but the cold start buys readability and a better RL start.
- **Distillation is the small-model lesson (R1 §2.4, §4.1):** the 7B distill is plain SFT on the 800k traces, and it beat 10k+ steps of from-scratch RL on a 32B base. For a 7B on one consumer GPU: **minted teacher traces + SFT/GRPO is the direction; from-scratch RL is not.**
- **llama.cpp serves the R1 format natively** (think/answer is just the chat template — R1 Table 1; the running server already uses `--jinja`; GBNF grammar on the completion endpoint can enforce `<think>/<answer>`). **Q8_0 is the right quant and the ceiling:** 8.1GB vs ~15.2GB bf16 (which can't co-exist with a KV cache on 16GB); the hub/ full-precision download is **incomplete** (two `.incomplete` shards). Mint at **temperature 0.6, top-p 0.95** — R1's own evaluation sampling (§3).

### 2. GRPO for an LLM token policy — same objective, token ratios, G rollouts per prompt

- **Same math as `arena/grpo.py`, different policy:** DeepSeekMath (arXiv 2402.03300) Eq. 3 with per-**token** ratios `π_θ(o_t|q,o_<t)/π_θ_old(o_t|q,o_<t)` (§4.1.1), group advantage `A_i = (r_i−mean(r_1..G))/std(r_1..G)` (R1 Eq. 3) broadcast to every token of completion i, KL in the loss (Eq. 4), μ=1 (A.1.6 Eq. 21). The arena's "group" (round field) becomes **G sampled rollouts per prompt**. GRPO needs no critic — the group baseline replaces it (2402.03300 §4.1.1).
- **Literature hyper-parameters:** DeepSeekMath §4.1.4: **G=64, β=0.04, policy LR 1e-6, max len 1024, batch 1024, μ=1** (quoted in chinese-lab-rl-foundations.md). Qwen2.5 (arXiv 2412.15115 §4.3): **G=8**, batch 2048 — the right start for one 7B card.
- **TRL GRPOTrainer (official docs):** reward funcs are arbitrary Python over `(prompts, completions)` — a war-outcome reward is directly expressible; the R1 format reward is a documented regex example; loss variants include DAPO and Dr. GRPO; β defaults to 0 in current TRL. **Transformers continuous batching is the documented single-GPU generation path** ("well-suited for single-GPU training or memory-constrained environments"); vLLM (pip-indexable in both venvs) is optional.
- **3070 8GB: not viable for 7B GRPO** (QLoRA weights + optimizer + G≥2 rollouts of ~1k tokens + backward pass exceeds 8GB with no margin — estimate; 16GB is the realistic floor, and there expect days/run, not hours).

### 3. Verifiable reward — ORM-with-group-advantage is the honest first step; PRM is not

- **R1's verifier rationale (2501.12948 §2.2.2):** "the neural reward model may suffer from reward hacking in the large-scale reinforcement learning process." Accuracy (rule-checked) + format rewards only. The war's pnl_pct is computed, not learned — it satisfies verifiability.
- **ORM vs PRM (Let's Verify Step by Step, arXiv 2305.20050):** process supervision beats outcome for best-of-N (78.2% vs 72.4%) and OOD — but PRMs need **per-step human labels (PRM800K: 800k step-level labels)**. R1 rejected PRM outright (2501.12948 §4.2): step definition is hard, automated step annotation unsatisfactory, model-based PRM "inevitably leads to reward hacking."
- **Per-token credit assignment is unjustified for trading:** tokens are not trades. The war's per-state pnl_pct (`arena/war.py`: per-trade relabels with `pnl_pct` + `regime_up` flags; δ_t = (r_t−V(s_t)) + (r_t−r_field_t) per the reward protocol) is a dense **per-decision** reward — the DeepSeekMath process-supervision form (§4.1.3: step rewards normalized within the group, `Â = Σ r̃` over later steps) at decision level, not token level. No per-token verifier exists in trading.
- **Reward-hacking risk is documented:** outcome supervision produces correct-answer-wrong-reasoning ("spurious" CoT; 2305.20050 §2.5; Uesato et al. arXiv 2211.14275; STaR arXiv 2203.14465 §5: higher temperatures "substantially increase[] the likelihood of a correct answer despite incorrect reasoning"). With a noisy, non-stationary market reward, verbose-but-wrong traces are the predictable failure. **Anti-hacking rails, all from primary sources: format reward (R1 §2.2.2), language-consistency-style reward (R1 §2.3.2), and the trace-outcome alignment gate — never raw pnl alone.**
- **Recommendation:** ORM-style reward at trace end (per-regime group z-score of realized pnl_pct — the arena's own advantage) + format reward; PRM/dense rewards are a later upgrade, at decision level only (2402.03300 §4.1.3 form).

### 4. Proposer-quality gating — sound, with prior art; the metric itself is undefined

- **STaR (arXiv 2203.14465) is the canonical prior art:** generate rationales, **keep only those whose final answer is correct** ("filtering generated examples based on whether their ultimate answer matches the target can be seen as expert feedback," §2), fine-tune, repeat; plus "rationalization" — regenerate a rationale from the correct answer for failures. R1 §2.3.3's correct-only, readable-only filter is the same mechanism at scale. This is the proposer-quality gate.
- **STaR's stated limitation is directly about trading (2203.14465 §6):** "settings with a high level of chance performance (e.g. binary decisions) yield many poor rationales, confounding the STaR approach." War outcomes are near-binary and noisy — so the gate must be a **hit-rate over many war states per regime window**, never per-trace outcomes, against a pinned baseline. **This metric does not exist in the repo**: "war-signal hit-rate" appears only in ADR-0006:56; `arena/war.py` computes books/relabels but no hit-rate; the ADIR/debate baseline (referenced in `data/TRADER.md`, `training/finetune_cycle.py`) is never defined. Defining it is a prerequisite.
- **"Traces derive new value-head features":** prior art covers *traces as SFT targets* (R1 distillation §2.4 — Qwen-7B distilled from R1 traces hits AIME 55.5, Table 5; STaR rationales as training data), **not** CoT→numeric-feature extraction into a 2.9K-param MLP. That step is novel for this project; treat it as the actual research deliverable, with trace filtering (STaR/R1) as the only established mechanism feeding it.

### 5. Compute budget on this box (verified hardware + venvs)

| Phase | Card | Feasibility |
|---|---|---|
| Minting | 7900 GRE 16GB (ROCm llama.cpp, co-resident with qwythos :5802) or 3070 8GB | **Yes on GPU1** (verified: loads at 8.1KB ctx alongside qwythos, 15.3GB/16GB combined); 3070 fits Q8=9.8GB only at small ctx, marginal. Hours for 1–2k traces. |
| Cold-start SFT | 7900 GRE 16GB | **Yes** (QLoRA 7B); needs HF stack in ROCm venv (not installed). |
| GRPO | 7900 GRE 16GB | **Marginal yes** — G=8, max_len 1024, β=0.04, LR 1e-6, μ=1, days/run; needs trl/unsloth on ROCm. **3070: no.** |
| Proposer gate | CPU | **Yes** — war sims already run CPU-side; only the metric is missing. |

---

## Recommended recipe

1. **Phase 1 — minting (reuses: llama-server, `arena/war.py` relabels, `training/custom_train.py`).** Prompt **DeepSeek-V4-Pro-Qwen3.5-9B-MTP** Q8_0 (T=0.6, top-p 0.95 per R1 §3) with war-state contexts; parse the thinking format (`reasoning_content` = CoT, `content` = answer — R1-style via the Qwen3.5 template); **reject-sample on realized pnl_pct > 0** (R1 §2.3.3; STaR filter) per regime window; apply the readability filter (R1 §2.3.3). **Budget at least 2000 tokens/completion** (the teacher's reasoning is verbose — verified 6.9KB CoT for a one-line answer). Target "thousands" (R1 §2.3.1's scale). SFT Qwen2.5-7B on accepted traces — this replaces the reward-weighted-SFT substrate (`flash_train.py`'s BehavioralRLTrainer) as the RL start point.
2. **Phase 2 — true GRPO (reuses: `arena/grpo.py` as the reference math).** Policy = Qwen2.5-7B-Instruct (local), reference = phase-1 SFT checkpoint. TRL GRPOTrainer, custom rewards: per-regime group z-score of pnl_pct + R1 format reward; G=8 (Qwen2.5 §4.3), β=0.04 (DeepSeekMath §4.1.4), LR 1e-6, max_len 1024, μ=1; continuous batching for generation (TRL docs); QLoRA. If VRAM forces it, decouple rollouts (offline advantages) from updates.
3. **Phase 3 — proposer gate (reuses: `arena/war.py`, ADR-0006 bars).** Define hit-rate (fraction of trace-proposed TAKEs with pnl_pct > 0, per regime window) vs a pinned ADIR/debate baseline on the same windows; add trace-outcome alignment (extracted signal vs realized outcome); **war gates before it relabels** (arena-reward-protocol.md Decision 2); never becomes the edge (ADR-0006:118–130).

## Gaps / blockers

1. **trl GRPOTrainer broken in the CUDA venv** (missing `mergekit` — `pip install mergekit` fixes it) **and unsloth vs torch 2.10 mismatch** (wants ≥2.11; cpp extensions skipped → unverified speed/VRAM benefit).
2. **No HF training stack in the ROCm venv** — the only card that can run phase 2. Options: install transformers/trl/unsloth into `/home/mrc/venv` (unsloth ROCm wheels, trl 1.9.2 on PyPI) and validate on torch 2.13+rocm7.2; fallback is plain-transformers GRPOTrainer without unsloth.
3. **The gate metric and ADIR/debate baseline are undefined in code** — must be specified before phase 3 can gate anything. Secondary: the R1 hub download being incomplete is now irrelevant — the V4-Pro Q8_0 teacher is the minting tool (the full-precision teacher is neither needed nor resident).

## Where it hooks in

- `arena/grpo.py` — keep as the reference implementation of the objective (group z-score, KL-in-loss, μ=1); LLM GRPO is the same math at token granularity with G rollouts per prompt.
- `training/flash_train.py` (BehavioralRLTrainer, reward-weighted SFT on closed trades) — the substrate *replaced* by true GRPO per ADR-0006:50–58; its reward weighting is the R1-style rejection-sampling prior.
- `training/custom_train.py` (Qwen2.5-7B SFT) — phase-1 cold-start SFT and phase-3 re-SFT on accept-sampled traces.
- `arena/war.py` — the reward source (per-trade `pnl_pct`, `regime_up`, per-regime books) and gate substrate; hit-rate slots into the `_book_metrics`/relabel output.

## Sources

- **DeepSeek-R1** — arXiv **2501.12948** — GRPO Eqs. 1–3; rule rewards + reward-hacking rationale §2.2.2; cold start §2.3.1; language-consistency reward §2.3.2; rejection sampling + 800k/2-epoch SFT §2.3.3; second RL §2.3.4; SFT-only distillation §2.4; distill-vs-RL §4.1; PRM rejection §4.2; T=0.6/top-p 0.95 §3; Qwen-7B distill AIME 55.5 (Table 5).
- **DeepSeekMath** — arXiv **2402.03300** — objective Eq. 3, unbiased KL Eq. 4, outcome/process advantage §4.1.2–4.1.3, hyper-parameters §4.1.4, single-update form A.1.6 Eq. 21 (quotes verified in chinese-lab-rl-foundations.md).
- **Qwen2.5 Technical Report** — arXiv **2412.15115** — online GRPO, G=8, batch 2048 §4.3.
- **Let's Verify Step by Step (Lightman et al.)** — arXiv **2305.20050** — PRM > ORM best-of-N (78.2 vs 72.4) and OOD; PRM800K step-label scale; spurious CoT under outcome supervision; credit assignment §6.1. **Uesato et al.** — arXiv **2211.14275** — process vs outcome supervision.
- **STaR (Zelikman et al.)** — arXiv **2203.14465** — bootstrap loop, correctness filtering as expert feedback §2, rationalization §3.2, high-chance-setting limitation §6, temperature→spurious-rationale warning §5.
- **TRL GRPOTrainer docs** (huggingface.co/docs/trl) — group advantage, KL approximator, loss variants, custom reward functions incl. the R1 format-reward example, continuous batching for single-GPU.
- **Local verification:** rocm_venv = torch 2.10.0+cu128 (CUDA) with trl 0.24.0 (GRPOTrainer import fails on mergekit), unsloth 2026.7.3 (torch warning); venv = torch 2.13.0+rocm7.2, no HF stack; RTX 3070 8GB + RX 7900 GRE 16GB gfx1100; llama.cpp HIP build v9917 serving :5802; **teacher = DeepSeek-V4-Pro-Qwen3.5-9B-MTP Q8_0 GGUF (9.8GB, qwen35/33 layers/262K ctx, thinking template — verified serving on GPU1 with real CoT output 2026-08-11)**; R1-Distill-Qwen-7B config + Q8_0 GGUF, hub/ incomplete (superseded as teacher); vLLM 0.27.0 / unsloth 2026.8.12 / trl 1.9.2 pip-indexable from both venvs.

*Compute figures for 7B GRPO on 8GB/16GB are engineering estimates, not measured — validate with a smoke run before phase 2.*
