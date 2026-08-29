# Qwen3.8-27B serving — proper configuration test (2026-08-29)

Prompt for this test: repeated agent-session failures raised the question
whether the *serving configuration* was ever actually validated, or merely
assumed. Answer: the config was mostly right, the **eval suite had a bug**,
and one principled change was made (KV q4_0 → q8_0).

## 1. The eval suite was broken, not the model

`qwen38-eval/eval.py` (4th category, added 2026-08-28) scored `tool-call 0/10`
in every run — including runs stored in `eval-results.txt` before any of the
2026-08-29 changes. Root cause: **`eval.py` never imported `re`**; every
tool-call case hit `NameError` inside its `try/except Exception` and was
scored FAIL despite byte-correct output. The category was structurally
un-passable since it was written. QWEN.md's "10/10 tool-calling" claim
predates the category and referred to `proto-tool` (native tools=[] API),
which always passed.

Fix: `import re` added. The suite is now 4 categories / 35 checks.

## 2. Corrected baseline (q4_0 KV, the config as-found)

- tool-call 10/10 · proto-tool 10/10 · canary 5/5 · digits 10/10 — **35/35**
- Needle recall (10 codewords in 38.7K-token haystack): **10/10** (prefill 143 s ≈ 270 tok/s)
- Generation speed: **5.1 tok/s**

## 3. A/B — KV cache q4_0 → q8_0 (one variable)

Rationale: with `--no-kv-offload` the KV lives in system RAM, where capacity
is free (3 GiB @ 96K q8 vs 1.5 GiB q4). q4 was saving RAM nobody needed to
save while stacking a second quantization penalty on an already-Q3_K_XL model.

| metric | q4_0 | q8_0 |
|---|---|---|
| eval suite | 35/35 | 35/35 |
| needle @ 38.7K | 10/10 | 10/10 |
| generation | 5.1 tok/s | 4.5 tok/s (−12%) |

**Decision: keep q8_0** (drop-in `~/.config/systemd/user/qwen38-serve.service.d/kv-q8.conf`).
No measurable quality delta at 38K, but the probes saturate — at the 60–90K
contexts real agent sessions reach, KV-quant degradation is exactly where it
would appear, and 0.6 tok/s is noise at these speeds.

## 4. Findings that stand

- Prefill, not decode, is the wall: ~270 tok/s means a 70K session re-prefill
  costs ~4 minutes. The CLI's cache-busting fetches (best practice:
  cache-bust ON, per the dashboard finding) interact with this — prefix-cache
  hits are the difference between seconds and minutes per turn.
- `--spec-type ngram-simple`, `--ctx-checkpoints 4`, flash-attn on ROCm,
  eval-matched sampling: all retained — exonerated by 35/35 + 10/10 needle.
- The model's contract-level competence (tool calling, injection refusal,
  exact-number extraction, long-context recall) is **solid at this config**.
  The recurring agent-session failures are agentic-persistence failures, not
  contract failures — that distinction is now measured, not assumed.
