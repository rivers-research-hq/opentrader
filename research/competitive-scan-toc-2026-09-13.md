# Competitive scan — token-budgeted context & epistemic governance for local LLMs

Ticket: rivers-research-hq/opentrader#261 · Map: #260 (toc open-core launch) · Date: 2026-09-13
Method: primary sources only — vendor pricing pages (fetched live 2026-09-13), official docs, GitHub API star/license counts, HN Algolia search API. Every number below is from the cited page; vendor performance claims are marked as such and not repeated as facts.

## Headline finding

**No tool found that sells what toc sells.** The market is organized in three camps, none of which govern the *question* before tokens are spent:

1. **Memory-as-a-service** (Letta, Mem0, Zep, Supermemory, Cognee) — manages what the model *remembers* across sessions; paid SaaS/credits, OSS cores.
2. **Platform-native context management** (Anthropic context editing + memory tool) — clears/summarizes context server-side, free but Claude-only.
3. **Post-hoc validation** (Cleanlab TLM, Guardrails AI, NeMo Guardrails, Patronus/Galileo) — scores or blocks the model's *output* after generation.

toc's combination — per-phase **hard token budgets** enforced by pre-flight estimates, an **epistemic ledger** (known/computable/unknowable/explore) that client-side **refuses unanswerable questions before any model call**, explore-quarantine, and endpoint-agnostic operation against any OpenAI-compatible local server — has no direct competitor found. HN Algolia for "epistemic LLM" (26 stories total, 2025-2026): the nearest semantic neighbors are **Rigor** ("epistemic graph with LLM-as-judge", waitlist-only, core not released), a post-generation "admissibility layer" demo (1-3 pts), and MarCognity-AI (local epistemic-verification layer, 1-3 pts, no traction). None is a claims registry that routes questions pre-spend.

## Competitor table

| Product | What it does | Overlap with toc | Pricing (fetched 2026-09-13) | Distribution | Weakness (for toc's wedge) |
|---|---|---|---|---|---|
| **Letta** (ex-MemGPT) | Stateful agents, persistent memory blocks, context auto-summarization; Letta Code | Manages agent memory/state; server-side context management | Cloud: Free $0 (3 agents), Pro $20/mo (20 agents), API $20/mo + $0.10/active agent/mo + $0.00015/s tool exec; usage-based LLM credits; Enterprise custom. Self-hosting documented, unpriced | Apache-2.0 OSS (24.7k stars) + cloud | Memory = persistence, not epistemic routing; no question refusal; agent-platform weight; monthly SaaS minimums |
| **Mem0** | Memory layer (add/retrieve) for LLM apps | Memory layer with usage metering | Hobby free (10k add / 1k retrieval req/mo), Starter $19/mo, Pro $249/mo, Enterprise custom (on-prem enterprise-only) | OSS Apache-2.0 (65.2k stars) + cloud | Retrieval of stored memory, not governance; no budgets/ledger; cloud-first |
| **Zep / Graphiti** | Temporal knowledge-graph memory | Memory with structured entities | Free 10k credits/mo, Flex $125/mo (50k cr), Flex Plus $375/mo (200k cr), Enterprise custom | OSS Apache-2.0 (30.9k stars Graphiti) + cloud/BYOC | KG ops burden; memory ≠ routing; credits are SaaS |
| **Supermemory** | Memory + RAG API, MCP plugins | Memory service with self-serve rate card | Free $0 ($5 cr), Pro $19/mo, Max $100/mo, Scale $399/mo (self-host from here), Ent custom; rate card $0.005/1k SM tokens (plain), $0.005/1k queries | OSS MIT (29.7k stars) + API/MCP | Ingestion-priced memory SaaS; not a competence governor |
| **LangSmith** (LangChain) | Tracing, evals, prompt mgmt, agent deployment, LLM gateway | Nearest "agent infrastructure platform" neighbor | Developer $0 (1 seat, 5k traces/mo), Plus $39/seat/mo, LCU $1.50, LSU $1.00, Enterprise custom; startup credits $10k | SaaS + enterprise self-host | Observability/eval ≠ context governance; per-seat SaaS; cloud-centric |
| **LlamaIndex / LlamaCloud** | RAG framework + managed parse/index | Context *assembly* at pipeline scale | Free 10k credits, Starter $50/mo (40k cr), Pro $500/mo (400k cr); 1k credits = $1.25; Ent custom | OSS MIT (52.1k stars) + cloud | RAG pipeline, not agent governance; managed service |
| **Cognee** | Memory engine (ECL pipelines, graphs) | Local-capable memory | OSS Apache-2.0 (30.7k stars); cloud is sales-led — no public pricing found | OSS + enterprise | Memory engine; monetization undefined publicly |
| **Cleanlab TLM** | Trustworthiness scores on LLM outputs (hallucination flagging) | Hallucination containment | No public pricing (sales-led); OSS core 11.7k stars | Sales-led SaaS | **Post-hoc**: scores responses after generation; no pre-spend routing; no local-model story on page |
| **Guardrails AI** | Output validation framework + Hub of guardrails | Hallucination containment, open-core | OSS Apache-2.0 (7.4k stars) free; Hub free; paid/cloud sales-led (no public pricing) | OSS + enterprise sales | Post-hoc validators; framework you wire yourself |
| **NVIDIA NeMo Guardrails** | Rails for output/topic control (Colang) | Hallucination containment | Free OSS (Apache-family, 7.1k stars) | OSS, NVIDIA support upsell | Post-hoc; engineering framework, not a workflow |
| **Forge** | Reliability layer for self-hosted small models: tool-call guardrails (rescue parsing, retries, validation) + token-budget context compaction (`budget_tokens`, sliding/tiered strategies) + hardware profiling; drop-in **proxy** for llama-server/Ollama/vLLM | **Closest philosophical neighbor**: targets the exact same model class (small local models), same endpoints, includes token-budget compaction | **Free, MIT** (2.2k stars); no paid tiers, no cloud | OSS (`pip install forge-guardrails`), proxy drop-in | Tool-call/output reliability, not question governance; no epistemic ledger, no budget ledger, no refusal of unanswerable asks; has a 26-scenario eval ("8B single digits → 84%", vendor-claimed) — toc has no comparable published number yet |
| **Anthropic context editing + memory tool** | Server-side clearing of tool results/thinking + memory files when context nears trigger | Context-window management at platform level | Beta; no separate fee — billed as tokens (clearing *reduces* input tokens; cache-write costs on each clear) | Claude API only | Claude-only; no user-defined budgets/ledger; no question routing; model-owned, not endpoint-agnostic |
| **LLMLingua** (Microsoft) | Prompt compression (2-20x) | Token-count reduction before send | Free, MIT (6.7k stars) | OSS/research | Compression, not governance; research tooling |
| **Context7** (Upstash) | Injects up-to-date library docs into prompts | Context *freshness* | OSS MIT (62.0k stars); Upstash SaaS pricing separate | OSS + API | Doc retrieval, not budgets or epistemics |

Star counts from GitHub API (`gh api repos/<repo>`), 2026-09-13.

## Adjacent but different

- **MemGPT paper → Letta**: the research lineage for OS-style memory paging; commercialized as Letta (above).
- **MemOS (MemTensor)** — "memory operating system", 11.3k stars, Apache-2.0; memory hierarchy research/product, no governance layer.
- **MCP (Model Context Protocol)** — the tool/context transport standard; not a governor, but the plumbing toc-adjacent tools ride on (Zep, Supermemory, Context7 all ship MCP servers).
- **Prompt caching (Anthropic/OpenAI/Bedrock)** — cost optimization for *cloud* tokens; toc's budgets exist for *competence*, not cost (its own README: "the budget is not about cost").
- **Repo→prompt packers (gitingest 15.5k stars, repomix 28.3k stars)** — one-shot token-budgeted packing of a codebase; no state, no governance.
- **HN-niche 2025-26 artifacts** (all ≤687 pts, mostly free OSS): MCP Compact (per-tool output trimming), One-MCP (on-demand tool loading), MindCache (per-type token budgets), OMS/CAL open memory spec (memorygrain.org) — evidence the *problem* is felt, but nobody has productized governance.
- **Uncertainty quantification**: Vectara HHEM leaderboard (3.3k stars), Spanda (sub-µs epistemic-uncertainty in Rust, HN 2026-09-11) — score uncertainty, don't route questions.
- **Eval/observability platforms (sales-led, no public pricing found)**: Patronus AI, Galileo, WhyLabs — post-hoc monitoring suites for enterprises.

## Sharpest honest differentiation statement

> Every commercial tool in this territory governs what the model **remembers** (Letta, Mem0, Zep, Supermemory — $19-$399/mo SaaS, cloud-first) or what happens **after** it answers (Cleanlab TLM, Guardrails AI — score and flag the output once tokens are already spent). Platform-native context editing (Anthropic) clears history but only inside Claude's API. **toc is the only tool found that governs the question before tokens are spent**: a curated epistemic ledger that hard-refuses unknowable targets client-side (zero tokens, logged as open questions), hard per-phase token allowances with pre-flight gating calibrated against real API usage, and explore-quarantine for speculation — running against any OpenAI-compatible endpoint, i.e. exactly the local-model regime where memory-vendor monthly minimums buy a SaaS dependency you don't need and platform features don't exist.

Defensible boundaries (stated in the same breath as the claim):
1. **"Only tool found"** is a market-scan claim (this file), not a patent claim; the nearest unreleased neighbor is Rigor (waitlist, "epistemic graph").
2. toc has **no published net-hallucination-reduction benchmark** yet (blueprint §10 lists the controlled with/without experiment as the follow-up). Forge's 26-scenario eval is vendor-claimed; do not counter it with vibes — the honest gap is "eval pending". Consistent with the standing claims-governance rule: no number goes on the landing page that the ledger wouldn't clear.
3. Competitor pricing verified live 2026-09-13; Cleanlab/Guardrails/Patronus/Galileo are sales-led with no public numbers — do not invent tiers for them.

## Threats worth watching

- **Platform absorption**: Anthropic ships context editing + memory as a free-with-tokens API feature (beta, 2025-06-27 header); if llama.cpp/llama-server absorbs equivalent server-side compaction, toc's budget layer must keep its value in the *epistemic* half.
- **Forge's distribution**: free MIT proxy already sits between clients and local servers (the same integration point `toc` uses); if it adds a ledger, the wedge narrows.
- **Memory-vendor gravity**: mem0/context7/cognee hold 30-65k-star mindshare vs toc's private repo; open-core launch competes for the same "context engineering" search attention.

## Sources

- letta.com/pricing → docs.letta.com/letta-code/pricing (fetched 2026-09-13)
- langchain.com/pricing; mem0.ai/pricing; getzep.com/pricing; llamaindex.ai/pricing; supermemory.ai/pricing (fetched 2026-09-13)
- cleanlab.ai/tlm/ (no public pricing); guardrailsai.com (no public pricing) (fetched 2026-09-13)
- platform.claude.com/docs/en/build-with-claude/context-editing (fetched 2026-09-13)
- github.com/antoinezambelli/forge (README + repo metadata) (fetched 2026-09-13)
- GitHub API star/license counts: repos listed above (2026-09-13)
- HN Algolia API: query "token budget LLM context", query "epistemic LLM" (2026-09-13)
- toc product context: /home/mrc/ai/table-of-context/README.md, blueprint.md (read-only)
