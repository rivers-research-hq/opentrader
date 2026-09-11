# CB-speech Warden fine-tune — offline eval (gate 1) — 2026-09-11

**Verdict: NO-GO.** The QLoRA fine-tune does **not** improve the Warden; the
thesis (CB-speech language → 5d FX direction) fails to generalize out-of-sample.

## What was trained

- Base: `ibm-granite/granite-4.2-8b` (the live Warden, Q4_K_M GGUF on :5802).
- QLoRA: NF4, r=8, alpha=8, targets q/k/v/o/gate/up/down_proj, lr 2e-4, 1 epoch.
- Temporal split (GLM plan §5): **train ≤2022 (739), val 2023-24 (215),
  test ≥2025 (246)**. The first training run consumed the full corpus incl.
  2025-26 — a leak — and was discarded (commit 2225163 adds `--year-lt`).
- Deploy artifact: `warden-cbft1` LoRA merged at serve-time via
  `data/models/finetune/warden-cbft1.gguf` (scale 1.0), served as
  `warden-4.2-8b-cbft1` on :5803. Provenance in
  `data/models/finetune/warden-cbft1/training_meta.json` (train_loss 1.244).

## Gate 1 — offline holdout, test window (≥2025, 246 docs)

| metric | base (:5802) | tuned (:5803) |
|---|---|---|
| JSON contract compliance | 246/246 = **100.00%** | 241/246 = **97.97%** |
| grounding (no invented %) | 240/246 = 97.56% | 203/241 = 84.23% |
| **directional hit-rate (sign vs +5d)** | 20/246 = **8.13%** | 88/241 = **36.51%** |
| policy-replay score sum | −40.751 | −67.588 |

- Base's 8.13% is the "honest abstain" baseline: it defaults to `flat`/0.0 and
  only hits when the 5d return is near zero.
- Tuned commits to a direction, but is **below the 50% chance line**
  (36.51% ≈ 4.2σ below 50%, n=241) — i.e. anti-predictive. Its directions are
  reliably inverted out-of-sample.
- Policy replay (gate 2 proxy) is *worse* than base (−67.6 vs −40.8), so the
  fine-tune degrades expectation quality, not improves it.

## Interpretation

The label sign conventions are correct (verified: GBP/USD·EUR/USD·AUD/USD long =
long base currency; USD/JPY short = long JPY; FED uses the DXY basket with
correct exponent signs). So the anti-correlation is not a labeling bug — it is
the plan's §8 nonstationarity risk materializing: the ≤2022 speech→direction
mapping does not transfer to 2025-26.

Per the plan §6 ("where 'better interpretation' must show up as expectation
quality, or the thesis is dead") and the ToC entry (`V-CBFT`, `[explore]`),
the benefit claim stays **unproven**; no promotion to `[known]`.

## Consequences

- **No shadow (gate 3) and no `:5802` swap (gate 4).** The tuned server on
  :5803 is torn down; the live Warden stays on the un-tuned Granite Q4_K_M.
- The parser hardening landed anyway (useful regardless): `fx_warden._extract_json`
  and `scripts/eval_cbspeech.py` now tolerate Granite's leaked `</think>` tag +
  duplicated answer (commits 8b9f753, 201f8eb).
- The harness/scripts (train/eval/label/harvest + temporal-split guard) are
  retained as reusable infrastructure for a future round with a better label
  or a different base model.

## Reproduce

```
.venv/bin/python3 scripts/eval_cbspeech.py \
  --holdout /home/mrc/opentrader-data/feeds/cbspeeches/corpus_labeled.jsonl \
  --port 5802 --year-ge 2025      # base
# ... --port 5803                 # tuned (before teardown)
```
