# Trader-agent prototype — first run (2026-09-16)

## Implemented

- `strategies/trader_agent/features.py`: causal daily context from the DuckDB
  accrual store: 60 D1 bars, returns, ATR, volume ratio, and structured FRED
  macro values. First context observed WTI **97.26**, VIX **17.8**, yield curve
  **+0.33**; `oil_shock=true`, `risk_off=false`.
- `strategies/trader_agent/agent.py`: OpenAI-compatible structured paper vote.
  It can only return BUY/SELL/HOLD + conviction; it has no order tool and no
  exchange write path.
- `strategies/trader_agent/scorer.py`: conviction-weighted next-close scoring.
- `scripts/run_trader_paper.py`: paper vote runner; writes
  `data/trader_agent/votes.json` and never places orders.
- `scripts/run_trader_backtest.py`: causal one-day momentum baseline.
- `tests/test_trader_agent.py`: four scorer tests.

## First measured results

The baseline is deliberately simple and negative, which is useful evidence:

| pair | periods | accuracy | mean outcome |
|---|---:|---:|---:|
| EUR_USD | 199 | 42.71% | -0.072864 |
| USD_JPY | 199 | 46.73% | -0.032663 |

This confirms the agent must not inherit a one-day rank/momentum rule as its
starting strategy.

A paper-only smoke vote through the healthy 3070 fallback (`:5804`) succeeded:
EUR_USD → **HOLD, conviction 0.0**. Its thesis used the observed WTI $97.26 oil
shock and noted that bearish momentum conflicted with the macro regime. No order
was sent.

## Validation

- Trader-agent tests: **4 passed**.
- Full suite: **96 passed, 6 warnings**.
- GRE worker was intentionally unloaded for gaming; no production schedule was
  enabled. The fallback was used only for one paper vote.

## Next gate

Do not schedule daily votes yet. First run the model over a fixed historical
walk-forward sample with the same context schema, score against next-close
returns, and compare against:

1. random BUY/SELL/HOLD baseline;
2. hold/no-trade baseline;
3. incumbent g151/rank signal;
4. macro-regime-only baseline.

Only a positive, stable out-of-sample record should create a daily paper-vote
cron. The prototype remains paper-only and cannot submit OANDA orders by design.
