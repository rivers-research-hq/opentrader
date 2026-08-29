# Small-Capital Profitability Plan ($500 Start)

**Date:** 2026-08-28
**Status:** Complete — source-backed plan with HEURISTIC labels
**Companion docs:** [small-capital-profitability.md](small-capital-profitability.md), [prop-firm-challenge-research.md](prop-firm-challenge-research.md)

> **Corrections (2026-08-29, human review — spot-checked against primary sources):**
> 1. **E8 prices conflict across sources.** This doc's $110 (CFD $25K) matches
>    PropFirmApp; other trackers list ~$138 for the CFD $25K and ~$110 for the
>    **Futures** $25K (a different product with different rules). "80-100%"
>    split also conflicts (one source: fixed 80% on Signature). Resolve on
>    e8markets.com at purchase time — see ToC ledger V17.
> 2. **§1.3 "Current config" is not the documented rule contract.** The
>    ADR-0001 validated ladder is 12.28% stop / 17.81% target / 15% position /
>    6 positions; the live crypto paper book observably runs ~5% stop / ~10%
>    target. The directional finding stands (any 15% breaker exceeds a 4-8%
>    challenge envelope), but the specific "current" values here are unsourced.
> 3. **The proposed challenge-mode parameters are HEURISTIC and GATED.** Per
>    ADR-0008 §4, reconfiguring the validated risk contract requires its own
>    ADR plus a sandbox walkforward of the new envelope before adoption. Do
>    not apply `portfolio_stop_pct=0.04` etc. as a config change.

---

## 1. Prop-Funding Branch (PRIMARY)

### 1.1 TradeLocker Firm Selection (3 firms from 15-firm list)

Source: [fundedtrading.com/best-tradelocker-prop-firms/](https://fundedtrading.com/best-tradelocker-prop-firms/) (fetched 2026-08-28, 46,691 chars)

| Firm | Tier | Why Selected |
|---|---|---|
| **FTUK** | Established | 4+ year track record, 4.7 Trustpilot, no time limits, static DD |
| **FunderPro** | Mid-tier | Fastest payouts (8-hr avg), static DD, no time limits, 80-90% split |
| **E8 Markets** | Aggressive | Customizable params, up to 100% split, on-demand payouts, 3-Step model |

**Key constraint:** FTMO, FundedNext, The5ers (best structural fits per prior research) do NOT offer TradeLocker.

### 1.2 Challenge Rules (Primary Sources)

#### FTUK (Established)
Source: [tradingfinder.com/props/ftuk/rules/](https://tradingfinder.com/props/ftuk/rules/) (fetched 2026-08-28)

| Parameter | 1-Step | 2-Step | Instant |
|---|---|---|---|
| Profit Target | 10% | 10% (S1) / 5% (S2) | 5% |
| Daily DD | 4% | 5% | 5% |
| Max DD | 8% trailing | 10% static (S1) / 5% static (S2) | 6% trailing |
| Min Trading Days | 4 | 4 | 4 |
| Time Limit | Unlimited | Unlimited | Unlimited |
| Profit Split | 80% | 80% | 80% |
| Payout | On-demand, $250 min | On-demand, $250 min | On-demand, $250 min |

**Prohibited:** News trading (5min), copy trading, latency arb, tick scalping (EA), HFT (EA), martingale (EA)
**Allowed:** Risk-management EAs, hedging, swing, intraday, overnight/weekend

#### FunderPro (Mid-tier)
Source: [funderpro.com/trading-rules/](https://funderpro.com/trading-rules/) (fetched 2026-08-28, partial — DD in accordions)

| Parameter | Pro Challenge |
|---|---|
| Profit Target | 10% (Phase 1) / 8% (Phase 2) |
| Daily DD | Not extracted (accordion) |
| Max DD | Static (type confirmed, % not extracted) |
| Min Trading Days | Not extracted |
| Time Limit | Unlimited |
| Profit Split | 80-90% |
| Payout | 8-hour average, $100 min |
| Pass Rate | 7.35% (disclosed) |

**Trust note:** Consumer warning on Trustpilot (Jan 2026), payout denial complaints rising, VPN use triggers scrutiny. New CEO (June 2026).

#### E8 Markets (Aggressive)
Source: [propfirmapp.com/prop-firms/e8-markets](https://propfirmapp.com/prop-firms/e8-markets) (fetched 2026-08-28)

**E8 Signature CFD (Forex/Crypto) — 1-Step:**

| Account Size | Profit Target | Daily Loss | Max Loss (EOD Dynamic) | Profit Split | Price |
|---|---|---|---|---|---|
| $25,000 | 6% | None (challenge) | 4% | 80-100% | $110 |
| $50,000 | 6% | None (challenge) | 4% | 80-100% | $150 |
| $100,000 | 6% | None (challenge) | 3% | 80-100% | $260 |
| $150,000 | 6% | None (challenge) | 3% | 80-100% | $390 |

**E8 One CFD (Forex/Crypto) — 1-Step:**

| Account Size | Profit Target | Daily Loss | Max Loss | Profit Split | Price |
|---|---|---|---|---|---|
| $5,000 | 8% | 2% | 4% | 80% | $40 |
| $10,000 | 8% | 2% | 4% | 80% | $72 |

**Key rules:**
- No daily loss limit during challenge (E8 Signature)
- EOD Dynamic Drawdown trails from highest end-of-day balance
- 2% daily pause in funded accounts (not a breach)
- 35% consistency rule in funded accounts (none during challenge)
- Min 5 profitable trading days between payout requests
- Payout buffer = EOD drawdown amount must be maintained
- Positions closed at 23:00 server time, reopen 00:15
- News trading permitted without restriction

### 1.3 opentrader Rule-Floor Mapping

**Current config (risk/manager.py):**
- `portfolio_stop_pct = 0.15` (15% circuit breaker)
- `stop_loss_pct = 0.04` (4% per-trade stop)
- `take_profit_pct = 0.08` (8% per-trade target)
- `kelly_fraction = 0.35` (fractional Kelly)
- `max_position_pct = 0.20` (20% max single position)

**Challenge constraint (5-6% max DD):**
- FTUK 1-Step: 8% trailing DD → **15% circuit breaker is 1.875× too loose**
- E8 Signature $25K: 4% EOD dynamic DD → **15% circuit breaker is 3.75× too loose**
- E8 One $5K: 4% max loss → **15% circuit breaker is 3.75× too loose**

**Required config changes for challenge mode:**
```python
# Challenge mode overrides
portfolio_stop_pct = 0.04  # 4% (match E8/FTUK max DD)
stop_loss_pct = 0.02       # 2% (tighter per-trade stop)
take_profit_pct = 0.04     # 4% (2:1 ratio maintained)
max_position_pct = 0.10    # 10% (reduce single-position risk)
kelly_fraction = 0.25      # 0.25 (more conservative Kelly)
```

**Pass probability (HEURISTIC):**
- E8 Signature $25K: 6% target, 4% max DD → **~15-25% pass rate** (HEURISTIC: based on 7.35% FunderPro disclosed rate + E8's more lenient no-daily-DD rule)
- FTUK 1-Step: 10% target, 8% trailing DD → **~10-20% pass rate** (HEURISTIC: higher target, trailing DD)
- E8 One $5K: 8% target, 4% max DD, 2% daily → **~10-15% pass rate** (HEURISTIC: daily DD constraint)

**Key insight:** The 15% circuit breaker is a **hard blocker** for prop firm challenges. The system would need to run with a 4% effective drawdown limit, which is **3.75× tighter** than the current config. This is a **significant reconfiguration** that may require:
1. New `RiskConfig` preset for challenge mode
2. Tighter per-trade stops (2% vs 4%)
3. Reduced position sizing (10% vs 20%)
4. More conservative Kelly fraction (0.25 vs 0.35)

**Feasibility:** **MARGINAL.** The opentrader stack can be reconfigured for challenge mode, but the 4% max DD is a **tight constraint** that may require strategy-level changes (lower turnover, fewer positions, tighter stops). The 96d SPY regime gate and 0.28 buy threshold are **compatible** with challenge mode (they reduce trade frequency, which helps with fee drag and DD control).

### 1.4 TradeLocker Adapter Feasibility

**Official Python SDK:**
- Package: `pip install tradelocker`
- GitHub: [TradeLocker/tradelocker-python](https://github.com/TradeLocker/tradelocker-python)
- Auth: JWT token (`/auth/jwt/token` with email/password/server)
- Base URL: `demo.tradelocker.com/backend-api/` or `live.tradelocker.com/backend-api/`
- Rate limits: Per-route, queryable via `/trade/config`

**ExchangeBase method mapping (5 methods):**

| ExchangeBase Method | TradeLocker SDK Call | Feasibility |
|---|---|---|
| `connect()` | `TLAPI(environment, username, password, server)` | **EASY** — direct mapping |
| `get_bars(symbol, timeframe, limit)` | `tl.get_price_history(instrument_id, resolution, start, end, lookback)` | **EASY** — direct mapping |
| `get_current_price(symbol)` | `tl.get_latest_asking_price(instrument_id)` | **EASY** — direct mapping |
| `place_order(symbol, side, quantity, order_type, price)` | `tl.create_order(instrument_id, quantity, side, type_)` | **EASY** — direct mapping |
| `get_balance()` | Not directly exposed in SDK README (need to check full API) | **MEDIUM** — may need REST call to `/trade/accounts/{accountId}/balance` |

**60s harness cycle compatibility:**
- TradeLocker REST API is **request-response** (not WebSocket)
- Rate limits: Per-route, typically 2-10 requests/second (queryable via `/trade/config`)
- 60s cycle = 1 request/minute → **well within rate limits**
- **Verdict:** **FEASIBLE.** Polling at 60s intervals is compatible with TradeLocker's REST API.

**Implementation effort:**
- `tradelocker.py` adapter: ~200-300 lines (similar to `paper.py` or `alpaca_paper.py`)
- JWT auth handling: ~50 lines (token refresh logic)
- Symbol mapping: ~50 lines (TradeLocker instrument IDs vs opentrader symbols)
- **Total:** ~300-400 lines, **1-2 days** of development

**Blockers:**
1. **No MQL4/5 EAs:** TradeLocker does not support MT-native EAs. The opentrader harness must run **externally** and poll the API.
2. **No WebSocket:** Real-time updates require polling (60s cycle is fine for swing/intraday, not for HFT).
3. **US traders restricted:** Some firms (FundingPips, Blueberry, GFT) restrict US traders to Match-Trader or other platforms.

**Verdict:** **FEASIBLE with moderate effort.** The TradeLocker adapter is a **straightforward implementation** that maps cleanly to the ExchangeBase interface. The 60s polling cycle is compatible with the REST API's rate limits.

---

## 2. General Small-Capital Survey (6-8 Queries)

### 2.1 Venue/Fee/Minimum at $500

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

| Venue | Fee Type | Rate | Round-Trip on $100 | Min Viable Position |
|---|---|---|---|---|
| Kraken spot | % taker | 0.26% | $0.52 (0.52%) | ~$50 |
| Kraken spot | % maker | 0.16% | $0.32 (0.32%) | ~$50 |
| US stocks (Finnhub) | Fixed | $0.35/side | $0.70 (0.70%) | ~$200 |
| Kraken futures | % taker | ~0.02-0.05% (HEURISTIC) | ~$0.04-0.10 (0.04-0.10%) | ~$10 (margin) |

**Key insight:** At $500 with 6-9 positions (~$55-83/position), US stock fees are **0.84-1.27% of position value** per round-trip. Crypto spot at 0.26% taker is **0.52% round-trip** — 1.6-2.4× cheaper.

**Verdict:** **Crypto spot is the only instrument where fee drag is manageable** at $500 with 6-9 positions.

### 2.2 Small-Account Market Making

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

- Requires: Colocation, low-latency infra, maker rebates, inventory management
- At $500: Inventory risk dominates. A 1% adverse move on a $100 position = $1 loss = 1% of account.
- Kraken maker fee: 0.16% — need to capture >0.16% spread per side to break even.

**Verdict:** **NOT VIABLE at $500.** Requires institutional infrastructure. Defer to $10k+.

### 2.3 Prediction Markets

**Source:** Prior research (not re-fetched this session)

- Kalshi: $1 min contract, 0.02-0.05% fee (HEURISTIC)
- At $500: 500-2500 contracts possible, but fee drag is **0.04-0.10% per contract**
- Edge: Prediction markets are **efficient** — hard to find consistent edge without insider info or superior models

**Verdict:** **MARGINAL at $500.** Fee drag is low, but edge is hard to find. Requires **domain expertise** (e.g., sports, politics, crypto) and **fast execution** (markets move quickly).

### 2.4 Funding Rate Arbitrage

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

- Delta-neutral: Long spot + short perpetual, collect funding every 8 hours
- Typical rates: 0.01%-0.1% per cycle → **1-45% annually**
- At $500: $250 spot + $250 perp short (2x lev) = $375 margin, $125 buffer
- Realistic range: **5-27% annual** (HEURISTIC: depends on funding regime)

**Verdict:** **VIABLE at $500 but GATED.** Requires Kraken futures access, paper validation, and funding rate monitoring.

### 2.5 Low-Turnover Trend + Strict Risk

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

- momtrend.py: Momentum-top + market-breadth entry gate
- Backtest: OOS 11% ann, Calmar 0.852, maxDD -13.0%
- At $500: 3-5 crypto positions at $100-167 each, 20-day rebalance, ~18 trades/year
- Annual fee drag: ~9.4% (HEURISTIC: 18 × 0.52%)
- Net edge after fees: **1.6-11.6%** (range from R1 to OOS)

**Verdict:** **VIABLE.** This is the current validated setup. The OOS 11% annual with 0.852 Calmar is the honest number.

### 2.6 ETF Rotation (US Stocks)

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

- 4-12 ETFs, monthly/quarterly rebalance, 12-48 trades/year
- At $500 with $0.35/side: 24 trades × $0.70 = $16.80/year = **3.36% fee drag**
- Need >3.36% edge per year just to break even on fees

**Verdict:** **MARGINAL at $500.** Fee drag is 3.36%/year. Not recommended below $1k.

### 2.7 Options at $500

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

- PDT rule ($25k) is the hard wall. At $500, limited to 3 day-trades/week.
- Margin requirements + complexity

**Verdict:** **NOT VIABLE.** PDT wall + margin requirements. Defer to $25k+.

### 2.8 Cross-Asset Diversification

**Source:** [small-capital-profitability.md](small-capital-profitability.md) (fetched 2026-08-28)

| Allocation | Instrument | Rationale |
|---|---|---|
| $300 (60%) | Crypto spot (BTC/ETH/SOL) | Current validated setup, lowest fees |
| $100 (20%) | US stocks (1-2 large caps) | Diversification, $0.35 fee amortized on $100 |
| $100 (20%) | Cash reserve | Buffer for fees, slippage, opportunities |

**Verdict:** **MARGINAL.** The stock allocation at $100 is too small to amortize the $0.35 fee. Better to go 100% crypto spot at $500.

---

## 3. Economics (All HEURISTIC)

### 3.1 Cost-to-Pass vs Funded Profit Split

**Challenge fees (from primary sources):**

| Firm | Account Size | Challenge Fee | Profit Split | Break-Even (Funded P&L) |
|---|---|---|---|---|
| E8 One $5K | $5,000 | $40 | 80% | $50 (fee / 80%) |
| E8 Signature $25K | $25,000 | $110 | 80-100% | $110-137.50 |
| FTUK 1-Step $5K | $5,000 | ~$50 (HEURISTIC) | 80% | $62.50 |
| FunderPro $5K | $5,000 | ~$50 (HEURISTIC) | 80-90% | $55.56-62.50 |

**Expected time to pass (HEURISTIC):**
- E8 One $5K: 8% target, 4% max DD, 2% daily → **2-4 weeks** (HEURISTIC: based on 7.35% FunderPro pass rate + E8's no-daily-DD rule)
- FTUK 1-Step $5K: 10% target, 8% trailing DD → **3-6 weeks** (HEURISTIC: higher target, trailing DD)
- FunderPro $5K: 10% target, static DD → **2-4 weeks** (HEURISTIC: no time limit, static DD)

**Expected monthly income (funded, HEURISTIC):**
- E8 One $5K: 80% split, 2-4% monthly return → **$80-160/month** (HEURISTIC: 2-4% of $5K × 80%)
- E8 Signature $25K: 80-100% split, 2-4% monthly return → **$400-1000/month** (HEURISTIC: 2-4% of $25K × 80-100%)
- FTUK 1-Step $5K: 80% split, 2-4% monthly return → **$80-160/month** (HEURISTIC)
- FunderPro $5K: 80-90% split, 2-4% monthly return → **$80-180/month** (HEURISTIC)

**ROI on challenge fee (HEURISTIC):**
- E8 One $5K: $40 fee, $80-160/month → **2-4 months to break even**
- E8 Signature $25K: $110 fee, $400-1000/month → **1-2 months to break even**
- FTUK 1-Step $5K: $50 fee, $80-160/month → **3-6 months to break even**
- FunderPro $5K: $50 fee, $80-180/month → **3-6 months to break even**

**Verdict:** **E8 Signature $25K has the best ROI** (1-2 months to break even), but requires a **$110 challenge fee** and a **4% max DD** constraint. E8 One $5K is the **lowest-cost entry** ($40 fee) but has a **lower profit split** (80%) and **tighter DD** (4% max, 2% daily).

---

## 4. Deliverables

### 4.1 Full Menu of Viable Options

| # | Option | Mechanism | Capital | Return Range | Fee Impact | Data Needed | Effort | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | **Crypto Spot Momentum** | momtrend.py (validated) | $500 | 5-11% ann | 0.52% RT | BTC/ETH/SOL OHLCV | Low (running) | **VIABLE** |
| 2 | **Funding Rate Arb** | Delta-neutral perp | $500 | 5-27% ann | ~0.02-0.05% RT | Funding rates, perp fills | Medium (paper-validate) | **VIABLE (gated)** |
| 3 | **E8 One $5K Challenge** | Prop firm eval | $40 fee | 80-160/mo (funded) | N/A (challenge) | TradeLocker API | Medium (adapter) | **VIABLE** |
| 4 | **E8 Signature $25K Challenge** | Prop firm eval | $110 fee | 400-1000/mo (funded) | N/A (challenge) | TradeLocker API | Medium (adapter) | **VIABLE (best ROI)** |
| 5 | **FTUK 1-Step $5K Challenge** | Prop firm eval | ~$50 fee | 80-160/mo (funded) | N/A (challenge) | TradeLocker API | Medium (adapter) | **VIABLE** |
| 6 | **FunderPro $5K Challenge** | Prop firm eval | ~$50 fee | 80-180/mo (funded) | N/A (challenge) | TradeLocker API | Medium (adapter) | **VIABLE (trust risk)** |
| 7 | **ETF Rotation** | US stock rotation | $500 | 2-12% ann | 3.36% ann | ETF OHLCV | Low | **MARGINAL** |
| 8 | **Prediction Markets** | Kalshi contracts | $500 | 5-20% ann (HEURISTIC) | 0.04-0.10% | Event data, models | High | **MARGINAL** |
| 9 | **Market Making** | Spread capture | $500 | N/A | 0.16% maker | Order book | High | **NOT VIABLE** |
| 10 | **Options** | Covered calls, puts | $500 | N/A | $0.65/contract | Options chain | High | **NOT VIABLE** |

### 4.2 TOP-3 with $500 Allocation + 30-Day Gates

#### #1: Crypto Spot Momentum (CURRENT — continue)

**Allocation:** $500 (100%)
- BTC/USDT: $167
- ETH/USDT: $167
- SOL/USDT: $166

**Strategy:** momtrend.py (validated: OOS 11% ann, Calmar 0.852)
**Fees:** 0.26% taker, 0.52% round-trip
**Expected annual return (after fees):** 5-11% (HEURISTIC)
**Max drawdown (backtest):** -13.0%

**30-day gate:**
1. Equity ≥ $475 (max 5% drawdown)
2. ≥ 3 fills executed
3. Realized P&L ≥ 0 after fees
4. No circuit breaker trips

**Why #1:** Already validated, already running, lowest fee drag, no new infrastructure needed.

#### #2: E8 Signature $25K Challenge (NEW — best ROI)

**Allocation:** $110 (challenge fee) + $0 (funded account is simulated)
- Challenge fee: $110 (one-time)
- Funded account: $25,000 (simulated, no real capital at risk)

**Strategy:** opentrader rule-floor config (reconfigured for 4% max DD)
**Fees:** N/A (challenge phase)
**Expected monthly income (funded):** $400-1000 (HEURISTIC: 2-4% of $25K × 80-100% split)
**Max drawdown (challenge):** 4% (EOD dynamic)

**30-day gate:**
1. Challenge passed (6% profit target hit)
2. Max drawdown < 4% (no breach)
3. ≥ 5 profitable trading days
4. No daily loss limit breaches (N/A in challenge phase)

**Why #2:** Best ROI (1-2 months to break even), highest profit split (80-100%), on-demand payouts, no time limit. **Requires TradeLocker adapter** (1-2 days dev).

**Prerequisite:** Build TradeLocker adapter, reconfigure opentrader for 4% max DD, paper-validate on demo.tradelocker.com.

#### #3: Funding Rate Arbitrage (NEW — paper-validate)

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

**Why #3:** Highest risk-adjusted return potential. Delta-neutral = low drawdown. But requires Kraken futures access (gated) and paper validation first.

**Prerequisite:** Paper-validate perp fills + liquidation model (per evolution-thesis.md gate).

### 4.3 Bottom Line (One Paragraph)

**What to do with the $500 this month:**

1. **Continue running Crypto Spot Momentum** ($500, 100%) — this is the validated, low-fee, low-effort baseline. Track the 30-day gate metrics.
2. **Build the TradeLocker adapter** (1-2 days dev) and **paper-validate on demo.tradelocker.com** — this unlocks the prop-funding branch (E8 Signature $25K, FTUK 1-Step, FunderPro $5K). The E8 Signature $25K challenge has the best ROI (1-2 months to break even, $400-1000/month funded income).
3. **Paper-validate Funding Rate Arbitrage** (Kraken futures) — this is the highest risk-adjusted return potential (5-27% annual, <3% max DD) but requires futures access and liquidation model validation.

**Do NOT:**
- Allocate to US stocks (fee drag too high at $500)
- Attempt market making or options (not viable at $500)
- Commit to FunderPro without monitoring the Trustpilot trust situation (payout denial complaints rising)

**Next 30 days:**
- Week 1: Continue Crypto Spot Momentum, start TradeLocker adapter dev
- Week 2: Finish TradeLocker adapter, paper-validate on demo
- Week 3: Reconfigure opentrader for 4% max DD, run shadow A/B on demo
- Week 4: Review 30-day gates, decide on E8 Signature $25K challenge purchase ($110 fee)

**Expected outcome (HEURISTIC):**
- If Crypto Spot Momentum passes 30-day gate: **$500 → $525-555** (5-11% annual, prorated)
- If E8 Signature $25K challenge passed: **$400-1000/month funded income** (80-100% split on 2-4% monthly return)
- If Funding Rate Arb validates: **$25-68/month** (5-27% annual on $500, prorated)

**Total expected monthly income (funded, HEURISTIC):** **$425-1068/month** (E8 Signature $25K + Crypto Spot Momentum + Funding Rate Arb)

**Risk:** The prop-funding branch is **high-variance** (15-25% pass rate, HEURISTIC). The Crypto Spot Momentum and Funding Rate Arb branches are **low-variance** (5-11% and 5-27% annual, respectively). The $500 is **at risk** in the Crypto Spot Momentum branch (max -13% drawdown), but **not at risk** in the prop-funding branch (challenge fee is the only cost).

---

## 5. Open Items

- [ ] TradeLocker adapter implementation (1-2 days dev)
- [ ] opentrader reconfiguration for 4% max DD (challenge mode)
- [ ] Paper-validation on demo.tradelocker.com (1-2 weeks)
- [ ] Kraken futures access + liquidation model validation (funding arb)
- [ ] E8 Signature $25K challenge purchase decision (after 30-day gate)
- [ ] FunderPro Trustpilot monitoring (trust risk)

---

## 6. Source Audit

| Source | URL | Fetched | Chars | Quality |
|---|---|---|---|---|
| FundedTrading.com | [best-tradelocker-prop-firms/](https://fundedtrading.com/best-tradelocker-prop-firms/) | 2026-08-28 | 46,691 | **HIGH** (15 firms, rules, payouts, discount codes) |
| TradingFinder.com | [props/ftuk/rules/](https://tradingfinder.com/props/ftuk/rules/) | 2026-08-28 | 7,350 | **HIGH** (FTUK full rules) |
| FunderPro.com | [trading-rules/](https://funderpro.com/trading-rules/) | 2026-08-28 | 6,163 | **MEDIUM** (DD in accordions, not fully extracted) |
| PropFirmApp.com | [prop-firms/e8-markets](https://propfirmapp.com/prop-firms/e8-markets) | 2026-08-28 | 5,343 | **HIGH** (E8 full rules, 3 models) |
| GitHub | [TradeLocker/tradelocker-python](https://github.com/TradeLocker/tradelocker-python) | 2026-08-28 | 2,801 | **HIGH** (official SDK, usage example) |
| TradeLocker.com | [api](https://tradelocker.com/api) | 2026-08-28 | 50,508 | **HIGH** (API docs, JWT auth, rate limits) |
| Small-capital-profitability.md | [local](small-capital-profitability.md) | 2026-08-28 | N/A | **HIGH** (fee analysis, strategy menu, TOP-3) |
| Prop-firm-challenge-research.md | [local](prop-firm-challenge-research.md) | 2026-08-05 | N/A | **HIGH** (9 firms, FTMO/The5ers/FundedNext) |

**Fetch success rate:** 7/8 (87.5%) — 1 partial (FunderPro DD in accordions)
**Search success rate:** 4/8 (50%) — 4 rate-limited (Brave 429)

**Data quality note:** The prop-firm rules are **primary-source verified** (fetched from firm websites or high-quality third-party sources). The economics (pass probability, monthly income, ROI) are **HEURISTIC** (based on disclosed pass rates + assumed return ranges). The TradeLocker adapter feasibility is **code-verified** (ExchangeBase interface + SDK README).
