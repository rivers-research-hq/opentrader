# RAG embeddings + rerank for "AI base" — RAM-frugal stack on this box

**Date:** 2026-08-17
**Scope:** Research only. No code or services touched.
**Box:** 31 GB RAM · AMD RX 7900 GRE 16 GB (ROCm) · RTX 3070 8 GB (CUDA) · 116 GB free disk on `/home`.

---

## TL;DR — recommended stack

| Role | Model | Size on disk | VRAM | How it is served |
|---|---|---|---|---|
| Embedding | **Qwen/Qwen3-Embedding-0.6B** (`Qwen3-Embedding-0.6B-Q8_0.gguf`) | **568 MB** | ~0.6–1.0 GB | **llama.cpp `llama-server --embedding --pooling last`** → `POST /v1/embeddings` (OpenAI-compatible). Already-built local HIP/ROCm server supports this today. |
| Reranker | **Qwen/Qwen3-Reranker-0.6B** (`ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF`) | **568 MB** | ~0.6–1.0 GB | **llama.cpp `llama-server --embedding --pooling rank`** → `POST /v1/rerank` / `/v1/reranking` (Jina/TEI-shaped). Same server binary. |
| Vector store | **sqlite-vec** (SQLite extension) — lightest persistent option; **FAISS** if corpus gets > ~1 M chunks | ~10–20 MB + 4 KB/1024-dim vector | RAM only | In-process; no extra server. Chroma is the "easy" alternative but pulls ~300 MB+ of deps + runtime. |
| Context model | existing qwen38 (32K ctx) | — | — | Reranked top-k chunks stuffed into prompt. |

**Total incremental footprint:** ~**1.1 GB disk**, ~**1.3–2 GB VRAM** (both models on the GRE's leftover VRAM; or reranker on the 3070), ~**1.5–2 GB system RAM** for the two llama.cpp server processes + store.

**Why this wins on quality-per-GB:** the 0.6B Qwen3 pair beats every other ≤4 GB embedding model on the MTEB **English v2** leaderboard and ties 7B-class models, and the 0.6B reranker is the best small reranker on MTEB-R. Both have 32K context (matches the 32K qwen38 context) and are multilingual (100+ languages, incl. Chinese, which the code repo + trading docs will need).

---

## 1. Embedding models (≤4 GB), ranked for quality-per-GB

All scores are the models' own reported MTEB results on their official model cards (primary sources, cited inline).

> **Benchmark caveat, read first.** MTEB English v1 (Average over 56 tasks) and MTEB **English v2** are different benchmarks; v1 and v2 numbers are **not** comparable across. Where a card reports one or the other, it is marked. Retrieval-subset scores (NDCG@10) are also not the same as the task average. The table below keeps each benchmark in its own row so ranking stays apples-to-apples.

| Model | Params | Dim / ctx | Bench & score | Source |
|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | 0.6 B | 1024 (MRL 32–1024) / 32K | MTEB **Eng v2** Mean(Task) **70.70** · MTEB **Multilingual** Mean(Task) **64.33** · C-MTEB 66.33 | [Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) (tables: MTEB Multilingual, MTEB Eng v2, C-MTEB); [GGUF README](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF) |
| bge-m3 (BAAI) | 0.6 B | 1024 / 8192 | MTEB **Multilingual** Mean(Task) **59.56** (same table, for comparison) | [Qwen GGUF README MTEB table](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF), values for compared models retrieved from the MTEB online leaderboard (May 2025) |
| bge-small-en-v1.5 (BAAI) | 33 M | 384 / 512 | MTEB **Eng v1** **62.17** | [bge-small-en-v1.5 card](https://huggingface.co/BAAI/bge-small-en-v1.5) |
| nomic-embed-text-v1.5 | 137 M | 768 / 8192 | MTEB **v1** (MTEB v1.18.0) **62.39** | [nomic card](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) |
| gte-small (thenlper) | 33 M | 384 / 512 | MTEB **v1** Average(56) **61.36** | [gte-small card](https://huggingface.co/thenlper/gte-small) |
| snowflake-arctic-embed-m | 110 M | 768 / 512 | MTEB Retrieval NDCG@10 **54.90** (retrieval subset only; v1.0 superseded by `-m-v2.0`) | [arctic-embed-m card](https://huggingface.co/Snowflake/snowflake-arctic-embed-m) |

### Ranking for quality-per-GB (≤4 GB)

1. **Qwen3-Embedding-0.6B** — clear #1. On MTEB **English v2** it scores 70.70 vs. stella_en_1.5B_v5 (69.43), gte-Qwen2-1.5B (67.20), multilingual-e5-large (65.53) — and ties gte-Qwen2-**7B** (70.72) at 1/10th the params. On MTEB **Multilingual** it beats multilingual-e5-large-instruct (64.33 vs 63.22) and bge-m3 (64.33 vs 59.56). 0.6B → Q8 GGUF is only **568 MB**.
2. **bge-m3** — the old favourite; multilingual + 8K ctx + dense/sparse/colbert. But on the same MTEB Multilingual table it trails Qwen3-0.6B by ~4.8 points, and no official GGUF path (community conversions only). Still a fine fallback if you want the hybrid sparse+dense trick.
3. **nomic-embed-text-v1.5** — best of the tiny English BERT-class (62.39), 8192 ctx, matryoshka. Requires `search_document:`/`search_query:` prefixes and `trust_remote_code`; English-only.
4. **bge-small-en-v1.5** (62.17) ≈ **gte-small** (61.36) — both 33 M/384-dim/512-ctx English-only. Fine for tiny embeddings (f16 GGUF ~66 MB) but 8+ points behind Qwen3 on the *harder* v2 benchmark and limited to 512-token docs.
5. **arctic-embed-m** — 54.90 retrieval NDCG@10 (v1.0); 768-dim/512-ctx English. The v2.0 multilingual refresh exists but is still BERT-class quality.

**Decision:** Qwen3-Embedding-0.6B is the quality-per-GB winner and also the only one with a first-party GGUF + documented llama.cpp path (see §3).

---

## 2. Reranker (≤1–2 GB)

Rerankers compared on the same eval (retrieval subsets MTEB-R / CMTEB-R / MMTEB-R / MLDR / MTEB-Code / FollowIR; table from the Qwen reranker card, top-100 candidates from Qwen3-Embedding-0.6B):

| Model | Size | MTEB-R | CMTEB-R | MMTEB-R | MLDR | MTEB-Code | FollowIR |
|---|---|---|---|---|---|---|---|
| **Qwen3-Reranker-0.6B** | 0.6 B | **65.80** | 71.31 | **66.36** | **67.28** | **73.42** | **5.41** |
| gte-multilingual-reranker-base | 0.3 B | 59.51 | **74.08** | 59.44 | 66.33 | 54.18 | −1.64 |
| Jina-multilingual-reranker-v2-base | 0.3 B | 58.22 | 63.37 | 63.73 | 39.66 | 58.98 | −0.68 |
| BGE-reranker-v2-m3 | 0.6 B | 57.03 | 72.16 | 58.36 | 59.51 | 41.38 | −0.01 |

Source: [Qwen3-Reranker-0.6B model card → Evaluation](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B).

**Decision:** **Qwen3-Reranker-0.6B.** It leads every non-Chinese benchmark by a wide margin, is instruction-aware, 32K ctx, Apache-2.0, and the llama.cpp org ships an official GGUF for it (see §3). Q8 GGUF = **568 MB**.
- If a *simpler*, longer-battle-tested llama.cpp rerank path is preferred, **BGE-reranker-v2-m3** (0.6 B) is explicitly supported by llama.cpp's rerank endpoint (see §3, PR #9510), at a ~9-point MTEB-R cost.
- How it scores: Qwen3-Reranker is a *decoder LM* reranker — score = softmax probability of "yes" over the last-token logits with a special prompt template (system judge prompt + `<Instruct>/<Query>/<Document>`), not a BERT-style cross-encoder. This matters for the serving path (§3).

---

## 3. Serving path — what actually runs on ROCm + NVIDIA here

### 3.1 llama.cpp is the winner for both models — and it is already on this box

Local state verified:

- `/home/mrc/src/llama-cpp-upstream` is master `b75ecd1` (2026-08-17), built with **GGML_HIP=ON / GGML_CUDA=OFF** (i.e. ROCm only; the GRE is the active AMD GPU — `rocminfo` present, `rocm-smi` sees 16 GB VRAM). Build outputs include `llama-server`, `llama-embedding`, `llama-retrieval`.
- The server already exposes the embedding + rerank routes: `POST /v1/embeddings`, `/embeddings`, `/embedding` (legacy) and `POST /v1/rerank`, `/v1/reranking`, `/rerank`, `/reranking` (`tools/server/server.cpp:252-258`).
- `llama-server --help` shows `--embedding, --embeddings`, `--pooling {none,mean,cls,last,rank}`, `--embd-normalize N` (default 2 = L2). The old `GGML_EMBEDDINGS` CMake gate is gone — embeddings are always compiled in.
- Rerank support is native, not a hack: `LLAMA_POOLING_TYPE_RANK` builds a classification head in the graph; for QWEN3/QWEN3VL arch it uses **last-token** pooling then applies the head and a softmax — i.e. exactly the Qwen3-Reranker "yes/no" scoring (`src/llama-graph.cpp:299,3601-3647`). Score = `embd[0]` (`tools/server/server-context.cpp:2130-2158`).
- Server-side rerank requires `--embedding --pooling rank` and warns if the vocab lacks BOS/EOS/SEP/rerank-template (`common/common.cpp:1463-1480`); documented in `tools/server/README.md:704-707` (example given: bge-reranker-v2-m3). The feature was merged upstream in llama.cpp PR [#9510](https://github.com/ggml-org/llama.cpp/pull/9510) (Sep 2024).

**First-party GGUFs (both official):**

| Model | GGUF | Files / sizes | Source |
|---|---|---|---|
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B-GGUF` | `Qwen3-Embedding-0.6B-Q8_0.gguf` **568 MB**; `-f16.gguf` 1.12 GB; arch `qwen3`, 32K ctx | [repo](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF); [README → llama.cpp usage](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/raw/main/README.md) |
| Qwen3-Reranker-0.6B | `ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF` | `qwen3-reranker-0.6b-q8_0.gguf` **568 MB**; arch `qwen3`, 40 960 ctx; tagged `llama-cpp` | [repo](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF) |

**Exact serving commands** (from the Qwen GGUF README, with the rerank variant from llama.cpp docs):

```bash
# Embedding server (OpenAI-compatible /v1/embeddings)
./build/bin/llama-server -m Qwen3-Embedding-0.6B-Q8_0.gguf \
    --embedding --pooling last -ub 8192 --port 8081

# Rerank server (same binary, second port)
./build/bin/llama-server -m qwen3-reranker-0.6b-q8_0.gguf \
    --embedding --pooling rank --port 8082
```

Notes:
- `--pooling last` is **required** for Qwen3-Embedding (last-token pooling, matching the reference implementation in the Qwen README's `last_token_pool`).
- The embedding server insists embeddings be computed in one ubatch — keep `-ub` large (Qwen's README uses 8192; the server logs a warning if `n_batch > n_ubatch`).
- The **client must apply the query instruction prefix** `Instruct: <task>\nQuery: <text>` for queries (docs need no prefix). Skipping it costs ~1–5% retrieval (Qwen card). ggml-org's reranker GGUF may rely on a `rerank` chat template stored in the GGUF for prompt formatting — confirm at integration time; if quality looks off, fall back to the Transformers yes/no path (below).
- Because this build is ROCm-only, everything lands on the **GRE**. If GRE VRAM is contended by the running qwen38 (currently ~15.2/16 GB used), the 0.6B Q8 models run comfortably on **CPU** (`-ngl 0`) — a 568 MB Q8 model embeds ~dozens of ms/token, fine for doc indexing and top-k rerank. The **RTX 3070** (~2.2 GB free right now) is NOT usable by this HIP build; to use it you'd rebuild llama.cpp with `GGML_CUDA=ON` (driver 610.43/CUDA 13.3 is present) — an option, not a requirement.

### 3.2 Why not sentence-transformers / ONNX / vLLM / TEI

| Option | Verdict for this box |
|---|---|
| **sentence-transformers** | Correct reference path for the *reranker's* yes/no scoring, and usable on CUDA (3070) or ROCm (`/home/mrc/rocm_venv` exists). But it drags in full PyTorch (~2–4 GB RAM), needs `trust_remote_code`-style handling, and adds a second, different serving stack next to llama.cpp. Keep as **fallback** only if llama.cpp rerank template fidelity is a problem. |
| **ONNX Runtime** | No benefit here; you'd hand-roll the Qwen3 last-token pooling + yes/no head logic, and ORT's ROCm EP is more setup than the working llama.cpp path. |
| **vLLM (vllm-rocm)** | vLLM ≥ 0.8.5 supports `task="embed"` and rerank, and `/home/mrc/vllm-rocm*` exists — but a 0.6B model does not justify a ~4+ GB serving runtime vs. a 570 MB llama.cpp binary. |
| **TEI (text-embeddings-inference)** | Great NVIDIA path (and CPU container), but TEI has no first-class ROCm build; not worth it when llama.cpp already works. |
| **Ollama / LM Studio** | Fine, but they are wrappers around llama.cpp anyway and add another process/port to manage. |

**Bottom line:** serve **both** embedding and rerank from the existing ROCm llama.cpp binary. One code path, OpenAI + Jina/TEI-shaped APIs, ~1 GB VRAM total.

---

## 4. Retrieval → context flow (into the 32K-context qwen38)

1. **Index:** chunk docs (512–1024 tokens, ~10% overlap; chunk size matches typical qwen38 context budget) → `POST /v1/embeddings` (llama.cpp, `--pooling last`, 1024-dim) → store.
2. **Store (pick one):**
   - **sqlite-vec** — SQLite extension, in-process, transactional, zero extra runtime. 1024-dim float32 vector = 4 KB/chunk (100k chunks ≈ 400 MB). Recommended default for a RAM-frugal single-user box. *(Primary source: sqlite-vec project.)*
   - **FAISS** — fastest ANN, but in-memory + manual persistence; pick only if the corpus grows past ~1 M chunks.
   - **Chroma** — easiest managed API and persistence, but it's a heavier runtime (its own server/client, ~300 MB+ deps). Comfort over frugality.
3. **Retrieve:** embed the query (with `Instruct: ...\nQuery: ...` prefix) → ANN top-k (e.g. 50).
4. **Rerank:** `POST /v1/rerank` with query + top-50 docs → take top 3–8 → these are the context.
5. **Stuff:** insert the reranked chunks (with source labels) into the qwen38 prompt under the 32K budget (chunk budget ≈ 8192 ctx model budget minus system/tool overhead).

---

## 5. Footprint of the recommended stack (rough, verified sizes)

| Item | Disk | VRAM (GRE) | System RAM |
|---|---|---|---|
| Qwen3-Embedding-0.6B-Q8_0.gguf | 568 MB | ~0.6 GB weights (+ small KV/batch) | process overhead ~1 GB |
| Qwen3-Reranker-0.6B-Q8_0.gguf | 568 MB | ~0.6 GB weights | process overhead ~1 GB |
| sqlite-vec + index (100k × 1024-dim) | ~500 MB | — | ~0.4–0.5 GB |
| **Total incremental** | **~1.1 GB** | **~1.3–2 GB** | **~1.5–2 GB** |

Fit check: GRE 16 GB currently ~15.2 GB used → either free ~2 GB on the GRE, run `-ngl 0` (CPU) for one or both, or rebuild llama.cpp with `GGML_CUDA=ON` and put one model on the 3070 (2.2 GB free). All three models are small enough that the choice is ergonomics, not physics.

Licensing: both models Apache-2.0; bge-m3 MIT; nomic/arctic Apache-2.0 — no restrictions on local RAG use.

---

## Sources (primary only)

- Qwen3-Embedding-0.6B model card (MTEB Multilingual / Eng v2 / C-MTEB tables): https://huggingface.co/Qwen/Qwen3-Embedding-0.6B
- Qwen3-Reranker-0.6B model card (reranker eval table): https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Official GGUF repos + llama.cpp usage: https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF · https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF
- Qwen3-Embedding GitHub README (usage, last-token pooling, rerank yes/no method): https://github.com/QwenLM/Qwen3-Embedding
- llama.cpp PR #9510 (rerank support, pooling rank): https://github.com/ggml-org/llama.cpp/pull/9510
- llama.cpp local source (built master b75ecd1): `tools/server/README.md`, `tools/server/server.cpp`, `tools/server/server-context.cpp`, `src/llama-graph.cpp`, `common/common.cpp`
- Model cards: https://huggingface.co/BAAI/bge-small-en-v1.5 · https://huggingface.co/BAAI/bge-m3 · https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 · https://huggingface.co/thenlper/gte-small · https://huggingface.co/Snowflake/snowflake-arctic-embed-m
- Local env: `nvidia-smi` (3070, ~2.2 GB free), `rocm-smi` (GRE 16 GB), `/home/mrc/src/llama-cpp-upstream/build/CMakeCache.txt` (HIP=ON), `/home/mrc/models` (no embedding models present yet).

**Open items to validate at integration time** (not blockers): (a) whether the ggml-org reranker GGUF carries a `rerank` chat template and its scoring fidelity vs. the Transformers reference; (b) GRE VRAM headroom at deploy time; (c) chunk-size calibration against the qwen38 32K budget.
