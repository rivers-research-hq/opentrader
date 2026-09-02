# Frontier scan: in-development AI infra that fits 31 GB RAM + 16 GB RX 7900 GRE (gfx1100)

**Date:** 2026-08-17
**Scope:** Research only. No code or services touched.
**Box:** 31 GB RAM (33.5 GB total, 8 GB swap) · AMD RX 7900 GRE 16 GB (gfx1100, HIP/ROCm) · RTX 3070 8 GB (CUDA) · 16 CPU threads.
**Companion report:** [`rag-embeddings-ai-base.md`](rag-embeddings-ai-base.md) covers topic #3 (embedding/rerank models) in depth; this scan cross-references it.
**Source discipline:** every claim cites the primary source that owns it (GitHub PR/issue, HF model card, arxiv, upstream source). Local repos (`~/src/llama-cpp-upstream`, `~/src/modelai-llama.cpp`) are ggml-org master at HEAD and were inspected directly.

---

## TL;DR — top 5 actionable findings

1. **The box's Qwen3.8-27B GGUF already contains MTP tensors (`qwen35.nextn_predict_layers`, `blk.64.nextn.*`), but the running server (`port 5804`, `--spec-type none` default) does not enable speculative decoding.** Upstream llama.cpp now has `--spec-type draft-mtp` as a first-class option; enabling it is a zero-download, likely-free token-rate win on a 22 t/s setup. Sources: [llama.cpp `docs/speculative.md`](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) (local mirror inspected), GGUF tensor names verified locally on the served blob.
2. **DFlash (block-diffusion speculative decoding) is merged upstream and works on gfx1100 via ROCm — measured 2.62× on an RX 7900 XTX (gfx1100) Qwen3-8B Q4_K_M, 93.75% draft acceptance.** Caveats: speedup shrinks on hybrid/MoE targets (the box's 27B is a Gated-DeltaNet hybrid), and the original PR had a cross-request crash that is fixed since merge. Sources: [llama.cpp PR #22105](https://github.com/ggml-org/llama.cpp/pull/22105), [lucasacchiricciardi/llama-dflash-rocm](https://github.com/lucasacchiricciardi/llama-dflash-rocm), [DFlash paper arxiv 2602.06036](https://huggingface.co/papers/2602.06036).
3. **TurboQuant (turbo3/turbo4 KV-cache types) is NOT in upstream llama.cpp — it lives in forks, but one of them (TheTom's) now has HIP/ROCm support plus a turbo4 prefill path for gfx1100.** Upstream still supports only F32/F16/BF16/Q8_0/Q4_0/Q4_1/IQ4_NL/Q5_0/Q5_1 KV types (verified in `common/arg.cpp`). 4.57–5.12× KV compression is real but requires a fork build. Sources: [discussion #20969](https://github.com/ggml-org/llama.cpp/discussions/20969), [TheTom/llama-cpp-turboquant](https://github.com/TheTom/llama-cpp-turboquant), [TurboQuant paper 2504.19874](https://huggingface.co/papers/2504.19874).
4. **Best RAM-frugal RAG pair stays Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B (Q8 GGUFs ≈ 568 MB each, Apache-2.0, 32K ctx, MTEB Eng-v2 70.70).** Both serve from the existing ROCm llama.cpp binary via `--pooling last` / `--pooling rank`. A new smaller option exists: LFM2.5-Embedding-350M / LFM2.5-ColBERT-350M landed upstream (#24913). Sources: [Qwen3-Embedding-0.6B card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF), upstream commit `88636e178` (verified locally).
5. **RAG-lite / agent-context on this box = combine llama.cpp's native `--cache-reuse` + prompt cache (`--cache-ram`) + the fork's own KV-compaction feature; LLMLingua-2 (Microsoft) is the only small-footprint prompt-compression model worth pulling in (compression 2–5×, latency 1.6–2.9×, runs on a ~560 M XLM-RoBERTa-large).** Sources: [llama.cpp server docs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [LLMLingua-2 arxiv 2403.12968](https://huggingface.co/papers/2403.12968), `modelai-llama.cpp` fork (local).

---

## 1. MTP / DFlash speculative decoding on ROCm / gfx1100

### 1.1 Status of MTP in llama.cpp — upstream is past the "AMD can't run it" stage

MTP (Multi-Token Prediction) draft heads are now first-class in upstream llama.cpp. `docs/speculative.md` lists `draft-mtp` ("Use Multi Token Prediction (MTP) heads from the main model") among the `--spec-type` values — no separate draft file needed. The current master (local `llama-cpp-upstream` HEAD `b75ecd197`, 2026-08-17) implements MTP for a broad model list, all merged:

- DeepSeek V3.2 MTP — PR #26457
- GLM-4.7-Flash MTP — PR #24868
- Qwen3-Next MTP — PR #25589
- Nemotron MTP — PR #26725
- GLM-DSA (GLM-5.2) NextN/MTP — PR #25980
- DeepSeek-V4 MTP + DSpark — PR #25784
- MiMo V2 MTP — PR #26412
- Huawei Hy3 MTP speculative decoding — PR #25395
- MTP model-type auto-detect in `llama-speculative` — PR #27005
- `--models-dir` MTP assistant-model loading — PR #24431

Verified directly in local source: `src/models/qwen35.cpp` implements `LLM_GRAPH_TYPE_DECODER_MTP` (Qwen3.5/3.6/3.8 dense series), and `src/models/qwen35moe.cpp` for MoE. `src/llama-model.cpp:532,645` route QWEN35/QWEN35MOE/QWEN3NEXT through the MTP-capable path. **MTP on hybrid (Gated-DeltaNet) targets is explicitly supported** (`mtp_on_hybrid_qwen`, `mtp_on_hybrid_nemotron`, `src/llama-model.cpp:2262-2281`).

**ROCm path:** the `ggml-hip` backend is a hipcc recompilation of the `ggml-cuda` sources (`ggml/src/ggml-hip/CMakeLists.txt` globs `../ggml-cuda/*.cu`). Since MTP/DFlash are graph-level features built on ggml ops (not bespoke CUDA-only kernels), they run on any backend that implements the underlying attention/FFN ops — including HIP/gfx1100. Confirmed by real measurements (below) and by the box's own setup: the 27B already runs on the GRE through `build-wmma` (HIP/gfx1100, `GGML_HIP=ON`, `GGML_HIP_ROCWMMA_FATTN=ON`, verified in `CMakeCache.txt`).

### 1.2 DFlash — merged upstream, ROCm-proven on gfx1100

**DFlash PR #22105 is MERGED** into ggml-org master (June 28, 2026) by ggerganov. DFlash is block-diffusion speculative decoding: a draft emits a whole block of tokens in a single forward pass instead of drafting one token at a time, giving up to 8× on Qwen3 per the PR and "over 6× lossless, up to 2.5× more than EAGLE-3" per the paper ([arxiv 2602.06036](https://huggingface.co/papers/2602.06036)).

- Usage: `llama-server -m target.gguf -md draft.gguf --spec-type draft-dflash --spec-draft-n-max 15 -fa on --jinja`.
- **ROCm on gfx1100 is proven:** [lucasacchiricciardi/llama-dflash-rocm](https://github.com/lucasacchiricciardi/llama-dflash-rocm) packages PR #22105 for RX 7900 XTX (gfx1100, ROCm 6.4) and measured **2.62× (50.7 → 132.7 t/s) on Qwen3-8B Q4_K_M, 93.75% draft acceptance**; ~1.50× on gpt-oss-20b (MoE) due to routing overhead during parallel verification. The PR is described as "CUDA-first" but works on ROCm — the docker build is the reproducible recipe.
- **Draft models available on HF** (all MIT/Apache, with GGUF conversions for llama.cpp):
  - `z-lab/Qwen3.6-27B-DFlash` (MIT, 168k downloads) — [card](https://huggingface.co/z-lab/Qwen3.6-27B-DFlash)
  - `z-lab/Qwen3.5-9B-DFlash` — [card](https://huggingface.co/z-lab/Qwen3.5-9B-DFlash)
  - `z-lab/Qwen3.6-35B-A3B-DFlash` — [card](https://huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash)
  - `z-lab/Qwen3-Coder-30B-A3B-DFlash`, `z-lab/Qwen3.5-27B-DFlash`, `z-lab/gemma-4-31B-it-DFlash`
  - GGUF: `spiritbuun/Qwen3.6-27B-DFlash-GGUF`, `Lucebox/Qwen3.6-27B-DFlash-GGUF`, `Alittlehammmer/Qwen3.6-27B-DFlash-GGUF-llama.cpp`
  - New & unproven: `rwmacy/qwen3.8-27b-dflash-drafter-fp8-b70` (Qwen3.8-27B drafter, 22 downloads, specforge/Intel-XPU tags) — [card](https://huggingface.co/rwmacy/qwen3.8-27b-dflash-drafter-fp8-b70)
- **Auto-download of DFlash/EAGLE3 HF sidecars** merged (#25811) and spec-type auto-detect from GGUF metadata (#26814) mean `-hf` model runs can pull the right drafter automatically.

### 1.3 Caveats that matter for THIS box

- **Hybrid targets (Qwen3.5/3.6/3.8 Gated-DeltaNet) get smaller DFlash speedups.** The PR's own benchmark of `Qwen3.5-9B`/`Qwen3.5-27B`/`Qwen3.6-27B` shows speedup lagging pure-attention targets because the target's recurrent state is not decomposable by token position — rejected draft blocks can't be discarded with `seq_rm`, so each rejection costs an extra target forward. The box's main model (Qwen3.8-27B, hybrid) is exactly this case. Expect DFlash gains here to be below the dense-model 2.6×.
- **Original PR had a cross-request crash** (`GGML_ASSERT(n_new >= 1)` in `speculative.cpp` when the KV cache is restored after a request). Fixed in the merged version, but re-verify on the fork build before trusting multi-request workloads.
- **mxfp4 re-quantization is blocked** in llama.cpp (`requantizing from type mxfp4 is disabled`) — a 27B in native mxfp4 GGUF must be used as-is, not re-quantized.
- **MTP on hybrid Qwen3.5 is a different, lighter mechanism** than DFlash and is supported on the box's exact architecture. It is the cheapest first experiment (no new model download).

### 1.4 Verdict for the box

| Path | Effort | Expected effect | Recommendation |
|---|---|---|---|
| `--spec-type draft-mtp` on the running 27B (GGUF already has MTP heads) | ~0 (config change) | t/s ↑, quantifiable in minutes | **DO FIRST** — measure on port 5804 |
| DFlash drafter for the 27B | Medium (download + convert + rebench) | moderate (hybrid target) | Evaluate after MTP measurement; prefer a Qwen3.5/3.6-27B-family drafter over the untested fp8 one |
| 9B MTP server (port 5802) re-enable | ~0 | box currently runs it with `--spec-type none` | Investigate why it was disabled |

---

## 2. KV-cache efficiency: what's landed vs. in development

### 2.1 Upstream (merged) KV state

- **Supported `--cache-type-k/v` values in current master** (verified in `common/arg.cpp:305-311`): `F32, F16, BF16, Q8_0, Q4_0, Q4_1, IQ4_NL, Q5_0, Q5_1`. **No turbo types upstream.**
- **`--kv-unified`** (single unified KV buffer across slots) — merged; the 9B MTP server already runs with it.
- **Prompt cache + `--cache-ram`** — merged (PR #16391); idle slots saved to the prompt cache (`--cache-idle-slots`). The 27B server already runs `--cache-ram 2048`.
- **`--cache-reuse N`** — reuse prefix KV via KV shifting; disabled automatically for multimodal and when unsupported. Server-side, agent-loop friendly.
- **KV-cache quantization hardening** merged: "extend cache quantization checks" (#21586), "reserve space for quantized kv-cache at startup" (#23907), "MTP layer kv-cache respects draft type ctk" (#23646), SWA/cache-quant interaction fixes (#21277/#21332/#21513).
- **Cache-cells sharing / avoidance of copies** (#24267, #24277) and **server speculative checkpointing** for hybrid targets (#19493, #22227) — relevant to hybrid Qwen3.5 speedup.

The box is already at the frontier of upstream KV usage: `q8_0` K+V caches on both servers, `--kv-unified` on the 9B, `--cache-ram` on the 27B, `--flash-attn on` on the 27B.

### 2.2 TurboQuant / turbo3 / turbo4 — the "landing" candidate, still fork-only

- **Paper:** [TurboQuant arxiv 2504.19874](https://huggingface.co/papers/2504.19874) (Zandieh et al., ICLR 2026): random rotation + per-coordinate scalar quantizers; ~3.5 bits/val "absolute quality neutrality", ~2.5 bits marginal degradation.
- **llama.cpp integration is community-driven, NOT merged.** Tracking discussion: [ggml-org/llama.cpp #20969](https://github.com/ggml-org/llama.cpp/discussions/20969) (181 comments). Active fork branches:
  - **TheTom/llama-cpp-turboquant** `feature/turboquant-kv-cache` — everything integrated: spiritbuun's CUDA work, block_size=128 (turbo3 4.57× → 5.12×), **HIP/ROCm support**, InnerQ per-channel equalization, **turbo4 prefill optimizations**. Per discussion: "Building from TheTom's HEAD gives you a working CUDA path with the improved compression ratios."
  - **TheTom/turboquant_plus** — Metal (Apple Silicon) turbo3 (3.25 bits, 4.9×) and turbo4 (4.25 bits, 3.8×) native KV types; detailed bug write-ups (WHT rotation transpose, column-major storage) useful for any port.
  - **domvox/llama.cpp-turboquant-hip** and **Tom1tk/mtp-pflash-turboquant-hip** — HIP/ROCm forks explicitly targeting **RDNA3 gfx1100** (RX 7900 XTX). The latter also bundles **PFlash** (speculative prefill: compress long prompts with a draft model before target prefill; 43% TTFT speedup at 128k, keep-ratio 0.55 quality floor on code tasks) — direct fit for this box's long-context RAG needs.
  - **atomicmilkshake/llama-cpp-turboquant** — TurboQuant (turbo2/3/4) + **TriAttention** (GPU KV-cache pruning, arxiv 2604.04921, RoPE-inverted key scoring + eviction) for long context.
- **Measured reality (from the discussion, with corrections flagged):** turbo3 K+V ≈ 14 KB/token vs ~64 KB fp16 (4.6×) on RTX 5090; but generation decode can degrade ~37% at 110K ctx with naive q4_0 due to per-token dequantization — TurboQuant's selling point is computing directly on quantized values. The single-user claim "~4.6-5.1× KV compression with minimal quality loss" is consistent across the discussion and the kaitchup test.

### 2.3 Context compaction / cache-reuse

- **Upstream:** prefix/cache reuse via `--cache-reuse`, prompt cache, `--kv-unified` (all above). No upstream "context compaction" (token-eviction) feature merged — the closest is the fork work below.
- **Fork-only (this box's own repo):** `modelai-llama.cpp` carries a substantial **KV-compaction** feature (`docs/kv-compaction-integration.md`, `llama-kv-compact-bench`, a solver/query/select/OMP pipeline, compacted-prefix store, hybrid-SSM and iSWA-base support; standard-RoPE hybrid layouts supported, pure-SSM N/A). This is already on disk and not in upstream — a local differentiator.

### 2.4 Verdict for the box

- **Now (no rebuild):** keep `q8_0`; enable `--cache-reuse` on the 27B if the workload repeats system prompts; consider `iq4_nl` K cache for a 2× KV shrink with a one-line flag (`--cache-type-k iq4_nl`) if context length is the binding constraint.
- **Experiment (fork build):** a HIP TurboQuant build (domvox or Tom1tk) on the GRE is the single highest-upside KV lever — 16 GB GRE + q8_0 KV means long context is expensive; turbo3/4 would roughly quadruple usable context at equal VRAM. Costs: fork maintenance, and the forks are one-person efforts.
- **Do not expect turbo KV types in upstream soon** — #20969 is still an ideas discussion; no merge PR.

---

## 3. RAM-frugal embedding / rerank models (≤4 GB)

See the companion report [`rag-embeddings-ai-base.md`](rag-embeddings-ai-base.md) for the full benchmark table. Summary of the current state:

- **Pick: Qwen3-Embedding-0.6B + Qwen3-Reranker-0.6B.** Both Apache-2.0, 32K ctx, 100+ languages; Q8 GGUFs ≈ 568 MB each; serve from the existing ROCm llama.cpp binary (`--pooling last` / `--pooling rank`). MTEB Eng-v2 mean 70.70 for the 0.6B embedding (ties gte-Qwen2-7B at 1/10th the params). Sources: [Qwen3-Embedding-0.6B card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Qwen3-Embedding-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF) (Q8_0 = 595 MB per HF API), [Qwen3-Reranker-0.6B card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B), [ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF). Paper: [Qwen3 Embedding arxiv 2506.05176](https://huggingface.co/papers/2506.05176).
- **New smaller option landed upstream:** LFM2.5-Embedding-350M and LFM2.5-ColBERT-350M (Liquid AI) merged in `88636e178` (model: add LFM2.5-ColBERT-350M and LFM2.5-Embedding-350M, PR #24913) — ~350 M, ColBERT-style multi-vector. Worth checking if even the 568 MB Qwen pair is too heavy; not benchmarked here.
- Qwen3-Embedding-4B-GGUF also exists (≈4 GB F16 total) if quality-per-GB tilts toward the 4B — but the 0.6B already ties 7B-class on MTEB Eng-v2, so the 4B is rarely worth the RAM.

---

## 4. RAG-lite / agent-context approaches for small-memory systems

### 4.1 Prompt/context compression

- **LLMLingua-2 (Microsoft)** is the state of the art for task-agnostic, small-model prompt compression. Formulates compression as token classification on a Transformer encoder (XLM-RoBERTa-large / mBERT — i.e. a ~560 M model, fits this box easily on CPU). Compression 2–5×, end-to-end latency 1.6–2.9×, 3–6× faster than entropy-based baselines. Sources: [paper arxiv 2403.12968](https://huggingface.co/papers/2403.12968), models [microsoft/llmlingua-2-xlm-roberta-large-meetingbank](https://huggingface.co/microsoft/llmlingua-2-xlm-roberta-large-meetingbank) / [llmlingua-2-bert-base-multilingual-cased-meetingbank](https://huggingface.co/microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank). License MIT/Apache.
- **PFlash (fork)** — speculative prefill from the Tom1tk fork (above): draft model compresses the prompt before target prefill; 43% TTFT speedup at 128k. Same hardware as this box.

### 4.2 Retrieval + agent-context plumbing (all local, no new deps)

- **llama.cpp `examples/retrieval`** — chunked cosine-similarity retrieval against embedding models (`llama-retrieval` binary present in the local build; see [PR #6193](https://github.com/ggml-org/llama.cpp/pull/6193)). Good enough for a first RAG-lite loop without a vector DB.
- **`--cache-reuse` + prompt cache (`--cache-ram`) + `--kv-unified`** on the server make repeated system prompts / tool schemas nearly free across turns — the cheapest "agent-context" optimization available today, already partially configured on this box.
- **KV compaction (fork, on disk)** is a token-eviction/prefix-compaction feature that specifically attacks long agent conversations.
- **`llama-cvector-generator`** (in local build) builds characteristic vectors / negative vectors for prompt suppression.

### 4.3 Verdict for the box

Build RAG-lite in this order: (1) enable `--cache-reuse` and confirm prompt-cache hits; (2) add Qwen3-Embedding-0.6B + reranker (companion report) for retrieval; (3) LLMLingua-2 as an optional pre-prompt compressor for very long tool outputs; (4) revisit KV-compaction fork feature for multi-turn agents. Skip heavy vector DBs (Chroma/FAISS) until corpus > ~100k chunks.

---

## 5. Small-model tech / serving tools that materially help the 22 t/s Qwen3.8-27B setup

### 5.1 What the box runs today (verified)

- **27B "qwen38-agentic"** on `build-wmma` (HIP/gfx1100) — `--ctx-size 32768 --cache-type-k/v q8_0 --fit off --flash-attn on --cache-ram 2048 --n-gpu-layers 99 --reasoning-format deepseek`. GGUF: arch `qwen35`, **contains MTP tensors** (`qwen35.nextn_predict_layers`, `blk.64.nextn.eh_proj/enorm/hnorm`), 13.4 GB blob, served from a 13.4 GB file at ~15.2/17.2 GB GRE VRAM used.
- **9B MTP "qwythos-9b-mtp"** on `build-cuda` (RTX 3070) — `DeepSeek-V4-Pro-Qwen3.5-9B-MTP-Q4_K_M.gguf`, but launched with **`--spec-type none`** (MTP deliberately off).

### 5.2 Highest-leverage moves, in order

1. **Enable MTP on the 27B:** `--spec-type draft-mtp` (no download). The GGUF already carries the heads. This is the cheapest possible tokens/s experiment and directly tests the "MTP on hybrid Qwen3.5" path that upstream now supports. Source: [docs/speculative.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md).
2. **Measure before/after with `llama-bench` or server `/metrics`** — the box already runs a nightly-style benchmark culture (`bench-results/` in the fork).
3. **DFlash for the 27B:** only if MTP under-delivers. Prefer `z-lab/Qwen3.6-27B-DFlash`-family drafts or wait for a mature Qwen3.8-27B drafter; the fp8 XPU one is untested here. Expect hybrid-target speedup ≈1.3–1.6× (not the dense 2.6×) per the PR's own numbers.
4. **Serving layer:** `llama-swap` (already in `~/src/llama-swap`) transparently hot-swaps llama-server backends — ideal for running embedding/rerank/draft servers alongside the 27B without manual port juggling. Source: [llama-swap README](https://github.com/mostlygeek/llama-swap).
5. **Do NOT switch the 27B to vLLM/SGLang on this box:** vLLM needs safetensors/FP8 (27B FP8 ≈ 28 GB weights + KV → exceeds 16 GB GRE + tight on 31 GB RAM) and adds a multi-GB runtime; llama.cpp GGUF + HIP is the right serving path here. SGLang/vLLM only matter if multi-user concurrency or the FP8 NVFP4 path becomes a requirement. (Model cards list both as supported serving options — [Qwen3.8-27B card](https://huggingface.co/Qwen/Qwen3.8-27B) — but hardware rules them out.)
6. **NVFP4 GGUFs for the 27B** (e.g. `esatapedico/Qwen3.8-27B-NVFP4-MTP-GGUF`, updated 2026-08-17, Blackwell sm_120 tag) are sized for Blackwell GPUs; the GRE is gfx1100 and the 3070 is sm_86 — treat NVFP4 files as not usable here without validation, prefer Q4_K_M/Q3_K_XL GGUFs (`unsloth/Qwen3.8-27B-GGUF` already in use via ollama).

### 5.3 Small-model tech worth tracking

- **DSpark** (DeepSeek, semi-autoregressive Markov head on a DFlash backbone) — merged in upstream #25173 and #26275 (speculators-format checkpoints). Drafts for Qwen3-4B exist; a DSpark drafter for the 27B family would combine block drafting with left-to-right signal. Sources: [docs/speculative.md](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md), [PR #25173](https://github.com/ggml-org/llama.cpp/pull/25173).
- **EAGLE-3** drafts (single-layer autoregressive) — broadest draft-model ecosystem on HF (AngelSlim/Qwen3-*_eagle3, yuhuili EAGLE3-*, nvidia gpt-oss Eagle3, RedHat speculators). A ~1-layer drafter is the smallest possible draft footprint; good for the 9B RTX-3070 slot. Listed in docs/speculative.md.

---

## Appendix A — Hardware baseline (verified this session)

| Resource | State |
|---|---|
| AMD RX 7900 GRE 16 GB (gfx1100) | Active, ~15.2/17.2 GB VRAM used by qwen38-agentic (HIP build-wmma); 14% gpu_busy; idle otherwise |
| RTX 3070 8 GB | ~6.0/8.2 GB used by qwythos-9b-mtp (CUDA build-cuda) |
| RAM | 33.5 GB total, ~24.8 GB available, 8 GB swap |
| ROCm | `/opt/rocm` present, ROCm 7.x toolchain (clang++ `hipconfig`), `rocm-smi` works |
| CUDA | `/opt/cuda` present, driver supports RTX 3070 |

## Appendix B — Reconciling with the companion report

The companion `rag-embeddings-ai-base.md` (same box, same day) states `/home/mrc/src/llama-cpp-upstream/build` is GGML_HIP=ON / GGML_CUDA=OFF. Re-verified this session: `GGML_CUDA:BOOL=OFF` in that build's `CMakeCache.txt`; `build/bin` contains `llama-server`, `llama-embedding`, `llama-retrieval`. No contradiction. Note the *active* 27B server runs from the **modelai fork's** `build-wmma` (HIP, ROCWMMA_FA=ON), which is a different build dir than the upstream `build/` the companion report audited — both are HIP/ROCm-capable on the GRE.

## Appendix C — Sources

- llama.cpp `docs/speculative.md` (MTP/DFlash/DSpark/EAGLE-3/n-gram; draft-model lists): https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- DFlash PR #22105 (merged): https://github.com/ggml-org/llama.cpp/pull/22105
- DFlash ROCm/gfx1100 build + 2.62× measurement: https://github.com/lucasacchiricciardi/llama-dflash-rocm
- DFlash paper: https://huggingface.co/papers/2602.06036 (arxiv 2602.06036)
- TurboQuant discussion: https://github.com/ggml-org/llama.cpp/discussions/20969
- TurboQuant forks: https://github.com/TheTom/llama-cpp-turboquant · https://github.com/TheTom/turboquant_plus · https://github.com/domvox/llama.cpp-turboquant-hip · https://github.com/Tom1tk/mtp-pflash-turboquant-hip · https://github.com/atomicmilkshake/llama-cpp-turboquant
- TurboQuant paper: https://huggingface.co/papers/2504.19874 (arxiv 2504.19874)
- Qwen3-Embedding / Reranker cards + GGUFs: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B · https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF · https://huggingface.co/Qwen/Qwen3-Reranker-0.6B · https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
- Qwen3 Embedding paper: https://huggingface.co/papers/2506.05176 (arxiv 2506.05176)
- LLMLingua-2 paper + models: https://huggingface.co/papers/2403.12968 · https://huggingface.co/microsoft/llmlingua-2-xlm-roberta-large-meetingbank
- Qwen3.8-27B model card (MTP, hybrid arch, context): https://huggingface.co/Qwen/Qwen3.8-27B
- DFlash draft models: https://huggingface.co/z-lab/Qwen3.6-27B-DFlash · https://huggingface.co/z-lab/Qwen3.5-9B-DFlash · https://huggingface.co/rwmacy/qwen3.8-27b-dflash-drafter-fp8-b70
- llama.cpp PRs (MTP model support): #26457 #24868 #25589 #26725 #25980 #25784 #26412 #25395 #27005 #24431 #24913 (see github.com/ggml-org/llama.cpp/pull/<id>)
- llama.cpp server docs (cache-reuse, cache-ram, kv-unified, speculative checkpointing): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- ROCm official llama.cpp docs (gfx1100 build targets): https://rocm.docs.amd.com/projects/llama-cpp/en/docs-26.02/install/llama-cpp-install.html
- llama-swap: https://github.com/mostlygeek/llama-swap
- Local primary sources: `~/src/llama-cpp-upstream` (HEAD b75ecd197), `~/src/modelai-llama.cpp` (modelai-main, docs/kv-compaction-integration.md, build-wmma CMakeCache), `~/src/llama-swap`, `rocm-smi`, `nvidia-smi`, running `llama-server` command lines, served GGUF tensor inspection.
