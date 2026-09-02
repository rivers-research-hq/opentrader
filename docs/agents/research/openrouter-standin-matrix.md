# OpenRouter stand-in — model lineup + pricing for coder / trader / court

Source: `https://openrouter.ai/api/v1/models` (fetched 2026-08-23, 422 models).
Pricing = USD per token (OpenRouter `pricing.prompt` / `pricing.completion`).

## CRITICAL — the stand-in is blocked on CREDITS, not model choice

All three research subagents launched this session failed instantly with:

> "This request requires more credits, or fewer max_tokens. You requested up to
> 32000 tokens, but can only afford 708."

The OpenRouter account balance is ~**708 tokens** (effectively zero). **Top up
`openrouter.ai/settings/credits` before any stand-in testing.** Until then, no
OpenRouter model can be used, regardless of which one the map picks.

## Pricing for the candidate models (per-token; ~ per-1M in parentheses)

| Model | in | out | ctx | Role fit |
|---|---|---|---|---|
| `deepseek/deepseek-v4-flash` | 4.9e-8 (~$0.049/M) | 9.8e-8 (~$0.098/M) | 1.05M | **trader/regime-router** (cheapest) |
| `~deepseek/deepseek-v4-flash-latest` | 4.0e-8 | 8.0e-8 | 1.31M | trader (latest alias) |
| `qwen/qwen3.7-flash` | 3.0e-8 | 1.3e-7 | 1.0M | trader (cheapest alt) |
| `deepseek/deepseek-v4-pro` | 4.0e-7 (~$0.40/M) | 7.9e-7 (~$0.79/M) | 1.05M | **agentic coder** (this session's model) |
| `anthropic/claude-sonnet-5` | 2.0e-6 ($2/M) | 1.0e-5 ($10/M) | 1.0M | **court reviewer** / hard debugging |
| `anthropic/claude-haiku` (`~…-latest`) | 1.0e-6 ($1/M) | 5.0e-6 ($5/M) | 200K | cheap court |

## Recommended default per role (cheap-first)

- **Trading operator / regime-router** — `deepseek/deepseek-v4-flash` (cheapest;
  matches the "deepseek-v4-flash cheapest DigitalOcean path" note in the
  "Court of managers" map). Escalate to `deepseek-v4-pro` only on routing
  ambiguity.
- **Agentic coder** — `deepseek/deepseek-v4-pro` (hard reasoning + tool use;
  what this session runs on). Escalate to `claude-sonnet-5` for stubborn bugs.
- **Court / manager reviewer** — `claude-sonnet-5` for independent judgment
  (distinct reasoning family from the worker); `claude-haiku` for cheap pass.

## Provider pinning

- Pin `provider:{only:["DigitalOcean"]}` for deepseek models (per the
  "Court of managers" map note: DigitalOcean is the cheapest deepseek route).
- No account guardrails surfaced this session beyond the credit balance above.

## Budget note

`deepseek-v4-pro` at ~$0.40/$0.79 per M is ~8–10× `v4-flash` at ~$0.049/$0.098.
For the stand-in period, run the **trader + cheap court on flash**, the **coder +
hard court on pro/sonnet**, and keep the sonnet calls to the rare escalation path.
