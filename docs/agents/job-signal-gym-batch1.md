# JOB — Signal gym batch 1: the model proposes candidates (≤15 tool calls, fresh session)

You are the signal generator for OpenTrader's Track B research. The machine
(scripts/signal_gym.py) verifies everything you write; you will never see
execution, only survivors. Your failures cost nothing; your survivors become
candidate experts. Propose boldly, but every candidate must be a distinct
hypothesis — duplicates are worthless.

If any prior conversation exists above this message → STOP, reply exactly:
"NOT A FRESH SESSION — open a new one and paste only this file."

## THE CONTEXT (from baseline 2026-08-31, 2y D1, 7 FX majors)

- mom_k5/k10/k20: dead. breakout_20: dead (IS 0.44). regime_mom_k10: dead.
- **mr_fade_ma20 is the only candidate positive in BOTH windows**
  (IS PF 1.18, OOS PF 2.27, WR 53.6% OOS) — mean-reversion works on majors.
- OOS-window momentum strength is a regime artifact, not skill.

## YOUR JOB — write 10 candidate files into
`/home/mrc/opentrader/data/signal_gym/candidates/`, named `c10_*.py` .. `c19_*.py`

Each file:
```python
NAME = "unique-name"
# one-line rationale comment
def entry(ctx) -> dict:   # {symbol: weight}; instruments to LONG only
```

Contract (the gym provides): `ctx.symbols` (7 majors), `ctx.i` (day index),
`ctx.close(sym)`, `ctx.close_n(sym, k)` (close k days back),
`ctx.ma(sym, n)` (SMA of n days, None if insufficient),
`ctx.atr(sym, n)`, `ctx.mom(sym, k)` (k-day return),
`ctx.series` (date-keyed OHLC), `ctx.dates`.

PURE functions only: no imports, no open/exec/eval (the gym rejects them).
Risk shape is uniform (ATR stop/target, $10k notional, 14d hold) — do NOT
encode exits; differentiate on ENTRY selection only.

## WHAT TO PROPOSE (diversity mandate)

The evidence says mean-reversion lives on majors. Explore it hard, but also
test genuinely different hypotheses — at least 6 of your 10 must be
mean-reversion variants (different MA lengths 10/30/50, different fade
thresholds, z-score forms, RSI(2)-style dips, Bollinger-tap, gap-fade),
up to 4 can be anything else you believe has a mechanism on majors
(volatility-conditioned, day-of-week, multi-pair relative value like
EUR/GBP spread trading, range contraction expansion). Give each a one-line
mechanism rationale — WHY it should work on FX majors.

## RULES

- ≤ 15 tool calls: 10 write_file + setup + final report.
- Every candidate syntactically valid Python (verify with one py_compile pass).
- Final reply: list of the 10 candidate names + one-line rationale each.
  Nothing else.
