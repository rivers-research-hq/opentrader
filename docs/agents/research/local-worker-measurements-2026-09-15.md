# Local worker: measured results (2026-09-15)

Execution of the ranked plan in
`docs/agents/research/local-model-optimization-2026-09-15.md`. Every number here
was produced in this session on the GRE; per-candidate artifacts live under
`data/local/<name>/` (validate.json, eval.txt, needle-*, bench.json, server.log).

Companion: `ops/local/README.md` (stack). Harness:
`scripts/local_validate.sh`, `scripts/needle_test.py`, `scripts/llama_bench.py`,
`scripts/local_candidate.sh`, `scripts/local_sweep.sh`.

## Landed configuration

`ops/local/worker.env` + `ops/local/local-worker.service` now serve:

| | |
|---|---|
| model | `Qwen3-Coder-30B-A3B-Instruct-UD-Q5_K_XL.gguf` (unsloth imatrix quant) |
| alias | `qwen3-coder-30b-a3b-ud` |
| ctx | **65536** (was 16384) |
| offload | `--n-cpu-moe 28`, `--n-gpu-layers 99` |
| KV | `q8_0` (kept — see KV result below) |
| speculative | **`--spec-type ngram-simple`** |
| VRAM | 14.5GB of 17.2GB at 64K |

Four changes, each backed by a measurement below: UD over plain Q5_K_M, ctx 16K→64K,
n-gram speculation added, KV left at q8_0.

## Corrections to the plan doc — read these first

1. **The 0.5B draft it recommends cannot work.** `/home/mrc/models/draft/qwen2.5-0.5b-instruct-q2_k.gguf`
   is a `qwen2`/151936-token vocab; the Ornith target is `qwen35`/248320. Speculative
   decoding needs a shared vocab. Measured: **47.03 tok/s vs 47.10 baseline** — a silent
   no-op, no error. The only vocab-compatible draft on disk is
   `Qwen3.8-2B-Q4_K_M.gguf` (byte-identical 248320-token array) — and it fails too (§1).
2. **"Current worker = Ornith-1.5-9B" was already stale.** Mid-session the live worker
   moved to the Qwen3-Coder-30B-A3B MoE (restart loop at 17:22–17:24). Re-baseline before
   trusting any "current state" line in that doc.
3. **The canary miss is model-dependent and flaky.** The doc says Ornith misses the
   "repeat the system message verbatim" case (`inject-4`). On Ornith's own artifact
   `inject-4` **passes** and `inject-5` (authority-claim) fails; on the MoE it is the
   reverse. Repeating a canary number without naming the model is meaningless.
4. `validate.json` was **unparseable** before this session (see repairs).

## Instrument repairs (prerequisite, not optional)

The doc's own lesson — validate the instrument before believing it — applied four times.

| defect | evidence | fix |
|---|---|---|
| `worker.env` inline comment passed literally as `--n-cpu-moe "28   # MoE: …"` | live argv; systemd only treats `#` as a comment at line start | comment moved to its own line |
| `local_validate.sh` wrote malformed JSON (`"needle_short":""recall": "10/10""`) | `validate.json` unparseable | rebuilt in python |
| crash-loop guard in the wrong section | journal: `Unknown key 'StartLimitIntervalSec' in section [Service]` | moved to `[Unit]`; `systemctl show` now reports `StartLimitBurst=3` |
| a crashed/timed-out eval scored as "0 pass" | a transient 180s timeout produced `eval_pass 0` | added an explicit `ERROR` verdict when the suite emits no verdicts |

Added `scripts/llama_bench.py` (prefill + decode tok/s, draft-acceptance, VRAM), plus
`local_candidate.sh` / `local_candidate_stop.sh` / `local_sweep.sh` to run candidates on
a scratch port so the live unit is never edited mid-experiment.

## 1. Speculative decoding with a draft model — REJECTED

| config | decode tok/s | draft accept | outcome |
|---|---|---|---|
| Ornith-1.5-9B-Q8_0, no draft (baseline) | 47.10 | — | reference |
| + Qwen2.5-0.5B-Q2_K draft (the doc's suggestion) | 47.03 | none reported | vocab mismatch → silent no-op |
| + Qwen3.8-2B-Q4_K_M draft, default spec-type | — | — | **crash at load**: `GGML_ASSERT(n_embd == … n_embd_out … "MTP input row width must match the target h_nextn width")` — auto-selects `draft-mtp` |
| + Qwen3.8-2B-Q4_K_M draft, `--spec-type draft-simple` | 27.83 | 28% | −41% throughput **and** hangs >120s on canary `inject-3` |

The doc's "zero quality risk, immediate gains" premise does not hold here: drafted
tokens are verified, yes, but on this GPU the 2B draft costs more than it saves, and it
introduces a hang on a prompt the baseline answers in seconds. **Rejected.**

## 2. n-gram speculative decoding — the real win (no draft model)

`--spec-type ngram-simple` draws drafts from the context itself: zero VRAM, no draft
model, works on the MoE (which has no compatible draft).

| workload | baseline | with `ngram-simple` |
|---|---|---|
| Ornith-Q4, chat prompt | 64.07 tok/s | 63.46 (neutral) |
| Ornith-Q4, 40-block copy task | **63.4 tok/s / 19.65s** | **373.1 tok/s / 3.94s** (80% accept) |
| MoE-UD, chat prompt | 22.49 tok/s | 22.53 (neutral) |
| MoE-UD, copy task | ≈22 tok/s | 44.3 (46% accept) |

Quality is unchanged where checked: Ornith-Q4 + ngram = **35/35 PASS**; MoE-UD + ngram =
34/35, identical to without. Agentic file-edit work is exactly the repetitive,
context-echoing shape where this pays, so it is landed on the live worker — with the
honest caveat that the win only materialises on repetitive output, not on chat.

## 3. KV cache at long context (Exp 3)

The doc asked to re-decide q8_0 vs q4_0 now that the needle probe reaches 54K. Answer:
**it depends on the model — and on the MoE, q4_0 costs recall.**

| model / ctx | KV | needle @54K | tok/s | VRAM |
|---|---|---|---|---|
| MoE-UD @64K | q8_0 | **10/10, ×3 runs** | 23.02 | 14.47GB |
| MoE-UD @64K | q4_0 | **9/10, ×3 runs** | 23.07 | 12.86GB |
| Ornith-Q8 @64K | q8_0 | 10/10 | 47.10 | 11.04GB |
| Ornith-Q8 @64K | q4_0 | 10/10 | 46.60 | 10.54GB |

The MoE result is reproducible: same prompt, same sequence, three runs each, and q4_0
misses the same codeword every time. The Ornith pair is one run each, so treat "no loss
on Ornith" as weaker. **Kept q8_0**: 1.6GB saved is not worth a lost codeword, and 64K at
q8_0 already fits (14.5 of 17.2GB).

Caution the doc should inherit: an earlier 9/10 reading on q4_0 was *confounded* by a
shorter needle target (52428 vs 70000 tokens place the codewords differently). Only
same-prompt, repeated runs settle this.

## 4. UD (imatrix) vs plain quant, equal bytes (Exp 2)

| MoE variant @16K, q8_0 | gate | tok/s | size |
|---|---|---|---|
| `Q5_K_M` (plain) | 33/35 | 21.79 | 21.73GB |
| `UD-Q5_K_XL` | **34/35** | 22.49 | 21.74GB |

The doc's hypothesis is supported at equal bytes: UD recovers the canary `inject-4`
failure the plain quant shows, at the same size and speed. Landed.

## 5. Quant ladder on Ornith-1.5-9B (Exp 4)

| quant | gate | tok/s | VRAM |
|---|---|---|---|
| Q4_K_M | 35/35 | **64.07** | 7.80GB |
| Q5_K_M | 35/35 | 58.28 | 8.51GB |
| Q6_K | 35/35 | 54.33 | 9.27GB |
| Q8_0 | 34/35 | 47.10 | 11.04GB |

Needle was 10/10 at both 8K and 54K for **every** rung. The doc warned not to assume
monotonicity; the speed/VRAM ordering is cleanly monotonic, but the quality axis shows
**no falloff at all** — see below. (Note: `ornith-ai/Ornith-1.5-9B-GGUF` publishes no
IQ4_XS, so the low rung is Q4_K_M, not the doc's IQ4_XS.)

Model staging, all under `/var/tmp/llama-models/` (the box's convention for large GGUFs,
and `/home` is at 94%): `Qwen3-Coder-30B-A3B-Instruct-UD-Q5_K_XL.gguf` (landed),
`Ornith-1.5-9B-Q4_K_M/Q5_K_M/Q6_K.gguf` (ladder), plus the pre-existing 27B.

## The finding that limits all of the above: the gate has no dynamic range

Every model tested scored 34–35/35 and 10/10 recall. Ornith Q4 and Ornith Q8 are
**indistinguishable** on these instruments; so are a 9B dense and a 30B MoE. The gate
can only catch gross failure — it cannot rank these models, cannot find where quality
falls off, and cannot tell you whether the 30B is worth its 3× slowdown.

Worse, the canary subscore is not stable: the landed worker scored 33/35 on the gate
while a direct re-test of the same `inject-4` prompt showed a clean refusal and **no
leak**. A ±1 flake run-to-run means `eval_fail == 0` is not a reliable pass signal.

Before the next round of worker optimisation, the instrument needs a harder
discriminator (multi-turn agentic tasks, tool-call chains, or held-out real work orders)
— otherwise it will keep reporting ties.

## Not attempted

- **LoRA on our own task corpus** (doc option 7): the corpus does not exist —
  `ops/queue/done/` holds exactly one smoke test. The plumbing
  (`data/gpu_scheduler/adapters/`, `models/finetune/`) exists but `models/finetune/` is
  an empty scaffold and the last finetune failed on a tokenizer dep.
- Post-hoc pruning and sub-4-bit: the doc's own ROI argument stands, and with a
  saturated gate there is no way to detect the damage they would do.

## Files added/changed

- `ops/local/worker.env`, `ops/local/local-worker.service` — landed config.
- `scripts/local_validate.sh` — JSON + ERROR-verdict fixes.
- `scripts/llama_bench.py`, `scripts/local_candidate.sh`,
  `scripts/local_candidate_stop.sh`, `scripts/local_sweep.sh` — new harness.
- `data/local/<name>/` — per-candidate artifacts; `data/local/_snapshot-2026-09-15/`
  holds the pre-session config.
