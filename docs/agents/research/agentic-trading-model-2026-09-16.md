# Agentic Trading Model for OpenTrader — Design Document

**Date:** 2026-09-16
**Status:** Research draft
**Scope:** Architecture, training paradigm, tool-use, and implementation plan for an LLM-powered agentic trading model on the OpenTrader FX arm (OANDA practice).

---

## Executive Summary

The current OpenTrader system uses a traditional ML pipeline: a transformer-based score predictor (fxexpert) per pair, feeding a rule-based rank book that rebalances every 30 trading days. This design recommends evolving toward an **agentic trading model** -- a small LLM (7B-8B class, Q4_K_M quantized) that reasons about the market, uses tools (price feeds, risk checks, order management, macro queries), and learns from outcomes via outcome-based reinforcement learning (GRPO).

**First prototype recommendation:** A ReAct-style agent running on the RX 7900 GRE (16GB, Granite 4.2-8B or Qwen2.5-7B) that receives daily feature vectors from the existing accrual store, holds a structured conversation with itself (thinking step -> tool call -> observation -> next thought), and outputs a trading decision with conviction. The agent runs alongside the existing fxexpert rank book, voting on each pair. Its votes are scored against actual close-to-close movement -- no positions, no P&L risk -- building a track record that qualifies it for a shadow lane.

**Key reuse:** The DuckDB accrual store (`/home/mrc/opentrader-data/store.duckdb`), the OANDA adapter (`exchange/oanda.py`), the FRED macro pipeline (`data/economics.py`, `scripts/fetch_fred_cond.py`), the warden's observe->plan->score pattern (`strategies/fx_warden.py`), the existing GRPO implementation (`arena/grpo.py`), and the Unsloth fine-tuning pipeline (`training/finetune_cycle.py`).

**What to discard:** The "LLM architect proposes skills" pattern in the arena (it has not produced a useful signal since 2026-08), the phantom model roles in `config/model_roles.json`, and any hope of running a 30B MoE model on 16GB VRAM at interactive speed.

---

## 1. Architecture Recommendations (with cited sources)

### 1.1 ReAct (Reasoning + Acting) for Trading

**Source:** Yao et al. 2022, "ReAct: Synergizing Reasoning and Acting in Language Models" (arXiv:2210.03629).

ReAct interleaves natural-language reasoning traces with concrete actions and environment observations. The key pattern:

```
Thought: "The recent US CPI print came in hot. This suggests the dollar should strengthen against EUR."
Action: get_price(EUR_USD): 1.0523
Observation: EUR_USD last traded at 1.0523, down 0.3% on the day.
Thought: "The move already happened before the news? That's a buy-the-rumor, sell-the-news setup. I should wait for a retracement before entering."
Action: get_bars(EUR_USD, "1h", 24)
Observation: [candles...] Price gapped down at the CPI release, has been range-bound for 3 hours.
Thought: "No entry yet. Mark as HOLD with moderate conviction."
Action: output_decision({"pair": "EUR_USD", "action": "HOLD", "conviction": 0.6})
```

**Recommendation:** Use this as the core loop. The agent gets a fixed set of tools (see section 2) and is prompted to reason step-by-step before acting. The prompt includes 1-2 exemplar traces (standard ReAct practice) to demonstrate the format.

### 1.2 The Warden Pattern (Observe -> Plan -> Score)

**Existing code:** `strategies/fx_warden.py` already implements this cycle for lane monitoring:

- **Observe:** Read venue state + news feed + instability table. The model produces structured notes with verified numeric claims.
- **Plan:** Set expected P&L per lane, conditioned on news and recent performance. Written to `data/warden/game_plan.json`.
- **Score:** Compare actual vs expected with an expectation-adjusted reward. Writes to `data/warden/scorecard.json`.

This maps directly onto the agentic trading loop. The agent would follow the same observe->reason->act->observe cycle, but instead of monitoring lanes, it would be making trading decisions.

### 1.3 Multi-Agent Debate (Lower Priority)

**Source:** TradingAgents (arXiv:2412.20138) -- a multi-agent framework inspired by trading firms with Fundamental Analysts, Sentiment Analysts, Technical Analysts, Traders, and Risk Managers. TradingGPT (arXiv:2309.03736) adds layered memory with per-layer decay.

**Assessment:** Multi-agent debate is architecturally tempting but expensive for the available hardware. Running 3+ models at 7B each would consume 15-18GB VRAM in Q4, leaving no room for context. **Recommend deferring debate until hardware allows** (e.g., a second GPU dedicated to inference). For the first prototype, a single agent with multi-step reasoning (ReAct) is sufficient.

The one exception: a **Bull/Bear researcher pair** (two 4B models on the 3070, ~3GB each in Q4) could provide opposing market assessments that feed into the main agent's context as observations. This is Phase 2.

### 1.4 Plan-vs-Execute Loop

**Recommendation:** Use a two-phase loop within each daily decision cycle:

1. **Plan phase** (morning, before market open): The agent reviews overnight price action, reads news/economic calendar, checks existing positions, forms a trading plan for the day. Output: `{"plan": "look for EUR/USD long if US data disappoints", "conviction": 0.3, "triggers": ["CPI < 3.0% YoY", "EUR/USD below 1.0500"]}`
2. **Execute phase** (on trigger or scheduled interval): The agent checks whether entry conditions are met, calls `place_order` if conviction exceeds threshold, monitors positions for exits.

This matches how the existing lanes work (`fx_runner --once` at specific times) and avoids continuous inference costs.

---

## 2. Tool-Use Paradigm

### 2.1 Tool Granularity

**Recommendation:** Many small tools, not one big "execute trade" tool. This follows the principle from Gorilla (Patil et al. 2023, "Gorilla: Large Language Model Connected with Massive APIs") and the general tool-use literature: fine-grained tools are more reusable, composable, and easier to verify.

**Core tool set:**

| Tool | Description | Status |
|------|-------------|--------|
| `get_price(symbol)` | Current mid/ask/bid from OANDA | EXISTS: `exchange/oanda.py:get_current_price()` |
| `get_bars(symbol, timeframe, count)` | Recent OHLCV bars | EXISTS: `exchange/oanda.py:get_bars()` |
| `get_positions()` | Current open positions (venue-truth) | EXISTS: `exchange/oanda.py:openTrades` via `_request()` |
| `get_balance()` | Account cash/Nav | EXISTS: `exchange/oanda.py` account summary |
| `get_open_trades(tag)` | Filtered by lane tag | EXISTS: `strategies/fx_warden.py:lane_states()` |
| `check_risk(symbol, side, notional)` | Risk check before order | EXISTS: `risk/manager.py` |
| `place_order(symbol, side, units, tag)` | Place market order with SL/TP | EXISTS: `exchange/oanda.py:place_order()` |
| `query_macro(series)` | FRED macro data | EXISTS: `data/economics.py:fetch_fred_series()` |
| `get_calendar(days_ahead)` | Economic calendar events | EXISTS: `data/economic_calendar.py` |
| `get_carry(pair)` | Current carry rate | EXISTS: `fxexpert/data.py` carry block |
| `get_news(count)` | Recent canonical headlines | EXISTS: `strategies/fx_warden.py:newsfeed_digest()` |

### 2.2 Integration Method: Prompted (Few-Shot)

**Recommendation:** Start with **prompted tool-use** (few-shot in context) rather than fine-tuning or native function-calling tokens. Rationale:

1. **Prompted** -- define tools in the system prompt with JSON-call format. Works with any model, no training needed. The warden already uses this pattern (JSON output from system prompt).
2. **Fine-tuned** -- Gorilla's approach of training on `{instruction, api_call, response}` triples. This would require a dataset of tool-use trajectories, which doesn't exist yet. Could be Phase 2 once enough ReAct traces accumulate.
3. **Native function calling** -- models like Qwen2.5 have built-in tool-use tokens, but these are optimized for REST API calls, not the specific trading tools above. Would still need system-prompt definitions.

The prompt format:

```
You are a trading agent with access to these tools:

Tool: get_price(symbol: str) -> float
Tool: get_bars(symbol: str, timeframe: str, count: int) -> list[candle]
Tool: query_macro(series: str) -> float
Tool: output_decision(pair: str, action: str, conviction: float, rationale: str) -> None

Call a tool by writing:
  ACTION: get_price("EUR_USD")
Then you'll receive the result as OBSERVATION.

Repeat: Thought -> ACTION -> OBSERVATION until enough information is gathered,
then call output_decision().
```

**Existing infrastructure for this pattern:**

- The warden (`fx_warden.py`) already uses `llm_json()` to call a local model with a structured system prompt and parses JSON output. The agentic trading model would extend this: instead of one call per mode, it would loop (Thought -> Action -> Observation -> Thought) for 3-5 iterations per decision cycle.
- The MCP server (`mcp_server.py`) already wraps exchange operations as callable tools (MCP protocol). This is available but may add latency vs. direct Python calls.

### 2.3 The Context Window Budget

A 7B model at Q4_K_M has ~8K-32K context depending on the GGUF. Budget for each ReAct cycle:

| Component | Tokens |
|-----------|--------|
| System prompt (tools definition + role) | ~800 |
| Few-shot exemplars (2 examples) | ~1200 |
| Today's feature vector + market data | ~600 |
| Tool definitions in JSON | ~400 |
| Per-step: Thought (~50) + Action (~30) + Observation (~200) | ~280/step |
| 5 steps total | ~1400 |
| **Total per decision** | **~4400** |

This fits comfortably in 8K context. Headroom for longer reasoning chains or more exemplars.

---

## 3. Training Paradigm

### 3.1 Outcome-Based RL (GRPO)

**Source:** DeepSeek-R1 (arXiv:2501.12948) -- demonstrates that pure RL from outcome feedback (no human reasoning traces) can produce emergent reasoning patterns (self-reflection, verification, dynamic strategy adaptation).

**Existing code:** `arena/grpo.py` already implements GRPO (Group Relative Policy Optimization) for the value-head MLP. The objective:

```
J = (1/G) * sum_i (1/|o_i|) * sum_t {
    min[ratio_t * A_hat, clip(ratio_t, 1-e, 1+e) * A_hat] - beta * D_KL(pi_theta || pi_ref)
}
```

The agentic trading model would use the same objective but applied to the LLM's decision distribution (which pair, which action, at what conviction) rather than a value-head's binary TAKE/HOLD.

**Training data pipeline:**

```
Accrual Store (DuckDB) -> Panel Builder (fxexpert/data.py)
       |
       v
Feature vectors per pair per day
       |
       v
Agent inference (ReAct loop, daily)
       |
       v
Decisions: {pair, action, conviction, rationale, feature_context}
       |
       v
Next-day close -> Outcome: {win/loss, magnitude, realized_pnl}
       |
       v
GRPO update: advantage = z-score(decision_outcome - group_mean)
             group = regime (up/down market)
       |
       v
LoRA weights updated (target model on GRE)
```

### 3.2 The Reward Signal

Unlike DeepSeek-R1 (verifiable correctness on math/code), trading outcomes are probabilistic. The reward must handle this:

- **Binary win/loss** as the primary signal (did price move in the predicted direction?)
- **Magnitude bonus** (how far did it move in the right direction?)
- **Risk-adjusted penalty** (conviction * |move| -- a high-conviction wrong call is penalized more)

This matches the warden's expectation-adjusted scoring pattern (`fx_warden.py:554-561`):

```python
miss = actual_pct - expected
penalty = miss if miss >= 0 else miss - HARSHNESS * abs(expected)
```

### 3.3 Supervised Fine-Tuning on Expert Records (Phase 2)

Once the agent has accumulated ~1000 ReAct decision traces (each with outcome), those with positive outcomes become supervised fine-tuning data. This is the standard "RL from AI feedback" loop:

1. Rollout with current policy (exploration)
2. Filter trajectories by outcome (keep good ones)
3. SFT on filtered trajectories (exploitation)
4. Repeat

This is feasible on the RTX 3070 (8GB) using QLoRA via Unsloth. The existing `training/finetune_cycle.py` already implements this pattern for the warden model, using `unsloth` + `bitsandbytes` for 4-bit QLoRA.

### 3.4 What is Feasible on 16GB AMD VRAM

| Task | Model | VRAM | Method | Feasible |
|------|-------|------|--------|----------|
| Inference | 7B Q4_K_M | ~4.5-5 GB | llama.cpp ROCm HIP | YES, with 11GB left for context |
| Inference | 8B Q4_K_M | ~5-6 GB | llama.cpp ROCm HIP | YES |
| Inference | 14B Q4_K_M | ~8-9 GB | llama.cpp ROCm HIP | YES, but tight |
| Inference | 30B-A3B MoE Q4 | ~6-8 GB (activated) | llama.cpp | DEPENDS -- MoE models swap experts in/out, but total VRAM for all experts may exceed 16GB |
| Fine-tuning | 7B QLoRA | ~6-8 GB | Unsloth + ROCm | MAYBE -- Unsloth claims ROCm support, but real throughput unknown |
| Fine-tuning | 7B QLoRA | ~6-8 GB | CUDA on 3070 | YES (existing pipeline) |

**Key constraint for MoE models (30B-A3B like Qwen3-Coder-30B-A3B):** While only ~3B params are activated per token, all 30B params must be loaded into VRAM. At Q4, that's ~15-17GB for all experts -- exceeding 16GB with any context. **Not recommended** for this use case.

**Better choices for 16GB:**
- Qwen2.5-7B-Q4_K_M: ~4.8 GB, strong tool-use, 32K context, excellent Chinese/English reasoning
- Granite 4.2-8B-Q4_K_M: ~5.5 GB, already the warden's model on :5802
- Llama 3.1 8B-Q4_K_M: ~5.5 GB, good tool-use but weaker on multi-step reasoning
- For fine-tuning: Qwen2.5-7B with QLoRA (4-bit base + LoRA adapters) fits in ~7-8 GB

### 3.5 Inference Speed Expectations

| Model | Quant | Hardware | Expected Tok/s | Decision Latency |
|-------|-------|----------|----------------|------------------|
| 7B Q4_K_M | GGUF | RX 7900 GRE | ~15-25 tok/s | ~3-7s per decision cycle |
| 8B Q4_K_M | GGUF | RX 7900 GRE | ~12-20 tok/s | ~4-8s per decision cycle |
| 7B Q4_K_M | GGUF | RTX 3070 | ~20-35 tok/s | ~2-5s per decision cycle |
| 4B Q4_K_M | GGUF | RTX 3070 | ~35-60 tok/s | ~1-3s per decision cycle |

For a daily decision cycle (plan at 17:10, execute at 21:25, matching the existing cron schedule), latency is not a concern -- 5-8 seconds for the full ReAct loop is acceptable.

---

## 4. Existing Codebase Reuse

### 4.1 Ready to Reuse (No Changes Needed)

| Component | Path | Function |
|-----------|------|----------|
| OANDA adapter | `exchange/oanda.py` | `get_bars()`, `get_current_price()`, `get_prices_batch()`, `place_order()`, `connect()` |
| Exchange base | `exchange/base.py` | `OHLCV`, `OrderResult`, `Balance` dataclasses |
| Risk manager | `risk/manager.py` | `check_risk()` before order placement |
| FRED economics | `data/economics.py` | `fetch_fred_series()` for macro context |
| Economic calendar | `data/economic_calendar.py` | Upcoming event proximity/density features |
| Accrual store | `fxexpert/data.py` | Reads `store.duckdb` to build training panels |
| GRPO optimizer | `arena/grpo.py` | Full GRPO implementation, ready for reuse |
| Unsloth fine-tune | `training/finetune_cycle.py` | QLoRA fine-tuning pipeline with version tracking |
| Model manager | `model_manager.py` | Model discovery, download, and launch |
| Security guards | `security/guards.py` | Hardened URL/open/request wrappers |

### 4.2 Adaptable (Minor Changes Needed)

| Component | Path | Adaptation |
|-----------|------|------------|
| Warden pattern | `strategies/fx_warden.py` | Extract the `llm_json()`, `_extract_json()`, and newsfeed helpers into a shared module. The observe / plan / score cycle is the template for the agent's daily loop. |
| fxexpert model | `fxexpert/model.py` | The FXExpert transformer (20-day window -> scalar score) provides the feature representation the agent reasons over. The agent could consume the model's output as a signal, replacing the rule-based rank book. |
| Training data builder | `training/data_builder.py` | Extend to record agent reasoning traces alongside features and outcomes, for GRPO training. |
| MCP server | `mcp_server.py` | The MCP server wraps exchange operations as tools -- these are the natural backend for the agent's tool calls. But direct Python calls may be lower latency. |
| Dashboard | `dashboard.py` | Add endpoint for agent decisions and performance (parallel to `/api/fx`). |
| Lane attribution | `strategies/lane_attribution.py` | If the agent graduates to a live lane, its fills need tag-based attribution through the shared resolver. |

### 4.3 What to Discard

| Artifact | Reason |
|----------|--------|
| `config/model_roles.json` | References 6 phantom models; the agent defines its own roles via the system prompt. |
| Arena architect | `arena/architect.py` -- The LLM-that-proposes-skills pattern has not produced useful signals since 2026-08. The agent's own reflections replace this. |
| `gpu_sync.py` | Dead proxy for :5801; the agent calls llama.cpp directly. |
| `harness.py` | 4260-line monolith; the agent operates independently via the OANDA adapter. |
| `llama-swap` dependencies | Not installed (`~/llama-swap/` missing); the agent manages its model directly via `model_manager.py`. |
| `tui.py` | Legacy Textual artifact; the human runs `tui/index.js`. |
| Pre-2026-09 FRED caches | The `macro_cache.json` may have stale pre-cache-fix data; a fresh fetch is needed for training. |

### 4.4 Key Reuse: The Warden's observe->plan->score Cycle

The warden in `strategies/fx_warden.py` shows exactly the pattern we need:

```
observe():
  1. Read venue state (balance, positions, P&L per lane)
  2. Read news feeds and economic calendar
  3. Call LLM with structured system prompt, parse JSON output
  4. Write structured notes and observations
  5. Update MFE (maximum favorable excursion) tracker

plan():
  1. Freshen feeds
  2. Read venue state + previous scores
  3. Call LLM to set expected P&L for each lane
  4. Validate lane coverage (no lane omitted)
  5. Write game plan with period anchor

score():
  1. Read game plan + current venue state
  2. Compute actual vs expected with expectation-adjusted penalty
  3. Update probation status per lane
  4. Compute give-back ratio (exit skill metric)
  5. Write scorecard
  6. Escalate to shadow cut list if needed
```

The agentic trading model reuses the infrastructure (LLM endpoint, JSON extraction, venue state reading, news digest, record logging, numeric claim verification) but replaces the "monitor lanes" purpose with "make trading decisions."

---

## 5. The Paper Jury / Shadow Arena Concept

### 5.1 Design Summary

The proposal: N agents each receive the same daily feature vector, each outputs `{vote: buy/sell/hold, conviction: 0-1}`. At the NEXT close, actual price movement scores each vote -- no positions, no P&L, just binary win/loss per period. Bottom agents are periodically retired, top agents spawn variants.

### 5.2 Novelty Assessment

**Not novel in concept, but novel in application for this hardware tier:**

- **Similar work:** The tournament swarm (R1/R1b/R1c, 2026-08-13) used exactly this pattern -- 6 parallel research agents, shared scorer, escalating bars, bottom-cull. It verified 4 strategies that beat all benchmarks and 2 that transferred to OOS universes. The difference: those were Python research scripts, not live LLM agents.
- **FinRL crowd** (A2C/DDPG/PPO/SAC agents): Multiple agents trained with DRL, tournament-selected. The paper jury differs by using LLM-based agents that reason in natural language (interpretable) rather than policy-gradient networks (black box).
- **TradingAgents** (arXiv:2412.20138): Uses specialized agent roles with debate, not competing identical agents.
- **Novel element:** The combination of LLM agents with binary outcome scoring (no P&L, no positions) on the existing FX accrual store infrastructure, with GRPO for weight evolution, is not found in the literature reviewed.

### 5.3 Failure Modes

1. **Overfitting to noise.** Binary win/loss signals are noisy -- two agents can have identical strategies but diverge 45-55% on the same data. Mitigation: use rolling-window scoring (minimum 20 periods before culling), and compare against a random-agent baseline.

2. **Convergence to identical strategies.** If the feature vector is the same and the prompt is the same, agents with different random seeds may converge. Mitigation: diversify across (a) different instruction sets (technical-only, macro-only, hybrid), (b) different temperature settings, (c) different context windows (pair-level vs. portfolio-level).

3. **Strategy collapse under evolution pressure.** If bottom agents are retired and replaced by mutated top agents, the population can lose diversity. Mitigation: maintain a "wild type" agent (random, non-learned baseline) and a "museum" of past winners. Only cull below the random baseline.

4. **Lookahead bias.** The daily feature vector must use only data up to the close, and scoring uses the next close. The accrual store already guarantees this causal separation -- the agent must follow the same discipline.

### 5.4 Implementation on Existing Hardware

The paper jury runs entirely offline (no live positions), so it uses spare GPU cycles:

```
RX 7900 GRE (16GB): Tournaments
  - 4 concurrent 7B-Q4 agents (batch inference, 4x ~1GB KV cache + ~5GB model = ~9GB)
  - Or 8 concurrent 4B-Q4 agents (~3GB each)
  - Each agent processes the same 200 days of history for the initial tournament
  
RTX 3070 (8GB): GRPO training
  - QLoRA fine-tune of the winning agent variant on its decision traces
  - 7B model in 4-bit + LoRA = ~7GB, fits with batch_size=1

System RAM (31GB):
  - Loading/processing the accrual store panel
  - Scoring and tournament management
  - Caching feature vectors
```

The jury loop:

```python
# Pseudo-code for the paper jury
def paper_jury_round(agents, features, n_days=200):
    """Score N agents on M days of historical data.
    
    Each day, each agent receives the feature vector and outputs a vote.
    The next day's close determines win/loss.
    After all days, bottom agents are retired, top agents spawn variants.
    """
    scores = {a.id: [] for a in agents}
    
    for day in range(n_days - 1):
        # Each agent gets the same feature vector (up to and including day t)
        feat_t = features[day]
        
        for agent in agents:
            # Agent reasons and votes (parallelizable across agents)
            vote = agent.decide(feat_t)  # {action: BUY/SELL/HOLD, conviction: 0-1}
            
            # Score against next day's return
            ret_d1 = features[day + 1]['return']
            outcome = 1.0 if (vote.action == 'BUY' and ret_d1 > 0) or \
                            (vote.action == 'SELL' and ret_d1 < 0) or \
                            (vote.action == 'HOLD' and abs(ret_d1) < threshold) else -1.0
            outcome *= vote.conviction  # Scale by conviction
            
            scores[agent.id].append(outcome)
    
    # Tournament: rank by rolling average, cull below median, mutate top half
    return ranked_agents
```

### 5.5 Coexistence with the Live Lane

The paper jury serves as a **consensus signal** for the live lane:

- The live lane (fxexpert-g151, the sole deployed expert) continues its 30-day rank book.
- The paper jury computes a daily consensus vote (mean conviction-weighted action across surviving agents).
- If the jury's consensus has above-threshold conviction AND aligns with the live lane's top-3 pairs, increase position size (or reduce if they disagree).
- The jury never opens positions -- it only adjusts sizing on existing lane entries. This keeps the "gate-entries-only; no forced exits" principle (verified by the 2026-08 tournament: forced exits destroy returns).

Over time, if a jury agent consistently beats the live lane on the same pairs, it can be promoted to a shadow lane (paper-only) and eventually to a live lane candidate.

---

## 6. Concrete Implementation Plan

### Phase 0: Infrastructure (Week 1-2)

**Objective:** Get the ReAct loop running on the GRE with the existing warden infrastructure.

1. **Create shared agent module** `strategies/agentic_trader.py`
   - Extract `llm_json()` and `_extract_json()` from `strategies/fx_warden.py` into a shared base
   - Implement ReAct loop (max 5 iterations per decision)
   - Tool definitions as a dictionary of `{name: {fn, description, parameters}}`
   - Output format: `{"pair": "EUR_USD", "action": "BUY|SELL|HOLD", "conviction": 0.0-1.0, "rationale": "..."}`

2. **Point to existing llama.cpp endpoint** `http://127.0.0.1:5802/v1/chat/completions`
   - The warden already uses this (Granite 4.2-8B on GRE)
   - Reuse the same failover pattern (primary :5802, fallback :5804)

3. **Wire up tools** wrapping existing exchange methods:
   - `get_price` -> `exchange/oanda.py:get_current_price()`
   - `get_bars` -> `exchange/oanda.py:get_bars()`
   - `query_macro` -> `data/economics.py:fetch_fred_series()`
   - `get_calendar` -> `data/economic_calendar.py` or feed files
   - `check_risk` -> `risk/manager.py:RiskManager.check()`

### Phase 1: Offline Paper Jury (Week 3-4)

**Objective:** Run N agents on historical data from the accrual store, score them, validate the concept.

1. **Build agent runner** `strategies/jury_arena.py`
   - Load panel from `fxexpert/data.py:load_panel()`
   - Spawn N=4 agents (same model, different system prompts: "technical trader", "macro trader", "momentum trader", "contrarian trader")
   - Each agent runs ReAct on each day's feature vector
   - Score against next-day return
   - Record all decisions to `data/jury/decisions.jsonl`

2. **Tournament evolution** `strategies/jury_evolution.py`
   - After 200 days, rank agents by win rate
   - Bottom 2 retired, top 2 spawn mutated variants (prompt change + temperature change)
   - Repeat for 10 generations

3. **Compare against baselines**
   - Random agent (coin flip)
   - Buy-and-hold (always BUY)
   - fxexpert model score (if available)
   - Simple moving average cross strategy

### Phase 2: Live Shadow Lane (Week 5-6)

**Objective:** Run the winning agent(s) daily on live data, write decisions to the ledger for monitoring.

1. **Daily cron job** `scripts/agentic_trader_cron.py`
   - Schedule: after EOD bars available (17:10 UTC, matching `fx_runner`)
   - Reads current state (OANDA), recent bars, macro data
   - Runs the winning agent from Phase 1
   - Outputs decisions to `data/jury/live_decisions.jsonl`
   - Decision = consensus across the surviving jury agents

2. **Dashboard integration** `dashboard.py`
   - New endpoint `/api/jury` returning agent decisions and performance
   - Add to `tui/index.js` as a "Jury" panel (the human's client)
   - Show per-agent win rate, conviction, and current decision

3. **Ledger recording**
   - Write each decision as a jury record (not a trade -- no fills)
   - Schema: `{ts, pair, action, conviction, rationale, agents: [{id, vote, conv}], close_price, next_close}`

### Phase 3: GRPO Training (Week 7-8)

**Objective:** Train the agent on its own decision history using outcome-based RL.

1. **Build GRPO dataset** from `data/jury/decisions.jsonl`
   - Each decision is an (observation, action, outcome) triple
   - Group by regime (up/down market) for field-relative advantage
   - Filter low-activity periods (no decisions made = no training signal)

2. **GRPO fine-tune** using `arena/grpo.py` logic
   - Apply to the LLM's decision distribution (not the value-head MLP)
   - Target model: Qwen2.5-7B or currently deployed jury model
   - Training on RTX 3070 (8GB) with QLoRA via Unsloth
   - LoRA rank=16, alpha=16, batch_size=1, grad_accum=4

3. **Evaluate trained agent** vs untrained baseline on holdout data
   - We expect: better win rate, better conviction calibration (high-conviction decisions are more accurate)
   - We do NOT expect: positive P&L (that is the arena's job, not a single agent's)

### Phase 4: Consensus Signal for Live Lane (Week 9-10)

**Objective:** Use the jury consensus as a sizing modifier for the live fxexpert lane.

1. **Wire into fxexpert lane** `strategies/fx_expert_lane.py`
   - Before each 30-day rebalance, read jury consensus from `data/jury/live_decisions.jsonl`
   - For pairs where jury agrees with the fxexpert score: increase position size by 10%
   - For pairs where jury disagrees: decrease by 10%
   - This is the "cross-validation" signal -- two independent models agree

2. **Monitor impact** via the existing scoreboard
   - Track: "with jury adjustment" vs "without jury adjustment" (couterfactual)
   - Report to `data/warden/friday_scoreboard.json`

---

## 7. Hardware Feasibility Assessment

### RX 7900 GRE (16GB, ROCm)

| Task | VRAM Required | Feasible? |
|------|---------------|-----------|
| 7B Q4_K_M inference (llama.cpp HIP) | ~5 GB + context | YES, 11GB headroom |
| 7B Q4_K_M inference + 8K context | ~6 GB | YES |
| 4 concurrent 7B Q4_K_M (batch) | ~9 GB (shared model) | YES |
| 7B QLoRA fine-tune (Unsloth ROCm) | ~8 GB | TBC -- needs testing |
| 30B-A3B Q4 MoE + context | ~15 GB + context | NO -- no headroom |
| Gaming lock prevents use | N/A | Check `data/gpu/gaming.lock` before starting |

**Recommendation:** Use the GRE for inference only. The existing Granite 4.2-8B (:5802) or Qwen2.5-7B are ideal. Do NOT attempt fine-tuning on the GRE on the first iteration -- use the 3070.

### RTX 3070 (8GB, CUDA)

| Task | VRAM Required | Feasible? |
|------|---------------|-----------|
| 7B Q4_K_M inference (llama.cpp CUDA) | ~5 GB + context | YES, but tight |
| 7B QLoRA fine-tune | ~7 GB | YES, with batch_size=1 |
| Warden 4B + qwen3-embed (current) | ~5.1 GB | Running now |
| Jury agent on 3070 | ~5 GB | YES, but pause warden first |

**Recommendation:** Use the 3070 for fine-tuning (GRPO, QLoRA). The existing `.venv-cuda` environment already has torch 2.11.0+cu128. Pause warden and qwen3-embed before training (`systemctl --user stop opentrader-llama-gpu1 qwen3-embed`), restore after.

### GPU Coordination

```
GRE (16GB): Inference server (:5802 or :5801)
  - Primary: ~6GB for 7B Q4 + 8K context
  - Available: ~10GB for agent reasoning context
  
3070 (8GB): Fine-tuning
  - QLoRA training for 4-8 hours per generation
  - Pause warden/qwen3-embed, train, restore
  
Both GPUs: Paper jury
  - GRE: 4 parallel 7B agents (batch inference)
  - 3070: Scoring/tournament management (no GPU needed)
```

### Decision Latency Budget (Live, 17:10 cron)

```
1. Load model from VRAM (already loaded on :5802)    0.01s
2. Fetch venue state + bars (OANDA API)                1-2s
3. Agent ReAct loop (5 iterations, ~4K tokens total)   5-8s
   - per iteration: 2-3s for ~800 tokens
4. Output decision + log                               0.1s
Total: ~7-10s (well within the 17:10-21:25 window)
```

---

## 8. References

### Papers

1. Yao et al. 2022. "ReAct: Synergizing Reasoning and Acting in Language Models." arXiv:2210.03629.
2. DeepSeek-AI. 2025. "DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning." arXiv:2501.12948.
3. Yang et al. 2023. "FinGPT: Open-Source Financial Large Language Models." arXiv:2306.06094.
4. Shao et al. 2024. "DeepSeekMath: Pushing the Limits of Mathematical Reasoning." arXiv:2402.03300. (GRPO derivation)
5. Li et al. 2023. "TradingGPT: Multi-Agent System with Layered Memory and Distinct Characters for Enhanced Financial Trading Performance." arXiv:2309.03736.
6. FinMem: An LLM Agent for Financial Decision-Making. arXiv:2311.13743.
7. Patil et al. 2023. "Gorilla: Large Language Model Connected with Massive APIs." arXiv:2305.15334.
8. TradingAgents: Multi-Agents LLM Financial Trading Framework. arXiv:2412.20138.
9. Han et al. 2024. "LLM-Powered Multi-Agent System for Automated Crypto Portfolio Management." arXiv:2501.00826.

### Existing Codebase (all paths absolute)

- `exchange/oanda.py` -- OANDA v20 REST adapter (practice)
- `exchange/base.py` -- Exchange adapter ABC with OHLCV/OrderResult/Balance
- `strategies/fx_warden.py` -- Observe->plan->score LLM monitor pattern
- `strategies/lane_attribution.py` -- Tag-based fill attribution (shared resolver)
- `fxexpert/model.py` -- Temporal transformer for per-pair score prediction
- `fxexpert/data.py` -- Panel builder from the DuckDB accrual store
- `fxexpert/train.py` -- Walkforward training with group-rank loss
- `fxexpert/loop.py` -- Hyperparameter bandit + warm-start recursion
- `arena/grpo.py` -- GRPO implementation (DeepSeekMath style)
- `training/finetune_cycle.py` -- Unsloth QLoRA fine-tuning pipeline
- `model_manager.py` -- Model discovery, download, and launch
- `security/guards.py` -- Hardened network/file wrappers
- `data/economics.py` -- FRED macro data fetcher
- `data/economic_calendar.py` -- Event proximity/density features
- `mcp_server.py` -- MCP protocol for tool-use (alternative backend)
- `risk/manager.py` -- Risk checks before order placement

### Tools and Frameworks

- llama.cpp (ROCm HIP for GRE, CUDA for 3070)
- Unsloth (QLoRA fine-tuning with 70% less VRAM)
- Qwen2.5-7B (recommended starting model, strong tool-use, 32K context)
- Granite 4.2-8B (already deployed on :5802 as the warden model)
- DuckDB (`/home/mrc/opentrader-data/store.duckdb` -- the accrual store)

---

## Appendix A: First Prototype Command

```bash
# 1. Test the ReAct loop manually (one pair, one day)
PYTHONPATH=/home/mrc/opentrader \
  python3 -c "
from strategies.agentic_trader import AgenticTrader

agent = AgenticTrader(
    model_endpoint='http://127.0.0.1:5802/v1/chat/completions',
    model_id='granite-4.2-8b',
    persona='technical_trader',
    max_steps=5,
)

# Feed today's feature vector for EUR_USD
decision = agent.decide({
    'pair': 'EUR_USD',
    'price': 1.0523,
    'bars_1h': [...],  # last 24 bars
    'rsi_14': 45.2,
    'macd': -0.0012,
    'carry_pct_yr': 0.018,
    'regime': 'up',
})

print(json.dumps(decision, indent=2))
# Expected: {pair, action, conviction, rationale, steps_taken, tokens_used}
"

# 2. Run the paper jury on historical data
PYTHONPATH=/home/mrc/opentrader \
  python3 -m strategies.jury_arena \
    --panel /home/mrc/opentrader/fxexpert/data/fx_expert/panel.npz \
    --agents 4 \
    --days 200 \
    --output /home/mrc/opentrader/data/jury/
```

## Appendix B: Decision Schema

```jsonc
// data/jury/decisions.jsonl — append-only record of agent decisions
{
  "ts": "2026-09-16T17:10:00Z",
  "pair": "EUR_USD",
  "price": 1.0523,
  "action": "BUY",
  "conviction": 0.65,
  "rationale": "MACD bullish cross on 4H, RSI recovering from 38, carry positive",

  // Agent info
  "agent_id": "technical_trader-v3",
  "model": "granite-4.2-8b",
  "system_prompt_hash": "abc123",
  "temperature": 0.25,
  "steps_taken": 4,
  "tokens_used": 3820,

  // Scoring (filled later, when next close arrives)
  "close_price": null,         // filled on next close
  "scored_at": null,           // timestamp when scoring happened
  "outcome": null,             // 1.0 = win, -1.0 = loss, 0.0 = neutral
  "outcome_magnitude": null,   // |return| * conviction (P&L-like)
}
```