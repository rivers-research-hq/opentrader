# CB speech interpreter — Granite fine-tune on FRASER + multi-CB archives

**Date:** 2026-09-10 · **Status:** PROPOSED — human decision pending · **Author:** research/backup agent
**Role context (human, 2026-09-10):** DeepSeek takes over development; this agent is research +
backup coding. Implementation below is sized for the DeepSeek lane; transcription-class steps for
the bounded local lanes per AGENTS.md role division.

---

## 1. Thesis

The Warden sets each lane's weekly `expected_pnl_pct` by conditioning a local model on the
instability table + news digest (incl. central-bank speeches). Its expectation quality is currently
bounded by generic pretraining — the model has no learned prior for what Fed/ECB/BoJ language
*meant* in past market contexts. Fine-tuning Granite 4.2-8B on dated central-bank communications
paired with subsequent FX outcomes should make the news→expectation mapping learnable instead of
guessed.

**FRASER's role:** the St. Louis Fed archive (fraser.stlouisfed.org) is the verified keyless source
for the *historical* Fed corpus. It is a **training-time** input, not a live-lane input — the
inference-time speech flow stays the existing Fed RSS feed in `fetch_event_feeds.py`.

## 2. Current system state (verified 2026-09-10)

- **Primary:** Granite 4.2-8B (`warden-4.2-8b`) on RX 7900 GRE, llama.cpp Vulkan, `:5802`,
  `opentrader-warden-gre.service` — live. Swap rationale + A/B: ToC Q15/Q16.
- **Fallback:** Qwen3.8-4B on RTX 3070, `:5804`, `opentrader-warden-qwen.service` — managed by
  `warden_failover.py` (GPU-eviction tolerant; never fights gaming).
- **Receipts:** every Warden record stamps `_model_id()` — lineage survives swaps. (Known minor
  defect: `fx_warden.py:4` docstring still says "Qwen3.8-4B"; stale.)
- **Corpus shape:** `data/warden/records.jsonl` = {ts, model, mode, instability, headlines,
  news_refs, plan} — the self-supervised mid-train corpus, ~days old. This plan supplies the
  historical augmentation that corpus lacks.

## 3. Source inventory

| Source | Status (2026-09-10) | Notes |
|---|---|---|
| FRASER OAI-PMH | **VERIFIED keyless** | `https://fraser.stlouisfed.org/oai/?verb=...`; MODS v3.5 only; `resumptionToken` paging; `from=` incremental; `ListSets` advertises only `author:*` but unlisted `theme:*` setSpecs work as filters; item records carry `access="raw object"` PDF URLs; occasional HTTP 500 on GetRecord (item:22462 seen) → harvester needs retries |
| Fed speeches RSS | **LIVE in repo** | `fetch_event_feeds.py` (`www.federalreserve.gov/feeds/speeches.xml`, browser UA — 403s plain clients) |
| RBA speeches RSS | **VERIFIED keyless** | `rba.gov.au/rss/rss-cb-speeches.xml` — HTTP 200, RSS1.0/RDF (items are `<item rdf:about>`, not bare `<item>`) |
| BoE speeches page | **VERIFIED reachable** | `bankofengland.co.uk/speeches` — HTTP 200 (301 first hop; follow redirects); needs HTML parse |
| BIS CB speeches DB | **DISCOVERY TASK** | Aggregate speeches from ~all major CBs — highest-value source for the long tail; guessed paths 404'd (`/list/cbspch/`, `/speeches/`, `/speech/`). Find current path |
| ECB speeches | **DISCOVERY TASK** | Data-portal/API path TBD (`data-api.ecb.europa.eu/service/data/SPEECHES` returned 404); RSS path TBD |
| BoJ English speeches | **DISCOVERY TASK** | `boj.or.jp/en/mopp/...` paths 404'd; site is live (ja 404 page served). Find current path |

Priority: Fed first (thesis-critical), then ECB+BoJ (EUR/JPY = lane currencies), then the BIS
aggregate for the long tail (CHF/AUD/CAD/CZK/CNH etc. in the instability table). Per-bank fetchers
follow the `fetch_event_feeds.py` pattern: `guarded_urlopen`, browser UA, write
`<store>/feeds/cbspeeches/<bank>/`.

## 4. Corpus design

**Normalized schema (one JSONL, all banks):**
`{bank, doc_type: speech|minutes|transcript|report, date, decision_vintage_date, speaker, role,
title, text, source_url, harvest_ts}`

**Scope & weighting:**
- Fed: speeches 2007→ (full text), FOMC minutes 1993→, transcripts 1994→ (FRASER + fed.gov).
- ECB/BoJ/BoE/RBA: 2000→. Recent 5 years ×3 weight (language regimes are nonstationary; the
  pre-1990 FRASER material is style-only — **no outcome labels exist** — exclude from supervised
  pairs, may keep as optional style pretraining).
- Language: EN only at first; BoJ/ECCO translations if quality allows.

**Label pairing (the make-or-break step):**
Each doc gets outcome labels from the repo's own FX data and FRED distillates:
- `ret_1d`, `ret_5d` of the doc's base currency vs USD (and vs basket), from decision-vintage
  closes only (doc `date` → next full-session closes; never same-session intraday — leakage).
- Optional auxiliary: hawk/dove tag derived from subsequent 5d direction + stress state, kept as a
  separate column so the primary task stays numeric.
- Conditioning features at doc time: stress snapshot (VIX/HY-OAS/UST10Y/curve z-scores — same
  fields as the instability table) so the model learns *speech × context*, not speech alone.

**Quality gates for the corpus itself:** dedup (same speech re-published), OCR-confidence flag
(scanned pre-1994), date-fidelity check (doc date vs RSS/economic calendar), bank/speaker
normalization. Bounded transcription jobs do PDF→text extraction.

## 5. Training design

- **Base:** Granite 4.2-8B (`warden-4.2-8b` file), **QLoRA** (RTX-class feasible; precedent:
  Ptolemy-1 finetune pipeline under `data/models/finetune/`). Serve via existing llama.cpp
  Vulkan/RADV stack — same service, new adapter merge.
- **Task format:** prompt = {bank tag, doc text, stress snapshot} → output = **the Warden's
  strict-JSON schema** (`regime_read` ≤2 sentences + expectations), so the fine-tuned model is a
  drop-in replacement at `:5802` with zero prompt surgery. Keep the grounding rule ("quote
  verbatim, never compute") in every training example.
- **Split: time-based** — train ≤2022, val 2023–24, test 2025–26 (regime leak is the failure mode;
  never random-split).
- Size: start ~2–5k paired docs (Fed speeches+minutes with clean labels), not the full archive.

## 6. Evaluation gates (all must pass before any swap)

1. **Offline holdout:** base vs tuned on 2025–26 speeches. Metrics: (a) directional hit-rate of
   implied bias vs +5d outcome; (b) JSON contract compliance ≥ base (6/7 bar from Q15); (c)
   grounding integrity (no computed numbers).
2. **Warden-policy replay:** feed holdout docs through the existing score rule
   (`HARSHNESS/PROBATE/ESCALATE`) using tuned vs base expectations; report `score_pct` drift on
   synthetic lane histories. This is where "better interpretation" must show up as
   expectation quality, or the thesis is dead.
3. **Shadow period:** tuned model runs dry alongside live Warden ≥2 tournament weeks, receipts
   distinguish the two (`warden-4.2-8b` vs e.g. `warden-4.2-8b-cbft1`).
4. **Human-gated swap** of `:5802`, then fix the stale `fx_warden.py:4` docstring in the same
   landing.

## 7. Task breakdown (DeepSeek lane unless noted)

| # | Task | Size | Lane |
|---|---|---|---|
| T1 | Source discovery: BIS speeches DB, ECB speeches API/RSS, BoJ EN paths | small | bounded local or DeepSeek |
| T2 | FRASER harvester (OAI-PMH→JSONL, resumptionToken, retry-500, incremental `from=`) | small | DeepSeek |
| T3 | Per-bank fetchers (RSS/HTML/BoJ) into same schema | small | DeepSeek |
| T4 | PDF→text extraction + dedup/date checks | medium | bounded transcription lanes |
| T5 | Label pairing script (FX outcomes + stress snapshot, vintage discipline) | medium | DeepSeek |
| T6 | QLoRA train run + merge | medium | GPU (GRE idle windows; failover must stay intact) |
| T7 | Offline eval + policy replay harness | small | DeepSeek |
| T8 | Shadow wiring + swap | small | DeepSeek + human gate |

Token/resource discipline: corpus extraction is the local model's free-lane work; subscription
tokens go to implementation only. GPU: training must not evict the live Warden or fight gaming
(3070 headroom rule applies).

## 8. Risks / honest boundaries

- **Label quality > corpus size.** A summarizer-grade fine-tune is worthless here; the policy
  replay (gate 2) is the real falsifier.
- **Nonstationarity:** old Fedspeak ≠ today's Fedspeak; weighting + time-split mitigate, not solve.
- **OCR quality** on scanned FRASER items; prefer born-digital (2007+ speeches) for supervised pairs.
- **The benefit claim is `[explore]`** — unproven until gate 2. No promotion to `[known]` without
  the replay evidence, per claims governance.
- **Scope:** FX arm focus (human 2026-09-02) — this is in-scope as Warden improvement; still needs
  the human's go (new training lane, GPU scheduling).

## 9. ToC entry (added this session)

`toc var add V-CBFT --status explore --desc "CB-speech fine-tune of Warden Granite improves
expectation quality; FRASER+multi-CB corpora, policy-replay gate required"` — bounds: offline eval
+ 2-week shadow; no live claim until gate 2 passes.
