# Trader-agent walk-forward gate — 2026-09-16

## Protocol

`python3 scripts/trader_walkforward.py --start 2018-01-01 --end 2026-09-01`

- 10 representative FX pairs, 22,627 pair-days.
- Every feature is as-of date t; the score is the close-to-close return from t to t+1.
- No LLM, no network, no orders. This is a cheap causal gate before inference.
- HOLD is abstention and earns zero; it is not scored as a wrong directional trade.
- Macro data is as-of joined from the DuckDB `exog` table: WTI, VIX, T10Y2Y.

## Results

| policy | mean conviction outcome | directional accuracy |
|---|---:|---:|
| 1-day/5-day momentum | **-0.003514** | 49.65% |
| VIX/curve risk-off HOLD | **-0.004685** | 30.18% |
| oil-shock suppression | **-0.004000** | 47.37% |

Regime coverage: 8,757 risk-off observations and 3,360 oil-shock observations.

## Decision

**No policy passes. Do not schedule daily LLM votes yet.** The result does not
show that macro data is useless; it shows that blunt thresholds (`VIX > 25`,
`curve < 0`, `WTI > 85`) are not a trading strategy. The next prototype must
learn regime interactions out of sample rather than hard-code one-variable
switches.

The LLM remains a paper-only judge. The next valid experiment is a historical
replay where the agent receives the same context schema and votes on a bounded
sample, with output stored separately from the gate. Compare its track record
against these negative baselines and a no-trade baseline before any scheduler
is enabled.

Artifact: `data/trader_agent/walkforward.json`.
Validation: full suite **96 passed**.
