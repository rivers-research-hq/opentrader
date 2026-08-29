# RTX 3070 (8GB) & AMD iGPU (16GB) Model Catalog — July 2026

## Trading Model Candidates (RTX 3070, 8GB VRAM — target <6GB at Q4_K_M)

| # | Model | Params | Family | Year | Q4_K_M Est. Size | Reasoning | Source |
|---|-------|--------|--------|------|-------------------|-----------|--------|
| 1 | DeepSeek-R1-0528-Qwen3-8B | 8B | Qwen3 | 2025 | ~5.0 GB | Yes (R1 CoT) | HF: bartowski/deepseek-ai_DeepSeek-R1-0528-Qwen3-8B-GGUF |
| 2 | Qwen3-8B | 8B | Qwen3 | 2025 | ~5.0 GB | No | HF: bartowski/Qwen_Qwen3-8B-GGUF |
| 3 | Qwen3-8B (abliterated) | 8B | Qwen3 | 2025 | ~5.0 GB | No | HF: bartowski/mlabonne_Qwen3-8B-abliterated-GGUF |
| 4 | DeepSeek-R1-Distill-Qwen-7B | 7B | Qwen2.5 | 2025 | ~4.5 GB | Yes (R1 CoT) | HF: bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF |
| 5 | DeepSeek-R1-Distill-Llama-8B | 8B | Llama 3.1 | 2025 | ~5.0 GB | Yes (R1 CoT) | HF: unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF |
| 6 | Qwen2.5-7B-Instruct | 7B | Qwen2.5 | 2024 | ~4.4 GB | No | HF/LOCAL: models/qwen2.5-7b-instruct/ |
| 7 | Qwythos-9B (fine-tune) | 7B→9B | Qwen2.5+LoRA | 2025 | ~5.5 GB | No | RETIRED 2026-08-13 — replaced by DeepSeek-V4-Pro-Qwen3.5-9B (live AMD model) |
| 8 | Hermes-3-Llama-3.1-8B | 8B | Llama 3.1 | 2024 | ~4.6 GB | No | LOCAL: models/hermes-3-llama-3.1-8b/ |
| 9 | Command R7B (12-2024) | 7B | Command R | 2024 | ~4.5 GB | No | HF: bartowski/c4ai-command-r7b-12-2024-GGUF |
| 10 | Command A Reasoning (08-2025) | 7B | Command A | 2025 | ~4.5 GB | Yes (reasoning) | HF: bartowski/CohereLabs_command-a-reasoning-08-2025-GGUF |
| 11 | Phi-4 (14B) | 14B | Phi-4 | 2025 | ~8.0 GB | No | HF: bartowski/phi-4-GGUF |
| 12 | Phi-4-mini-instruct | 3.8B | Phi-4 | 2025 | ~2.5 GB | No | HF: bartowski/microsoft_Phi-4-mini-instruct-GGUF |
| 13 | Phi-4-mini-reasoning | 3.8B | Phi-4 | 2025 | ~2.5 GB | Yes | HF: bartowski/microsoft_Phi-4-mini-reasoning-GGUF |
| 14 | Phi-4-reasoning-plus | 14B | Phi-4 | 2025 | ~8.0 GB | Yes | HF: bartowski/microsoft_Phi-4-reasoning-plus-GGUF |
| 15 | Granite 3.1-8B-Instruct | 8B | Granite | 2025 | ~5.0 GB | No | HF: bartowski/granite-3.1-8b-instruct-GGUF |
| 16 | Granite 3.2-8B-Instruct | 8B | Granite | 2025 | ~5.0 GB | No | HF: bartowski/ibm-granite_granite-3.2-8b-instruct-GGUF |
| 17 | Granite 3.3-8B-Instruct | 8B | Granite | 2026 | ~5.0 GB | No | HF: bartowski/ibm-granite_granite-3.3-8b-instruct-GGUF |
| 18 | InternLM3-8B-Instruct | 8B | InternLM3 | 2025 | ~5.0 GB | No | HF: bartowski/internlm3-8b-instruct-GGUF |
| 19 | OLMo 2-1124-7B-Instruct | 7B | OLMo 2 | 2024 | ~4.5 GB | No | HF: bartowski/OLMo-2-1124-7B-Instruct-GGUF |
| 20 | EXAONE 3.5-7.8B-Instruct | 7.8B | EXAONE | 2025 | ~5.0 GB | No | HF: bartowski/EXAONE-3.5-7.8B-Instruct-GGUF |
| 21 | Dolphin3.0-Llama3.1-8B | 8B | Llama 3.1 | 2025 | ~5.0 GB | No | HF: bartowski/Dolphin3.0-Llama3.1-8B-GGUF |
| 22 | Aya Expanse 8B | 8B | Command R | 2024 | ~5.0 GB | No | HF: bartowski/aya-expanse-8b-GGUF |
| 23 | Qwen3-Coder-Next | 8B? | Qwen3 | 2025 | ~5.0 GB | No | HF: bartowski/Qwen_Qwen3-Coder-Next-GGUF |
| 24 | Mistral-Small-Instruct-2409 | 22B | Mistral | 2024 | ~13 GB | No | HF: bartowski/Mistral-Small-Instruct-2409-GGUF |

## Supervisor Model Candidates (AMD iGPU, 16GB VRAM — target <13GB at Q4_K_M)

**LIVE (2026-08-13):** DeepSeek-V4-Pro-Qwen3.5-9B-MTP Q8_0 (~9.8 GB) — 9B, Qwen3.5 family, 2026. Served on :5802 via `opentrader-llama-gpu1.service`, alias `deepseek-v4-pro-qwen3.5-9b` (legacy alias `qwythos-9b-mtp`). `models/deepseek-v4-pro-qwen3.5-9b/`.

| # | Model | Params | Family | Year | Q4_K_M Est. Size | Context | Source |
|---|-------|--------|--------|------|-------------------|---------|--------|
| 25 | Gemma-4-12B-Agentic | 12B | Gemma 4 | 2026 | ~6.9 GB | 128K | LOCAL: models/gemma-4-12B-agentic-fable5/ |
| 26 | Gemma-3-12B-it | 12B | Gemma 3 | 2025 | ~7.5 GB | 128K | HF: bartowski/google_gemma-3-12b-it-GGUF |
| 27 | Qwen3-14B | 14B | Qwen3 | 2025 | ~8.5 GB | 32K | HF: bartowski/Qwen_Qwen3-14B-GGUF |
| 28 | Qwen3-14B (abliterated) | 14B | Qwen3 | 2025 | ~8.5 GB | 32K | HF: bartowski/mlabonne_Qwen3-14B-abliterated-GGUF |
| 29 | DeepSeek-R1-Distill-Qwen-14B | 14B | Qwen2.5 | 2025 | ~8.5 GB | 32K | HF: unsloth/DeepSeek-R1-Distill-Qwen-14B-GGUF |
| 30 | Qwen3-30B-A3B-Instruct-2507 | 30B MoE (3B active) | Qwen3 MoE | 2025 | ~2.5 GB | 32K | HF: bartowski/Qwen_Qwen3-30B-A3B-Instruct-2507-GGUF |
| 31 | Qwen3-30B-A3B-Thinking-2507 | 30B MoE (3B active) | Qwen3 MoE | 2025 | ~2.5 GB | 32K | HF: bartowski/Qwen_Qwen3-30B-A3B-Thinking-2507-GGUF |
| 32 | Qwen3-Coder-30B-A3B-Instruct | 30B MoE (3B active) | Qwen3 MoE | 2025 | ~2.5 GB | 32K | HF: unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF |
| 33 | Qwen3-30B-A3B | 30B MoE (3B active) | Qwen3 MoE | 2025 | ~2.5 GB | 32K | HF: bartowski/Qwen_Qwen3-30B-A3B-GGUF |
| 34 | Cerebras Qwen3-Coder-REAP-25B-A3B | 25B MoE (3B active) | Qwen3 MoE | 2025 | ~2.5 GB | 32K | HF: bartowski/cerebras_Qwen3-Coder-REAP-25B-A3B-GGUF |
| 35 | Llama-4-Scout-17B-16E-Instruct | 17B MoE (16 experts) | Llama 4 | 2025 | ~10 GB | 256K? | HF: bartowski/meta-llama_Llama-4-Scout-17B-16E-Instruct-old-GGUF |
| 36 | Mistral-Small-24B-Instruct-2501 | 24B | Mistral | 2025 | ~14 GB | 32K | HF: bartowski/Mistral-Small-24B-Instruct-2501-GGUF |
| 37 | Mistral-Small-3.1-24B-Instruct-2503 | 24B | Mistral | 2025 | ~14 GB | 32K | HF: bartowski/mistralai_Mistral-Small-3.1-24B-Instruct-2503-GGUF |
| 38 | Mistral-Small-3.2-24B-Instruct-2506 | 24B | Mistral | 2025 | ~14 GB | 32K | HF: bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF |
| 39 | Devstral-Small-2-24B-Instruct-2512 | 24B | Mistral | 2025 | ~14 GB | 32K | HF: bartowski/mistralai_Devstral-Small-2-24B-Instruct-2512-GGUF |
| 40 | Dolphin3.0-R1-Mistral-24B | 24B | Mistral+R1 | 2025 | ~14 GB | 32K | HF: bartowski/cognitivecomputations_Dolphin3.0-R1-Mistral-24B-GGUF |
| 41 | OLMo 2-1124-13B-Instruct | 13B | OLMo 2 | 2024 | ~8.0 GB | 4K | HF: bartowski/OLMo-2-1124-13B-Instruct-GGUF |
| 42 | Gemma-3-27B-it | 27B | Gemma 3 | 2025 | ~16 GB | 128K | HF: bartowski/google_gemma-3-27b-it-GGUF |
| 43 | DeepSeek-R1-Distill-Qwen-32B | 32B | Qwen2.5 | 2025 | ~19 GB | 32K | HF: bartowski/DeepSeek-R1-Distill-Qwen-32B-GGUF |
| 44 | Qwen3-Coder-480B-A35B-Instruct | 480B MoE (35B active) | Qwen3 MoE | 2025 | ~20+ GB | 32K | HF: bartowski/Qwen_Qwen3-Coder-480B-A35B-Instruct-GGUF |
| 45 | GPT-OSS-20B | 20B | GPT-OSS | 2025 | ~12 GB | 32K | HF: bartowski/openai_gpt-oss-20b-GGUF |
| 46 | GPT-OSS-120B | 120B | GPT-OSS | 2025 | ~70 GB | 128K | HF: bartowski/openai_gpt-oss-120b-GGUF |
| 47 | EXAONE 3.5-32B-Instruct | 32B | EXAONE | 2025 | ~19 GB | 32K | HF: bartowski/EXAONE-3.5-32B-Instruct-GGUF |
| 48 | Llama-3.1-Nemotron-51B-Instruct | 51B | Llama/Nemotron | 2025 | ~30 GB | 128K | HF: bartowski/Llama-3_1-Nemotron-51B-Instruct-GGUF |
| 49 | DeepSeek-R1-0528 (full) | 671B MoE | DeepSeek V3 | 2025 | ~400+ GB | 128K | HF: bartowski/deepseek-ai_DeepSeek-R1-0528-GGUF |

## Ollama-Library Models (also available as GGUF)

| # | Model | Params | Notes |
|---|-------|--------|-------|
| 50 | llama3.1 (8B/70B/405B) | 8B/70B/405B | Meta, 2024 |
| 51 | llama3.2 (1B/3B) | 1B/3B | Meta, 2024 |
| 52 | llama3.3 (70B) | 70B | Meta, 2024 |
| 53 | deepseek-r1 (1.5B/7B/8B/14B/32B/70B/671B) | various | R1 distills + full |
| 54 | gemma3 (1B/4B/12B/27B) | various | Google, 2025 |
| 55 | gemma4 | ? | Google, 2026 |
| 56 | qwen2.5 (0.5B-72B) | various | Alibaba, 2024 |
| 57 | qwen3 (0.6B-235B) | various | Alibaba, 2025 |
| 58 | qwen3.5 | ? | Alibaba, 2025/2026 |
| 59 | qwen3.6 | ? | Alibaba, 2026 |
| 60 | qwen3-coder | various | Alibaba, 2025 |
| 61 | qwen2.5-coder (1.5B-32B) | various | Alibaba, 2024 |
| 62 | mistral (7B) | 7B | Mistral, 2023 |
| 63 | mistral-nemo (12B) | 12B | Mistral/Nvidia, 2024 |
| 64 | phi3 (3.8B/7B/14B) | various | Microsoft, 2024 |
| 65 | phi4 (14B) | 14B | Microsoft, 2025 |
| 66 | dolphin3 (1B/3B/8B/24B) | various | Cognitive Computations, 2025 |
| 67 | codellama (7B-70B) | various | Meta, 2024 |
| 68 | deepseek-coder (1.3B-33B) | various | DeepSeek, 2024 |
| 69 | deepseek-v3 (671B MoE) | 671B | DeepSeek, 2024 |
| 70 | olmo2 (7B/13B) | 7B/13B | AI2, 2024 |
| 71 | smollm2 (135M/360M/1.7B) | various | HuggingFace, 2024 |
| 72 | gpt-oss (20B/120B) | 20B/120B | OpenAI, 2025 |
| 73 | minicpm-v | various | OpenBMB, vision |
| 74 | llava (7B/13B) | 7B/13B | vision |
| 75 | qwen3-vl (2B/4B/8B/32B/30B-A3B) | various | Alibaba, vision |
| 76 | llama3.2-vision (11B/90B) | 11B/90B | Meta, vision |
| 77 | nomic-embed-text | embedding | Nomic, embeddings |
| 78 | mxbai-embed-large | embedding | MixedBread, embeddings |
| 79 | all-minilm | embedding | sentence-transformers |
| 80 | bge-m3 | embedding | BAAI, multilingual embeddings |
| 81 | glm-ocr | vision | THUDM, OCR |
| 82 | command-r7b-12-2024 | 7B | Cohere |

## Specialized / Notable Models

| # | Model | Params | Why Notable |
|---|-------|--------|-------------|
| 83 | DeepSeek-R1-0528-Qwen3-8B | 8B | R1 CoT reasoning on Qwen3. Think-before-speak for trading. |
| 84 | Qwen3-30B-A3B-Thinking-2507 | 30B MoE 3B active | Tiny VRAM footprint (2.5GB!) with 30B knowledge. Fits on RTX 3070 with room to spare. Has thinking mode. |
| 85 | Cerebras Qwen3-Coder-REAP-25B-A3B | 25B MoE 3B active | Cerebras-optimized MoE. Same 2.5GB footprint. You already tried downloading this. |
| 86 | Qwen3-14B | 14B | Sweet spot for supervisor. Fits 16GB with 32K context. Strong reasoning. |
| 87 | Gemma-4-12B-Agentic | 12B | Already on disk. 128K context. 6.9GB. Google's latest. |
| 88 | Phi-4-mini-reasoning | 3.8B | Tiny reasoning model. 2.5GB. Could run on RTX 3070 alongside a larger model. |
| 89 | Llama-4-Scout-17B-16E-Instruct | 17B MoE | Meta's 2025 MoE. Multimodal. Active params ~5B, fits 8GB? |
| 90 | GPT-OSS-20B | 20B | OpenAI's open-source model. 12GB at Q4. Barely fits 16GB. |
| 91 | Dolphin3.0-R1-Mistral-24B | 24B+R1 | R1 reasoning + Dolphin agentic training + Mistral. 14GB. Too big for both GPUs. |
| 92 | Command A Reasoning 08-2025 | 7B | Cohere's reasoning model. 4.5GB. Good alternative trading model. |
| 93 | Granite 3.3-8B-Instruct | 8B | IBM's latest. 2026 release. Good instruct compliance. |
| 94 | InternLM3-8B-Instruct | 8B | Shanghai AI Lab. Strong agentic benchmarks. |
| 95 | EXAONE 3.5-7.8B-Instruct | 7.8B | LG AI Research. Competitive with Qwen3-8B on Korean/English. |

## Key Platform Insights

### HuggingFace (bartowski GGUF):
- bartowski converts every major release to GGUF with Q4_K_M
- Download: `huggingface-cli download bartowski/<model> --include "*Q4_K_M*"`

### Ollama:
- Library: `ollama pull qwen3:8b`, `ollama pull gemma4:12b`, etc.
- Models: llama3.1, llama3.2, llama3.3, deepseek-r1, gemma2, gemma3, gemma4, qwen, qwen2, qwen2.5, qwen3, qwen3.5, qwen3.6, qwen3-coder, qwen2.5-coder, mistral, mistral-nemo, phi3, phi4, dolphin3, smollm2, olmo2, gpt-oss, command-r7b, codellama, deepseek-coder, deepseek-v3, minicpm-v, llava, qwen3-vl, llama3.2-vision, glm-ocr

### GitHub:
- llama.cpp releases: official models converted to GGUF
- Open-source training code for Qwen3, DeepSeek, Llama 4, Gemma 4
