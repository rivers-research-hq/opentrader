# Small-Capital Profitability Research ($500 Scale)

**Date:** 2026-08-28
**Status:** Complete — 8/12 web queries executed, 6/10 fetches successful
**Companion docs:** [evolution-thesis.md](../evolution-thesis.md), [jane-street-playbook.md](jane-street-playbook.md), [prop-firm-challenge-research.md](prop-firm-challenge-research.md)

---

## 1. Research Method & Source Audit

### Queries executed (8/12)

| # | Query | Status | Key sources |
|---|---|---|---|
| 1 | small account trading strategy 500 dollars fee-aware profitability | OK | tradealgo.com (JS-blocked), 5× Reddit (JS-blocked) |
| 2 | crypto spot momentum trend strategy backtest small account results | OK | coinquant.ai (fetched), stoic.ai, 4× Reddit |
| 3 | perpetual futures funding rate arbitrage small capital requirements | OK | coincryptorank.com (fetched), gate.com (403), btcc.com, arbitragescanner.io |
| 4 | ETF rotation strategy backtest results small account low turnover | OK (after 429) | quantifiedstrategies.com (bot-verify), logical-invest.com, 4× Reddit |
| 5 | market making strategy retail investor small account order book spread capture | OK | quantt.co.uk (fetched, thin), epam.com, 4× Reddit |
| 6 | fee-aware trading strategy design minimum notional round trip cost | TIMEOUT (429) | — |
| 7 | slippage market impact small order crypto exchange cost | OK | kraken.com (fetched, thin), coinbase.com (fetched), 4× Reddit |
| 8 | low activity trading strategy reduce turnover hold streak fee drag | OK | financialmodelslab.com, prismafinancehub.com, 4× Reddit |
| 9 | cross asset diversification small portfolio 500 dollars | 429 (3 attempts) | — |
| 10 | (fee impact threshold) | 429 (2 attempts) | — |
| 11 | (prop firm — already in prop-firm-challenge-research.md) | SKIPPED | existing doc |
| 12 | (options at $500 — PDT wall, already in evolution-thesis.md) | SKIPPED | existing doc |

### Fetch results (6/10 successful)

| URL | Result |
|---|---|
| coincryptorank.com/blog/funding-rate-arbitrage | OK — 9905 chars, detailed funding arb mechanics |
| coinquant.ai/blog/crypto-trading-strategies-every-type-explained-2026-guide | OK — 9014 chars, full strategy taxonomy |
| help.coinbase.com/.../understanding-slippage-and-spread | OK — 2685 chars, slippage mechanics |
| kraken.com/learn/what-is-slippage-in-crypto | OK — 795 chars (thin, mostly nav) |
| quantt.co.uk/resources/market-making-strategy-guide | OK — 437 chars (thin, mostly nav) |
| quantifiedstrategies.com/etf-rotation-strategy/ | BLOCKED — bot verification |
| gate.com/learn/.../funding-rate-arbitrage | BLOCKED — 403 |
| tradealgo.com/.../trading-small-account | NO TEXT — JS-rendered |
| reddit.com (all 7 attempts) | NO TEXT — JS-rendered |
| old.reddit.com (2 attempts) | OK but CSS/JS noise, no readable content |

**Fetch success rate: 6/10 (60%)** — 2 blocked, 2 JS-rendered, 2 thin.
**Search success rate: 8/12 (67%)** — 4 rate-limited (Brave 429).

### Data quality note
Reddit (the richest source for practitioner experience) is entirely JS-rendered and unreadable via this fetch pipeline. The quantitative data below comes primarily from:
- **coincryptorank.com** — funding rate mechanics (detailed, 29 sections)
- **coinquant.ai** — strategy taxonomy with regime mapping
- **coinbase.com** — slippage/spread mechanics
- **opentrader internal docs** — fee structures, instrument gates, validated backtests
- **HEURISTIC labels** — where no source was found, the number is labeled as such

---

## 2. Fee Viability at $500 (the binding constraint)

### Fee structures (from opentrader docs + exchange sources)

| Venue | Fee type | Rate | Round-trip cost on $100 position |
|---|---|---|---|
| Kraken spot | % taker | 0.26% | $0.52 (0.52%) |
| Kraken spot | % maker | 0.16% | $0.32 (0.32%) |
| US stocks (Finnhub) | Fixed | $0.35/side | $0.70 (0.70% on $100) |
| Kraken futures | % taker | ~0.02-0.05% (HEURISTIC) | ~$0.04-0.10 (0.04-0.10%) |

**Key insight (from evolution-thesis.md):** At $500 with 6-9 positions (~$55-83/position), a US stock round-trip fee of $0.70 is **0.84-1.27% of position value**. This is the dominant cost. Crypto spot at 0.26% taker is **0.52% round-trip** — 1.6-2.4× cheaper per trade.

### Minimum viable position size

- **US stocks:** $0.35/side fee on a $50 position = 0.70% one-way, 1.40% round-trip. You need a **>1.4% edge per trade** just to break even. At 20 trades/month, that's 28% annual fee drag. **Not viable below ~$200/position.**
- **Crypto spot:** 0.26% taker on a $50 position = 0.26% one-way, 0.52% round-trip. You need a **>0.52% edge per trade**. At 20 trades/month, that's 10.4% annual fee drag. **Viable from ~$50/position.**
- **Kraken futures:** ~0.02-0.05% taker (HEURISTIC — Kraken futures fee schedule not directly fetched). On a $50 position with 10x leverage ($500 notional), fee is ~$0.01-0.025 one-way. **Viable from ~$10/position (margin).**

**Conclusion:** At $500 total, **crypto spot is the only instrument where fee drag is manageable** with 6-9 positions. US stocks require either fewer, larger positions (2-3 at $150-250) or a very low-turnover strategy.

---

## 3. Strategy Menu (mapped to opentrader stack)

### A. Crypto Spot Momentum/Trend (CURRENT — validated)

**What:** momtrend.py — momentum-top + market-breadth entry gate.
**Backtest (from opentrader docs):**
- R1 (US 2008-26): ann 23.2% / Calmar 0.469 / 4/4 folds
- OOS (intl 2021-26): ann 11.0% / Calmar 0.852 / Sharpe 1.05 / maxDD -13.0%
- Best params: mom=60, k=5, rebal=20, breadth_thr=0.6, breadth_win=100
- Honesty: signals at prior close, fills at current close, 0.35%/side fees

**At $500:** 3-5 crypto positions at $100-167 each. Round-trip fee 0.52% (taker). With 20-day rebalance, ~18 trades/year. Annual fee drag: ~9.4% (HEURISTIC: 18 × 0.52%). Net edge after fees: ~1.6-11.6% (range from R1 to OOS).

**Verdict:** **VIABLE.** This is the current validated setup. The OOS 11% annual with 0.852 Calmar is the honest number. Fee drag is the main risk — if rebalance frequency increases, fees eat the edge.

**30-day gate:** Run shadow A/B for 30 days. Pass if: (1) equity ≥ $500 (no drawdown > 5%), (2) ≥ 3 fills executed, (3) realized P&L ≥ 0 after fees.

---

### B. Funding Rate Arbitrage (Kraken Futures — gated ~$500-1k)

**What:** Delta-neutral: long spot + short perpetual. Collect funding every 8 hours.
**Source (coincryptorank.com, fetched):**
- Funding cycles: 8h (00:00, 08:00, 16:00 UTC)
- Typical rates: 0.01%-0.1% per cycle → **1-45% annually** (source: coincryptorank.com)
- Setup: Buy $X spot, short $X perp with 2-5x leverage
- For $500: Buy $250 BTC spot, short $250 BTC perp (2x lev = $125 margin)
- Rebalance when drift > 2-5%
- Basis risk: large persistent premiums may reverse

**At $500:**
- $250 spot + $250 perp short (2x lev) = $375 margin used, $125 buffer
- At 0.01%/8h funding: $250 × 0.01% × 3/day × 365 = **$27.4/year (5.5% on $500)**
- At 0.05%/8h (HEURISTIC: mid-range): **$137/year (27.4% on $500)**
- At 0.1%/8h (peak): **$274/year (54.8% on $500)**
- **Realistic range: 5-27% annual** (HEURISTIC: depends on funding regime)

**Verdict:** **VIABLE at $500 but GATED.** Requires:
1. Kraken futures access (274 swaps via ccxt.krakenfutures())
2. Paper-validate perp fills + liquidation model first (per evolution-thesis.md)
3. Funding rate monitoring (already prototyped: `[FUNDING]` in opentrader)
4. Rebalancing automation (drift > 2-5%)

**Risk:** Funding rates can go negative (shorts pay longs). In a bear market, the arb flips. Basis risk if spot/perp diverge.

**30-day gate:** Paper-trade with $500 virtual. Pass if: (1) ≥ 30 funding collections recorded, (2) net P&L ≥ 0 after fees, (3) max drawdown < 3%, (4) no liquidation events.

---

### C. ETF Rotation (US Stocks — gated ~$1-5k)

**What:** Rotate between sector/thematic ETFs based on momentum.
**Source (quantifiedstrategies.com — BLOCKED, bot verification; logical-invest.com — not fetched):**
- Typical ETF rotation: 4-12 ETFs, monthly/quarterly rebalance
- Low turnover: 12-48 trades/year
- At $500 with $0.35/side: 24 trades × $0.70 = $16.80/year = **3.36% fee drag**
- Need >3.36% edge per year just to break even on fees

**At $500:** 2-3 ETF positions at $167-250 each. With monthly rebalance (12/year), 24 round-trips = $16.80 fees. **Fee drag 3.36%/year.**

**Verdict:** **MARGINAL at $500.** Fee drag is 3.36%/year — you need a >3.36% edge. Most ETF rotation strategies claim 5-15% annual, but after fees and slippage, the net is 2-12%. **Not recommended below $1k.** At $1k+, fee drag drops to 1.68% and the strategy becomes viable.

**30-day gate (if pursued at $1k+):** Paper-trade with $1k virtual. Pass if: (1) equity ≥ $1k, (2) ≥ 2 rebalances executed, (3) realized P&L ≥ 0 after fees.

---

### D. Market Making / Spread Capture (NOT VIABLE at $500)

**What:** Quote bid/ask, capture spread.
**Source (quantt.co.uk — fetched, thin; jane-street-playbook.md — internal):**
- Requires: colocation, low-latency infra, maker rebates, inventory management
- Jane Street playbook (internal doc): "Cannot replicate: speed, flow knowledge, capital, maker/rebate infra"
- At $500: inventory risk dominates. A single adverse move of 1% on a $100 position = $1 loss = 1% of account.
- Kraken maker fee: 0.16% — you need to capture >0.16% spread per side to break even.

**Verdict:** **NOT VIABLE at $500.** Requires institutional infrastructure. The opentrader stack has no order-book quoting capability. Defer until $10k+ with dedicated MM infrastructure.

---

### E. Cross-Asset Diversification (HEURISTIC)

**What:** Split $500 across crypto spot + US stocks + (later) futures.
**No direct source found** (query 9 rate-limited). Based on evolution-thesis.md instrument gates:

| Allocation | Instrument | Rationale |
|---|---|---|
| $300 (60%) | Crypto spot (BTC/ETH/SOL) | Current validated setup, lowest fees |
| $100 (20%) | US stocks (1-2 large caps) | Diversification, $0.35 fee amortized on $100 |
| $100 (20%) | Cash reserve | Buffer for fees, slippage, opportunities |

**At $500:** 3 crypto + 1-2 stock positions. Fee drag: crypto 0.52% × 18 trades + stocks 0.70% × 6 trades = 9.36% + 4.2% = **13.56% annual** (HEURISTIC). This is high — the stock allocation adds fee drag without proportional edge.

**Verdict:** **MARGINAL.** The stock allocation at $100 is too small to amortize the $0.35 fee. Better to go 100% crypto spot at $500 and add stocks at $1k+.

---

### F. Options at $500 (NOT VIABLE)

**What:** Covered calls, cash-secured puts.
**Source (evolution-thesis.md):** PDT rule ($25k) is the hard wall. At $500, you're limited to 3 day-trades/week.
**Verdict:** **NOT VIABLE.** PDT wall + margin requirements + complexity. Defer to $25k+.

---

## 4. TOP-3 Recommendations with $500 Allocation

### #1: Crypto Spot Momentum (CURRENT — continue)

**Allocation:** $500 (100%)
- BTC/USDT: $167
- ETH/USDT: $167
- SOL/USDT: $166

**Strategy:** momtrend.py (validated: OOS 11% ann, Calmar 0.852)
**Fees:** 0.26% taker, 0.52% round-trip
**Expected annual return (after fees):** 5-11% (HEURISTIC: OOS 11% minus ~5% fee drag)
**Max drawdown (backtest):** -13.0%
**30-day gate:**
1. Equity ≥ $475 (max 5% drawdown)
2. ≥ 3 fills executed
3. Realized P&L ≥ 0 after fees
4. No circuit breaker trips

**Why #1:** Already validated, already running, lowest fee drag, no new infrastructure needed.

---

### #2: Funding Rate Arbitrage (NEW — paper-validate)

**Allocation:** $500 (100%) — run in parallel with #1 as a separate shadow
- $250 BTC spot (long)
- $250 BTC perpetual (short, 2x leverage = $125 margin)
- $125 cash buffer

**Strategy:** Delta-neutral funding collection
**Fees:** ~0.02-0.05% taker (HEURISTIC) + funding payments
**Expected annual return:** 5-27% (HEURISTIC: depends on funding regime)
**Max drawdown (target):** < 3% (delta-neutral)
**30-day gate:**
1. ≥ 30 funding collections recorded
2. Net P&L ≥ 0 after fees
3. Max drawdown < 3%
4. No liquidation events
5. Drift rebalancing ≤ 5 times (indicates stable hedge)

**Why #2:** Highest risk-adjusted return potential. Delta-neutral = low drawdown. But requires Kraken futures access (gated) and paper validation first.

**Prerequisite:** Paper-validate perp fills + liquidation model (per evolution-thesis.md gate).

---

### #3: Crypto Spot + Cash Reserve (CONSERVATIVE)

**Allocation:** $500
- $350 (70%) in crypto spot (2-3 positions)
- $150 (30%) cash reserve

**Strategy:** momtrend.py with reduced exposure
**Fees:** 0.26% taker, 0.52% round-trip (on $350 deployed)
**Expected annual return (after fees):** 3.5-7.7% (HEURISTIC: 70% × 5-11%)
**Max drawdown (backtest):** -9.1% (70% × -13%)
**30-day gate:**
1. Equity ≥ $475 (max 5% drawdown)
2. ≥ 2 fills executed
3. Realized P&L ≥ 0 after fees
4. Cash reserve maintained ≥ $100

**Why #3:** Lower risk, preserves capital for opportunity. The 30% cash reserve reduces fee drag (fewer positions) and provides dry powder for funding arb entry when #2 validates.

---

## 5. What's NOT Viable at $500 (and why)

| Strategy | Why not | Gate to revisit |
|---|---|---|
| US stock day trading | $0.35/side = 0.7% on $50 pos; PDT wall | $1k+ (fee amortization) |
| Market making | No infra, inventory risk dominates | $10k+ (MM infra) |
| Options | PDT $25k wall, margin requirements | $25k+ |
| ETF rotation (below $1k) | 3.36% fee drag eats most edge | $1k+ |
| High-frequency scalping | Slippage + fees > edge at small size | $5k+ (better fills) |

---

## 6. Fee-Aware Design Principles (for opentrader)

1. **Round-trip fee cap:** Reject any trade where round-trip fee > 20% of expected edge. (Already in opentrader: "round-trip fee ≤ 20% of notional")
2. **Min-notional floor:** Don't trade positions < $50 (crypto) or < $200 (stocks). (Already in opentrader: "$300 min-viable deposit")
3. **Low-activity gating:** HOLD-streak rescout — if no signal for N cycles, stay flat. Reduces fee drag from 18 trades/year to ~12.
4. **Maker preference:** Use limit orders (0.16% maker) instead of market orders (0.26% taker) when possible. Saves 38% on fees.
5. **Rebalance frequency cap:** Don't rebalance more than once per 20 days (current momtrend setting). More frequent = more fees.
6. **Fee drag budget:** Total annual fee drag should be < 10% of account. At $500 with crypto spot, 18 trades × 0.52% = 9.36% — right at the limit.

---

## 7. Slippage & Impact (from coinbase.com + kraken.com)

- **Slippage** = difference between expected and actual execution price
- **Caused by:** liquidity, volatility, order size relative to book depth
- **At $500 with $100-167 positions:** Slippage on BTC/ETH/SOL is negligible (< 0.01%) — these are the most liquid pairs on Kraken
- **Coinbase threshold:** Orders canceled if slippage > 10% (their safeguard)
- **Kraken:** No published slippage threshold, but market orders on BTC/ETH/SOL execute at mid ± spread
- **Impact:** At $100-167 order size, market impact is < 0.01% on BTC/ETH/SOL (HEURISTIC: these pairs have $10M+ depth within 1% of mid)

**Conclusion:** Slippage/impact is NOT a binding constraint at $500 on major crypto pairs. Fees are the dominant cost.

---

## 8. Next Steps

1. **Immediate:** Continue running momtrend.py shadow A/B (current validated setup). Track 30-day gate metrics.
2. **This week:** Paper-validate Kraken futures perp fills + liquidation model (prerequisite for funding arb).
3. **Next 2 weeks:** If funding arb paper validation passes, allocate $250 to a separate shadow A/B for funding rate collection.
4. **Month 2:** Review 30-day gate results. If #1 passes and #2 is validated, consider splitting $500: $350 momentum + $150 funding arb.
5. **Month 3:** If both pass, scale to $1k (add US stocks at $200-300 positions, start ETF rotation).

### Open items (not resolved by this research)
- [ ] Kraken futures fee schedule (HEURISTIC used: 0.02-0.05% taker) — verify with Kraken API
- [ ] Funding rate historical data for BTC/ETH on Kraken (needed for realistic arb backtest)
- [ ] ETF rotation backtest with $0.35/side fees (not yet run in opentrader)
- [ ] Cross-asset correlation at $500 scale (query 9 rate-limited, no source found)
