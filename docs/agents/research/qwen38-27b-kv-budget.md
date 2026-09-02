# Qwen3.8-27B VRAM / KV-cache budget (RX 7900 GRE, ROCm gfx1100)

Research note for the llama.cpp serving ticket. Goal: compute the real VRAM
budget so the next session can set correct `llama-server` flags, instead of
OOMing the box the way the vLLM attempt did.

> **Headline finding:** the naive KV formula in the ticket
> (`2 × num_hidden_layers × num_key_value_heads × head_dim`) **overestimates KV
> cache by 4×** for this model. Qwen3.8-27B is a **hybrid** architecture where
> only **16 of 64 layers** are full attention (with a growing KV cache). The
> other **48 layers** are Gated DeltaNet linear-attention layers that carry a
> *fixed-size* recurrent state, not a per-token KV cache. Everything below is
> computed on this basis.

---

## Architecture

Primary source — `config.json`:
https://huggingface.co/Qwen/Qwen3.8-27B/raw/main/config.json

The model is a Qwen3.5-family hybrid (linear attention + full attention), dense,
native vision-language. Relevant `text_config` values (exact JSON):

| Key | Value | Meaning |
|---|---|---|
| `model_type` | `"qwen3_5"` | hybrid DeltaNet architecture |
| `num_hidden_layers` | `64` | total decoder layers |
| `num_attention_heads` | `24` | query heads (full-attn layers) |
| `num_key_value_heads` | `4` | KV heads (full-attn layers) |
| `head_dim` | `256` | full-attn head dim |
| `hidden_size` | `5120` | model width |
| `full_attention_interval` | `4` | every 4th layer is full attention |
| `linear_num_key_heads` | `16` | DeltaNet key heads |
| `linear_key_head_dim` | `128` | DeltaNet key head dim |
| `linear_num_value_heads` | `48` | DeltaNet value heads |
| `linear_value_head_dim` | `128` | DeltaNet value head dim |
| `linear_conv_kernel_dim` | `4` | DeltaNet conv kernel |
| `mtp_num_hidden_layers` | `1` | MTP (speculative decode) block |
| `max_position_embeddings` | `262144` | native context = 256K |
| `num_experts` / `num_experts_per_tok` | *(absent)* | **dense**, not MoE |

- **GQA ratio** (full-attn layers): `num_attention_heads / num_key_value_heads`
  = 24 / 4 = **6:1**.
- **Dense vs MoE:** dense. No `num_experts` key in `text_config`; the README
  describes it as a "compact, deployment-friendly dense model". (The 2.4T-A95B
  sibling is the MoE one.)
- **Hybrid layout:** `layer_types` is a 64-entry array that repeats
  `linear_attention, linear_attention, linear_attention, full_attention` 16
  times → **48 linear-attention layers + 16 full-attention layers**. Confirmed
  by `full_attention_interval: 4` and the unsloth README's "Hidden Layout:
  16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))".
- **Native context length:** `262144` (256K); extensible to 1M via YaRN.
  Unsloth README confirms "Context Length: 262,144 natively and extensible up
  to 1,000,000 tokens".

Source: https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/raw/main/README.md

---

## KV-cache math

Only the **16 full-attention layers** have a KV cache. The 48 DeltaNet layers
keep a fixed recurrent state (see below), which does *not* scale with context.

### Full-attention KV cache, per token

Formula (corrected for hybrid): `2 × 16 × num_key_value_heads × head_dim × bytes_per_element`

- Full-attn layers: `16`
- `num_key_value_heads`: `4`
- `head_dim`: `256`
- elements/token = `2 × 16 × 4 × 256 = 32768`

| dtype | bytes/elem | bytes/token | per 1024 tokens |
|---|---|---|---|
| q8_0 | 1.0 | **32768 B = 32 KiB** | 32 MiB |
| q4_0 | 0.5 | **16384 B = 16 KiB** | 16 MiB |
| f16 | 2.0 | **65536 B = 64 KiB** | 64 MiB |

### The naive formula (what the ticket assumed)

`2 × num_hidden_layers × num_key_value_heads × head_dim × bytes/elem`
= `2 × 64 × 4 × 256` = **131072** elements/token → 128 KiB/token @ q8_0.
That is a **4× overestimate**, because it treats all 64 layers as full
attention. Correct figure is 32 KiB/token @ q8_0.

### Gated DeltaNet recurrent state (fixed, not per-token)

From `src/models/qwen35.cpp` in llama.cpp (authoritative):
https://raw.githubusercontent.com/ggml-org/llama.cpp/master/src/models/qwen35.cpp

- `head_v_dim = ssm_d_state = 128` (=`linear_value_head_dim`)
- `num_v_heads = ssm_dt_rank = 48` (=`linear_num_value_heads`)
- state tensor per layer: `head_v_dim × head_v_dim × num_v_heads`
  = `128 × 128 × 48` = **786,432 floats** = 3 MiB/layer @ fp32.
- `mamba_ssm_dtype: "float32"` → state is fp32.
- 48 DeltaNet layers → **≈ 144 MiB** recurrent state per sequence (fp32).
- Plus conv state: `conv_kernel_size(4) × (d_inner(6144) + 2×16×128)`
  ≈ 4 × 10240 = 40,960 floats/layer → ≈ 8 MiB total. Negligible.

Net: ~**0.15 GiB** fixed per sequence for the DeltaNet state, independent of
context length. (Labeled as estimate; exact dtype/rounding may vary slightly.)

---

## VRAM budget table

Inputs:

- **Model weights** = `Qwen3.8-27B-UD-Q3_K_XL.gguf` file size
  = **13,146,393,504 bytes = 12.24 GiB = 12,537 MiB**.
  Source (HF tree API, `lfs.size`):
  https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF/tree/main
- **DeltaNet recurrent state** ≈ 0.15 GiB (152 MiB), fixed.
- **Compute buffer + ROCm/driver/graph overhead** = **assumed 1.0 GiB**
  (stated assumption; range 0.5–1.5 GiB). This covers llama.cpp compute buffer,
  ROCm context, and CUDA-graph allocations.
- **GPU usable** = **16,308 MiB** (RX 7900 GRE 16 GiB minus driver/compositor),
  per ticket.

Total VRAM (MiB) = 12,537 (weights) + 152 (state) + 1,024 (compute) + KV.

| ctx-size | KV q8_0 | KV q4_0 | KV f16 | total q8_0 | total q4_0 | total f16 |
|---|---|---|---|---|---|---|
| 4096 | 128 | 64 | 256 | 13,841 | 13,777 | 13,969 |
| 8192 | 256 | 128 | 512 | 13,969 | 13,841 | 14,225 |
| 16384 | 512 | 256 | 1,024 | 14,225 | 13,969 | 14,737 |
| 32768 | 1,024 | 512 | 2,048 | 14,737 | 14,225 | 15,761 |
| 65536 | 2,048 | 1,024 | 4,096 | 15,761 | 14,737 | 16,681 |

(all values in MiB; usable = 16,308 MiB; table uses nominal weights 12,537 MiB —
actual measured file size is 12,818 MiB, so real totals are ~281 MiB higher)

**Recommended config (2026-08-20, rev 2):** **131072** ctx, `q4_0` KV, `--no-kv-offload` (KV in RAM). KV@128K q4_0 = 2 GiB in RAM (RAM has ~17 GiB free); VRAM = weights(12,818) + state(152) + compute(1024) ≈ 14.0 GiB, ~1.2 GiB headroom. Generation drops to ~10.4 t/s (KV-in-RAM attention reads bottleneck it, vs 14.7 with GPU KV@64K) but server n_ctx doubles, which roughly doubles Qwen Code's client input budget (~52K), fixing forced compactions. Preflight script counts offloaded KV against RAM (RAM gate: avail > 4096 + KV). `f16` KV stays avoided at any large ctx.

---

## Recommended flags

```bash
llama-server \
  --model Qwen3.8-27B-UD-Q3_K_XL.gguf \
  --ctx-size 131072 \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \
  --no-kv-offload \
  --n-gpu-layers -1 \
  --flash-attn on \
  --port 8080
```

- `--n-gpu-layers -1`: full weight offload. 12.5 GiB weights + state + compute
  buffer fit in 16 GiB VRAM (KV no longer counts — it's in RAM).
- `--cache-type-k q4_0` / `--cache-type-v q4_0`: 0.5-byte KV. Combined with
  `--no-kv-offload`, KV goes to system RAM so VRAM only holds weights.
- `--no-kv-offload`: moves the KV cache to system RAM. Frees ~1-2 GiB VRAM and
  uses the idle RAM; costs ~30% generation speed (attention reads KV from RAM).
- `--ctx-size 131072`: server context doubled; Qwen Code's client input budget
  tracks it (~40%), so ~52K usable input. Drop to 98304 for a speed/context
  middle ground.
- `--flash-attn on`: reduces attention workspace for the 16 full-attn layers.
  (Does not shrink the KV cache itself.)

---

## Caveats (llama.cpp arch support)

1. **Hybrid / qwen35 arch.** llama.cpp implements this as `llama_model_qwen35`
   (`src/models/qwen35.cpp`), and the GGUF metadata reports
   `"architecture": "qwen35"`. The KV cache lives only on the 16 full-attention
   layers; the 48 DeltaNet layers use a recurrent state. Source:
   https://raw.githubusercontent.com/ggml-org/llama.cpp/master/src/models/qwen35.cpp
   and the GGUF metadata (`gguf.architecture = "qwen35"`) in
   https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF

2. **MTP / speculative decode.** `mtp_num_hidden_layers: 1`. The main GGUF
   carries MTP layers as extra decoder blocks that are **not executed** in the
   normal decode pass (`"MTP/NextN layers are loaded as extra decoder blocks but
   not executed in the main pass"`). A separate speculative-decode file
   (`MTP/mtp-Qwen3.8-27B-Q4_0.gguf`) is shipped. For text-only serving, do **not**
   enable MTP — it adds VRAM and buys nothing for a single client. Source:
   https://raw.githubusercontent.com/ggml-org/llama.cpp/master/src/models/qwen35.cpp

3. **Vision encoder.** The model is `language_model_only: false`, but the vision
   tower is shipped as a **separate** `mmproj-BF16.gguf` / `mmproj-F16.gguf`
   (~930 MB each). Text-only serving needs **only** the text GGUF
   (`Qwen3.8-27B-UD-Q3_K_XL.gguf`); do not load mmproj, and use `llama-server`
   (not `llama-mtmd-cli`). Source:
   https://huggingface.co/api/models/unsloth/Qwen3.8-27B-GGUF/tree/main

4. **Backend maturity.** qwen35 support is recent in llama.cpp. There is a
   reported Vulkan garbage-output bug at batch size 512 (correct at 1024/4096):
   https://github.com/ggml-org/llama.cpp/issues/27237 — not relevant on ROCm,
   but pin a recent llama.cpp build and avoid exotic batch sizes. Unsloth also
   ships its own fork (`unslothai/llama.cpp`) for the newest Dynamic 3.0 quants.

5. **Dynamic quants.** `UD-` prefix = Unsloth Dynamic 3.0 (imatrix) quants.
   Sizes above are from the HF tree `lfs.size` fields for the exact
   `UD-Q3_K_XL` file; other quants differ (Q4_K_XL = 17.56 GB, Q4_K_M =
   16.46 GB, Q5_K_M = 19.77 GB, Q8_0 = 29.05 GB — the last two will **not** fit
   the 16 GiB GRE fully offloaded).
