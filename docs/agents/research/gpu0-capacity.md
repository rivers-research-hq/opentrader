# GPU0 Real Simultaneous Capacity (issue #48)

Status: research only — measurements taken, no services touched.
Date: 2026-08-10. Ticket: wayfinder RESEARCH (AFK), darylerivers/opentrader #48.

## 1. Measured VRAM with services resident (nvidia-smi, live)

| GPU | Card | Total | Used | Free | Resident |
|-----|------|-------|------|------|----------|
| 0 (CUDA) | RTX 3070 | 8192 MiB | **6174 MiB** | **1666 MiB (1.63 GiB)** | researcher-fast llama-server + Steam |
| 1 (ROCm) | RX 7900 (Navi 31) | ~16 GiB | ~10.65 GiB | ~5.4 GiB | researcher-deep llama-server |

GPU0 residency breakdown:

- `llama-server` pid 358242 — Hermes-3-Llama-3.1-8B.Q4_K_M, alias `research-fast`, port :5803, ctx 32768, q4_0 KV, `--parallel 1`, 99 layers on GPU: **5936 MiB**
- Steam (3 procs): ~93 MiB
- Free: **1666 MiB**

**The ticket's assumption (~4.9GB used / ~3.3GB free) is wrong.** The fast tier costs 5.8 GiB, not 4.9 — free headroom is **1.6 GiB, roughly half** of what was assumed. This changes most fit verdicts.

## 2. What fits in 1.63 GiB of headroom

Rough VRAM math per candidate (weights + runtime):

| Candidate | Math | Fits? |
|-----------|------|-------|
| **LoRA fine-tune qwen2.5-1.5b F16** (gguf exists, 2.88 GiB file) | F16 weights alone = 2.88 GiB > 1.63 GiB free. PyTorch/Unsloth path (bf16 base + grads + optimizer) ≥ 3.5 GiB. | **NO** |
| LoRA via llama.cpp on a **Q4_K_M 1.5B** base (needs quantizing first — only F16 exists) | base ~0.95 + KV 16K q4 ~0.15 + compute ~0.2 + LoRA/optimizer ~0.2 = ~1.4 GiB | Marginal — needs ~1.4 of 1.63 GiB; violates rcheck margin (10% of 8 GB = 0.8 GiB); also SM-contention with resident server during train steps |
| **FinBERT batch inference** (`ProsusAI/finbert` via HF pipeline — already used in `setup_search/task_sentiment_expert.py:78`) | 110M params fp16 ≈ 0.23 GiB + activations/batch ≈ 0.3–0.6 GiB total | **YES** — comfortable, leaves ≥ 1 GiB |
| **Small quantized model server** (1.1–1.5B Q4_K_M, e.g. qwen2.5-1.5b Q4, qwen2.5-coder-1.5b) | 1.5B Q4 ~0.95 + 16K q4 KV ~0.15 + compute ~0.2 = ~1.3 GiB | **YES, tight** (0.3 GiB margin); 0.5–1.1B Q4 (~0.4–0.7 GiB) fits comfortably |
| 3B Q4_K_M | ~1.9 GiB | **NO** |
| 7B Q4_K_M (qwen2.5-7b-instruct, qwen2.5-coder-7b ggufs exist) | ~4.3 GiB | **NO** |
| A second 8B (Hermes/gemma/qwythos) | ~4.9 GiB | **NO** |

Practical ranking for a GPU0 parallel workload: (1) FinBERT batch scoring, (2) a small Q4 1.5B llama-server on a new port, (3) llama.cpp LoRA fine-tune on a freshly-quantized 1.5B Q4 — all three can coexist, but the LoRA train's duty cycle is the most disruptive to the resident fast tier.

## 3. Debate placement: where bull/bear/risk actually run

- Front door: `gpu_sync.py` (:5801) load-balances/fails-over across :5802 (GPU1, ROCm, deep) and :5803 (GPU0, CUDA, fast) — routes by `model` field when it matches an advertised backend model, else round-robin (`gpu_sync.py:152-208`).
- Harness config (`config/harness_config.json`): `llama_host` = `gpu0_host` = `http://127.0.0.1:5801`, `debate_model` = qwythos-9b-mtp (bull), `risk_model` = qwen2.5-7b-instruct (bear+risk).
- Harness (`harness.py:538-553`): ADIR mode passes `bull_host=llama_host`, `bear_host=risk_host=gpu0_host` — **both resolve to :5801**, so in the live config all three roles go through gpu_sync. The comment block (harness.py:541-544) says bull→GPU1 / bear+risk→GPU0, but that is **stale** (references qwen27-trader and qwen2.5-coder-7b on :5803 — neither is resident; :5803 hosts Hermes-3-8B). Since requested model ids ("qwythos-9b-mtp", "qwen2.5-7b-instruct") match no advertised backend, requests actually **round-robin across both GPUs — nothing is pinned**.
- ADIR flow (`mot/agents/adir_debate.py`): per symbol — Phase 1 bull+bear in parallel (`ThreadPoolExecutor(max_workers=2)`, :608), Phase 2 falsification (1 call, :653-654), risk is a **heuristic** inside `_synthesize` (:742-756, no LLM call). So ~2–3 LLM calls per symbol, `universe_focus=6` → **~12–18 calls per cycle**, capped at 4 concurrent by a global semaphore (:86). Bear and risk use the same model: `qwen2.5-7b-instruct`.

**What enabling the gated debate costs GPU0:**
- VRAM: ~0 extra. The resident Hermes server pre-allocates its 32K q4 KV inside its 5936 MiB; bear/falsify calls ride the resident context pool. Risk grows only if prompts push KV limits (they won't at 2–3K tokens).
- Duty cycle: the real cost. :5803 is `--parallel 1` — every bear/falsify call **serializes against researcher-fast traffic**. At ~20–60 s per 8B call, a 6-symbol cycle adds ~12–18 calls ≈ 8–15 min of GPU0 occupation per harness cycle, with the semaphore allowing overlap but the server's single slot forcing queueing. The debate would visibly disturb the resident :5803 tier (ticket constraint), even though VRAM is untouched.

## 4. Verdict

**The gated-debate bear/risk role is the wrong first pick for GPU0's 1.6 GiB:** it adds ~zero VRAM but hijacks the single slot of the resident fast server for minutes per cycle. The natural parallel workloads are FinBERT batch scoring (comfortable) or a small Q4 1.5B server on a new port (tight but honest), with a llama.cpp-LoRA 1.5B fine-tune only after quantizing a Q4 base — none of which touch the resident tiers. If the debate must run, point bear/risk at a dedicated small model port, not :5803.
