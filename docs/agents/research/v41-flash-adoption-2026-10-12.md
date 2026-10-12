# DeepSeek-V4.1-Flash (arXiv:2609.19969) — read-up and adoption map for this house

- **Date:** 2026-10-12 · **Status:** research input; opens no gate
- **Source:** full 51-page paper read (pdf fetched this session); release note `api-docs.deepseek.com/news/news260910`
- **Why it matters here:** the user flagged DeltaNet (our served Qwen3.6's linear-attention
  hybrid) as archaic and asked what of this paper we can implement.

## 1. What the paper actually does (verified claims, not video recall)

552B-backbone MoE, 1M context, trained on 45T tokens. Three compression axes multiply:

1. **CED (Causal Encoder-Decoder)** — 20-layer encoder + 20-layer decoder. The decoder's
   global KV is **projected from the encoder's final hidden state** (layer-dependent W_KV^l,
   W_Z^l), not from each decoder layer's own hidden state. Prefill complexity drops from
   O(N·L) to ≈O(N·L/2): prompt tokens only run the encoder for global KV. Activates 8B
   params/token in prefill vs 16B in decode — built for input-heavy agent workloads.
2. **CSA2 (Compressed Sparse Attention 2)** — replaces V4's CSA/HCA hybrid with pure CSA2.
   Three statically assigned modes per layer: **Full** (own main KV + indexer + Top-K),
   **Reindex** (reuse main KV + indexer K; own indexer Q → fresh Top-K), **Reuse** (reuse
   main KV AND Top-K indices; attention only). Every layer keeps its own queries and SWA KV.
   Simplifications vs CSA: no overlapping compression windows, no absolute positional
   embedding in compression, indexer K projected from main KV (not a separate path).
   Result: global KV = **890 bytes/token** — 1/4 of V4-Flash, 1/437 of V1.
3. **Hierarchical Sparse Indexer** (decoder only): the first Full-mode layer scores the full
   visible context, then selects 2,048 blocks × 8 positions = **16,384 candidate positions**;
   later Reindex-mode indexers score **only within that pool** → per-query indexer cost is
   constant in context length (only the first layer scans everything).
4. **FP4 main KV (QAT)** — MXFP4-family (E2M1 + one E4M3 scale per 16 channels, no second
   global scale), quantized **after RoPE**; dequantize before attention so no native FP4 matmul
   is needed. FP8 retained for SWA KV (it's quantization-sensitive). Cache quantized
   post-training only (QAT during the post-train phase).
5. **SWA Bounded Replay** — the deployment trick. Don't persist SWA KV at all: global KV is
   persisted (72h, SSD/host); SWA KV lives in a minutes-TTL host-RAM pool (10% of DRAM). On a
   SWA miss, **replay only the last n_win=128 tokens** instead of the exact L×n_win replay —
   approximate but measured-negligible. This is what takes persistent KV to 1/8. The paper
   frames it as a new storage↔computation trade-off: "turns a catastrophic miss into a
   graceful, inexpensive degradation."
6. **Single-Pass mHC** — shift the input-mixing coefficients one block back so the residual
   update, input mixing, and coefficient prediction fuse into one kernel (Mega-mHC) at the
   theoretical (n+1)d memory-traffic bound. Pure deployment kernel work.
7. **DSpark** — speculative decoding: 3-block drafter, one forward pass drafts 5 positions
   semi-autoregressively with a Markov head, a confidence head predicts per-position
   acceptance, and a scheduler picks verification length from measured engine throughput.
   Trained in a dedicated post-pretrain stage, backbone frozen.
8. **Reasoning-effort knob** (§5.1.4) — a scalar b∈[1,100] trained into the model via RL with
   an exponential length penalty (k(b) = k₀·exp(−(b−b_min)/τ)). At deployment it's a
   cost-quality dial: API tiers low/high/max = b 50/75/100. Effort 60–80 recovers most of
   max-effort accuracy at <half the tokens.
9. **Post-training finding** (their words): "the marginal return of engineering the data and
   environment pipeline substantially exceeds that of algorithmic novelty in post-training."
   No new RL algorithms — scale + verifiability of synthesized tasks did all the work.
10. **Multi-agent** (Agent Team mode): multi-agent beats single-agent at every wall-clock
    deadline tested, with a derived-latency penalty (critical path of the collaboration DAG)
    in the reward.

## 2. What we CANNOT adopt (and why — stated so nobody re-derives it)

- **CED/CSA2/Engram/FP4-QAT as architectures**: these require a model pretrained with them
  (CSA2 layers carry indexer/compressor projections; Engram is 196B of hash tables). You
  cannot bolt them onto Qwen3.6's weights. 552B backbone ≈ 276GB at FP4 — never fits the
  16GB GRE even when community GGUFs appear. Serving V4.1-Flash here is off the table.
- **"Implementing DeltaNet's replacement"**: the honest reading is that DeepSeek itself has
  moved OFF linear-attention hybrids — V4.1-Flash's backbone is pure attention (CSA2+SWA)
  with compression doing the linear-attention's job via the KV-cache axis. Adoption on our
  side means *serving a model trained that way*, which doesn't exist at our scale yet.

## 3. What we CAN adopt — mapped to our stack, with status

| Paper piece | Our analog | Status |
|---|---|---|
| KV quantized after RoPE (FP4-class) | q4_0 KV on the GRE lane; llama.cpp quantizes cache post-RoPE | **already equivalent-class** |
| Persistent global KV / cheap SWA reconstruction | Router lane: weights resident (TTL 7200) so a dispatch never eats a cold reload; `--cache-reuse 256` for prefix reuse | **already implemented** (this is our bounded-replay analog: the catastrophic miss we avoid is the 17GB weight reload) |
| Reasoning-effort knob (low/high/max tiers) | Dispatch card effort tiers: mechanical cards = thinking OFF + tight budget; hard cards = thinking ON + large budget; very hard = thinking + multi-sample | **implementing now** (§4 below) |
| DSpark speculative decoding | llama.cpp `--model-draft` with a small draft; same family (draft → verify), simpler scheduling | **proposed experiment** — needs a ~400–500MB draft GGUF (announce before pulling) and a measured A/B on the GRE; paper's own rule: measure before designing around it |
| 8B-reads/16B-writes asymmetry | Our four-stage protocol: cheap CPU verifier reads, expensive GPU worker writes | **already implemented** (this session) |
| "Data pipeline > algorithmic novelty" | The house's own falsification-first discipline (ADR-0007: probes beat vibes; PIT-DATA sells provenance) | **already our doctrine** — nice external confirmation |
| Derived-latency penalty in multi-agent reward | Our orchestration costs real tokens; the DAG-critical-path *measurement* (not reward) is implementable as a dispatch-lane metric | candidate, low priority |
| DSec sandbox containment (AppArmor per-sandbox, eBPF nets, repercussion signals) | Our sandbox lane already has unprivileged-agent-isolation work (#288/#291 line) | the paper validates the direction; our tickets cover it |

## 4. Implementation this session: reasoning-effort tiers (paper §5.1.4 → our lane)

Concrete adoption of their scalar-effort idea, minus the RL (we can't train; we can
*schedule*). The dispatch lane gains an effort contract on every card:

- **`low`** (their b=50 analog): thinking OFF, ≤8k output — mechanical translations, doc
  edits, single-file slices. Cheapest path.
- **`high`** (b=75 analog): thinking ON, ≤16k output — multi-constraint implementation cards
  where the reasoning trace pays for itself.
- **`max`** (b=100 analog): thinking ON, ≥24k budget or N samples + verifier gate — reserved
  for the hardest cards; the paper's own data shows the last step (80→100) costs 1.6–1.8×
  tokens for marginal accuracy.

Card format gains `EFFORT: low|high|max`; the dispatcher maps it to
`chat_template_kwargs.enable_thinking` + `max_tokens` + retry policy. Defaults: `low`
(everything dispatched so far this session has been low-effort work and succeeded —
consistent with the paper's front-loaded gains).

## 5. Standing watch item

The release note commits to "work closely with the open-source community on V4.1-Flash
inference support." If a CED-class model ships at ≤16GB (a distilled small CED), it becomes
a candidate worker for this stack and THEN the architecture migration is real. Until then,
the honest stack is: Qwen3.6-35B (worker) + the paper's inference patterns (cache policy,
effort knob, spec-decode experiment) — not the architecture itself.
