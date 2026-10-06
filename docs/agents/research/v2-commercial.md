# V2 commercial models & per-call A2A pricing (wayfinder ticket #333)

- **Date:** 2026-10-06
- **Scope:** How trading platforms actually monetize (thinkorswim, TradingView, NinjaTrader, QuantConnect/LEAN, Quantopian postmortem, API-first brokers) and what metered per-call pricing looks like in adjacent markets (market-data APIs, algo-execution APIs, agent-to-agent commerce: Stripe ACP/Metronome, x402, MCP monetization) — feeding the commercial-model lock in map **#326**, the "cheap per-call API access for agent-to-agent (A2A) asset trading" direction.
- **Status:** **Options for the human to choose from, with trade-offs — not a verdict.** This doc opens no gate and changes no V1 surface. Sibling docs: venue/feed survey (#329) → `v2-venues-feeds.md`; this doc complements it on the money side.
- **Method:** Primary sources (official pricing pages, docs, newsroom posts) fetched today wherever possible. Secondary sources (reviews, aggregator blogs) are labeled **[secondary]**. Price arithmetic is labeled **[derived]**. Numbers that could not be confirmed from a primary page are labeled **[unverified]**. JS-rendered price grids that failed to extract: TradingView prices, QuantConnect tier prices (feature matrices did extract).

---

## Part 0 — The constraint, sharpened: what "make the calls cheap" must mean

Agent trading loops are **read-heavy**. A venue agent that polls one price stream at 1 call/s for a ~20-hour FX day issues ~72,000 read calls and places perhaps tens of orders ([derived]). Read traffic at retail per-call prices is lethal; at wholesale per-call prices it is invisible. The whole pricing question is therefore not one number but **two meters**: reads (must approach infra cost, $10⁻⁶–$10⁻⁵/call) and actions (can carry $10⁻²–$10⁰ each). Platforms that meter both at the same rate will either bankrupt agents or starve themselves.

The cost side is genuinely tiny for reads: Twelve Data's Grow tier ($29/mo, 55 API credits/min ≈ 2.4M requests/mo at full utilization) implies **≈ $0.000012 per request**; its Pro tier ($99/mo, 610 credits/min ≈ 26M/mo) implies **≈ $0.0000038 per request** ([derived from official pricing](https://twelvedata.com/pricing)). What is *not* tiny is (a) market-data licensing if V2 redistributes its own feed, (b) support, and (c) the fixed cost of being a counterparty. That split — cheap reads, expensive everything else — is what every candidate in Part 4 monetizes differently.

---

## Part 1 — How trading platforms actually monetize

### 1.1 thinkorswim (Charles Schwab) — free-with-brokerage

- The platform is bundled with the brokerage; non-clients get a 30-day "Guest Pass" trial ([Schwab thinkorswim page](https://www.schwab.com/trading/thinkorswim)). Per-call or per-seat cost to the user: **$0**.
- Revenue comes from the brokerage, not the software: Schwab is listed among PFOF-receiving US brokers ([Wikipedia PFOF](https://en.wikipedia.org/wiki/Payment_for_order_flow), citing Business Insider); industry-wide, brokers received **$2.5B in PFOF in 2020** (Congressional Research Service), and the **12 largest US brokerages earned $3.8B in PFOF revenue in 2021** while the top three wholesalers handled >80% of US retail equity orders (Wikipedia, same article). Robinhood's 2021 extreme: **77% of net revenue was transaction-based ($1.4B — options 49%, crypto 30%, equities 21%)**.
- Adjacent direct fees exist where the venue is a market: Schwab Crypto charges **0.75% of trade value, zero spread** (same Schwab page) — per-*transaction* pricing, not per-call.
- **Lesson for V2:** the platform is a retention surface; the money is in float, routing, margin, and per-fill fees. The per-call price of the *software* can be zero *because* it is not the business.

### 1.2 TradingView — freemium subscription, capacity-metered

- Five tiers (Basic free → Essential → Plus → Premium → Ultimate). Prices **[secondary, 2026 review](https://gist.github.com/scju673/0c28e472f06dac95d342289e2119b130)**: Essential ≈ $12.95/mo billed annually (~$14.95 monthly), Plus ≈ $28.29 (~$34.29), Premium ≈ $56.49 (~$68.49), Ultimate ≈ $199.95 (~$249.95). Annual billing discounts ~13–17%.
- What the official [pricing page](https://www.tradingview.com/pricing/) actually meters is **capability capacity, not calls**: charts per tab (1→16), indicators per chart (2→50), active price alerts (3→1,000), historical bars (5K→40K), simultaneous chart connections (2→200), Pine calculation time (20s→100s), watchlist symbols (30→1,000), screener auto-refresh rates, backtest report depth.
- **Lesson:** TradingView never prices a request. It prices *headroom* — the subscription buys limits, and usage within limits is unmetered. A free tier stays genuinely usable (1 chart, 2 indicators, 3 alerts, 30 watchlist symbols) — a real onboarding funnel.

### 1.3 NinjaTrader — free platform, per-side commissions, license tiers

From the official [pricing page](https://ninjatrader.com/pricing) (futures, FCM-cleared):

| Plan | Platform fee | Micro/e-Nano per side | Standard per side |
|---|---|---|---|
| **Free** | $0 | $0.39 | $1.29 |
| **Monthly** | $99/mo | $0.29 | $0.99 |
| **Lifetime** | $1,499 one-time | $0.09 | $0.59 |

- Per side means per entry or exit; a round trip is double. Exchange/clearing/NFA fees are extra, "as they are at every regulated U.S. futures broker" (same page).
- The platform itself is **always free for charting, backtesting, and unlimited simulated trading** — no funding required; real-time data and premium add-ons unlock when the account is funded. Company structure explicitly splits the software vendor (NinjaTrader, LLC) from the FCM (NinjaTrader Clearing, LLC).
- **Lesson:** the purest per-*action* pricing in the space: software free, every trade action metered, and the subscription/lifetime products are *commission discount vehicles* ($99/mo or $1,499 to cut per-side fees by 25–77%). The meter is the fill, never the API call.

### 1.4 QuantConnect / LEAN — open-core, cloud metered by resource-time + micro-credits

- The engine (LEAN) is open source and free to run locally; the cloud is the product. Five organization tiers (Free / Quant Researcher / Team / Trading Firm / Institution) — tier prices are JS-hidden **[unverified]**; QuantPedia lists Researcher $96/yr, Team $960/yr **[secondary, likely stale]**.
- Free tier caps (official [docs](https://www.quantconnect.com/docs/v2/cloud-platform/organizations/resources)): one B-MICRO backtest node with a **200 backtests/day** cap, one research node, **zero live nodes**, agent node capped at **100,000 tokens/month**; paid tiers raise node quotas (Team: 10 live nodes; Trading Firm: unlimited).
- **QuantConnect Credit (QCC)** is the micropayment currency: **1 QCC = $0.01** ([official](https://www.quantconnect.com/docs/v2/cloud-platform/organizations/credit)). QCC covers: parameter-optimization node-time (billed as it runs, pre-estimated), dataset downloads (per-file/per-day), and **notification overages** — email/Telegram/webhook above the tier's hourly quota costs 1 QCC each, US/CA SMS 1 QCC, international SMS 10 QCC (official resources doc).
- Notification quotas by tier: 20/hr (Researcher) → 60 → 240 → 3,600/hr (Institution) — usage ceilings, with metered pennies beyond.
- **Lesson:** the open-core escape from Quantopian's trap — the community product is free software, the *paid* meter is compute-time and consumables. Note the metering granularity: $0.01 for a notification is expensive per-call; $0.01-per-credit works because credits are spent in bursts on meaningful units (an optimization job, a dataset), not per poll.

### 1.5 Quantopian — the postmortem every free-trading-platform should re-read

From [Wikipedia](https://en.wikipedia.org/wiki/Quantopian) (primary quotes preserved): founded 2011, raised **$48.8M** (Spark, Khosla, Bessemer, Point72 Ventures, a16z), 210,000+ members by 2018, **$250M** committed by Point72 in 2016, single algorithms funded up to **$50M**. Two-sided market: members develop **for free** on free data/tools; institutional investors allocate to winning algorithms and pay royalties/commissions.

- **Feb 2020:** returned investors' money — the strategies underperformed. **Nov 2020:** shut down after 9 years ("crowd-sourcing alpha was a moonshot"); the team went to Robinhood. Gap filled by QuantConnect, CrunchDAO, Numerai.
- The intended economics were explicit: board member Andrew Parker described the target as "a modest number of users and a large average revenue per user (ARPU); more like Bloomberg than Facebook" — the institutional pivot (2018 FactSet enterprise product) never replaced the free community's burn.
- **Lessons for V2 (direct):**
  1. **A free, unmetered community platform is a cost center until something charges.** Quantopian's users consumed data and compute for 9 years with no per-usage revenue line.
  2. **"We'll make money when the alpha works" is a contingent business model.** Platform viability cannot depend on the customers' trading being profitable.
  3. **Charge the compute, the data, or the fills — anything that exists regardless of whether the community's alpha is real.** QuantConnect (same audience, same era) survived precisely by doing #3.

### 1.6 API-first brokers — Alpaca (and IBKR by pointer)

- **Alpaca** is the closest living model to "A2A trading platform as API": commission-free US stocks/options/crypto via Trading API; free paper accounts; free tier **200 API calls/min → 10,000/min paid** (captured in sibling `v2-venues-feeds.md` #329 from official docs). Their own ["How does Alpaca make money?"](https://alpaca.markets/support/how-alpaca-makes-money) page opens: "Securities brokers traditionally generate revenue in multiple ways including charging trading commissions, marking up margin lending rates and stock loan…" (page body is JS-rendered; margin ~6.5% USD **[secondary, BrokerChooser review]**). Revenue = margin, interest, securities lending, routing — plus B2B Broker API (fintechs like Midas build brokerages on it).
- **Agent surface:** Alpaca ships a free official [MCP server](https://alpaca.markets/mcp-server) — "Ask. Build. Analyze. Automate. Execute… inside your favorite AI interface" — with full prompt/parameter/payload visibility per trade, Cursor/PyCharm/Postman integration. This is the shape of V2's A2A product surface precedent.
- **The clause that matters for agent flow** (MCP page disclosures): *"Alpaca reserves the right to charge additional fees if it is determined that order flow is non-retail in nature."* Agent-driven flow is exactly what this clause anticipates: today's free-execution economics are priced for human retail accounts, and venues will re-meter flows that don't look like that. Whatever V2 charges per call, the **venue may charge the agent's flow separately — commercial model must anticipate this layer.**
- **Interactive Brokers:** commissions + per-exchange market-data subscriptions (full tables in `v2-venues-feeds.md` #329).

---

## Part 2 — Metered per-call pricing in adjacent markets

### 2.1 Market-data APIs (the closest per-call analogies)

| Vendor | Model | Numbers | State |
|---|---|---|---|
| **[Twelve Data](https://twelvedata.com/pricing)** | Credit-metered subscription tiers | Free: 800 calls/day (8 credits/min); Grow $29/mo (55 credits/min); Pro $99/mo (610 credits/min); Ultra $329/mo (2,584 credits/min). 1 standard request = 1 credit; batch requests bundle symbols per credit | Alive; per-request cost at full tier utilization ≈ $0.000012 (Grow) → $0.0000038 (Pro) **[derived]** |
| **[Polygon.io → "Massive"](https://polygon.io/pricing)** | Rebranded; now sells "unlimited market data… simple pricing" tiers (business pricing separate) | Tier prices not extractable from current page **[unverified]** | Alive (rebrand noted 2026-10) |
| **[Databento](https://databento.com/pricing)** | Usage-based ($/GB) + subscriptions | $125 free credits (6-mo expiry); Standard $199/mo; Plus $1,750/mo (annual contract); Unlimited $4,500/mo. Pass-through exchange license fees, "no upcharge" | Alive; **usage-based live (per-message) billing deprecated by 2025-03-31** for most datasets — moved to subscription |
| **IEX Cloud** | Per-credit metered data API | — | **Dead: retired 2024-08-31.** Announcement: "running at a loss and represented less than 2% of IEX Group overall revenue" ([finazon recap](https://finazon.io/blog/iex-cloud-is-gone-why)); customers referred to Intrinio (EOD historical data from **$3,100/yr** [secondary]) |

Two hard lessons sit in this table:

1. **Per-message billing did not survive even at a real exchange.** Databento kept usage-based for *historical* ($/GB) but killed it for live; IEX Cloud per-credit metering died outright. Where per-call survives, it survives as **rate-cap bundles** (Twelve Data) — you buy a ceiling, not a meter.
2. **The fixed cost is data licensing.** V2's per-call price floor is set by whether it redistributes a licensed feed (then each read carries amortized license cost) or passes through the agent's own venue credentials (OANDA/IBKR keys — reads cost only compute, `v2-venues-feeds.md` Part 0-2). This is the #334/#336 boundary question, but it *is* the pricing question too.

Adjacent datapoint — **X API** (non-finance, shows per-call spreading): after killing free access in 2023 ($100→$200/mo Basic, $5,000/mo Pro, $42,000/mo Enterprise), X opened a **pay-per-use** beta in Oct 2025 — per-request-type prices (read/post/DM/trends/bookmarks), an estimator calculator, and **no monthly tier caps** ([TechCrunch](https://techcrunch.com/2025/10/21/x-is-testing-a-pay-per-use-pricing-model-for-its-api/)). Direction of travel in adjacent API markets: tiers → per-request granularity, after tier-price backlash.

### 2.2 Algo-execution APIs

- **NinjaTrader brokerage:** per-side commission per fill (1.3 above) — the execution meter is standard everywhere in futures.
- **Alpaca:** execution free (revenue from margin/float/routing; non-retail-flow clause) — execution meter is zero until the venue decides otherwise.
- **QuantConnect:** live trading metered as **node-hours** (monthly node subscription + QCC for overage consumables) — execution itself unmetered; the *resources around it* are the product.
- **Trading Technologies / institutional:** per-contract execution licensing (pointer only — institutional contracts, no public per-call price).

No competitor meters *order placement* per-call; they meter per **fill/side** (venue economics) or per **resource-time** (cloud economics).

### 2.3 Agent-to-agent commerce & MCP monetization (the A2A layer)

- **Stripe ACP (Agentic Commerce Protocol)** — released with OpenAI; already powers **Instant Checkout in ChatGPT**; an **open standard** — "merchants can sell through AI agents while retaining control over their brand, catalog, fulfillment, and customer relationships… businesses can adopt it even if they don't process payments with Stripe." Early partners testing: Microsoft Copilot, Anthropic, Perplexity, Vercel, Lovable, Replit, Manus ([Stripe newsroom, Tour NY 2025](https://stripe.com/newsroom/news/tour-newyork-2025); [agenticcommerce.dev](https://www.agenticcommerce.dev/)).
- **Stripe agents stack** — "charge for AI features, sell through agents, and accept payments from agents"; an agent plugin bundling the **Stripe MCP server + agent skills**; the **Stripe Directory** is an index agents can search/discover merchants ([docs.stripe.com/agents](https://docs.stripe.com/agents)). Stripe Billing now supports **hybrid revenue models combining subscriptions with usage-based pricing**, and a new API tracks LLM inference costs in real time (newsroom, same launch).
- **Metronome is now part of Stripe** — real-time metering, "flexible pricing models (including tiered, dimensional, and composite pricing), prepaid credits, enterprise contracts, and automated invoice generation" ([usage-based billing docs](https://docs.stripe.com/billing/subscriptions/usage-based)). This is the off-the-shelf machinery for per-call/per-tool-call metering if V2 doesn't want to build it.
- **Usage-based pricing is the ambient norm:** SaaS companies with usage-based pricing went **27% (2018) → 41% (2023)**, with hybrids becoming dominant ([Orb usage-billing guide](https://www.withorb.com/blog/usage-billing-guide), citing Growth Unhinged). The canonical per-call problems and their fixes are standard playbook: bill shock → budget caps/alerts (Twilio pattern); forecasting → floor commitments (AWS pattern); accuracy → raw usage-event architecture.
- **Fraud on free tiers is a stated revenue problem:** Stripe Radar now blocks **up to 62% of trial fraud** — "bad actors string together multiple free trials and rack up huge compute bills" (newsroom). Any V2 free-call tier for agents needs the same defense (proof-of-work, staked credits, or identity-keyed quotas).
- **x402** — open standard (Linux Foundation), HTTP-native payments: server middleware returns **HTTP 402 Payment Required**, agent pays per request in stablecoins and retries; **zero protocol fees** (payment-network fees only), no account/KYC/API key, "production ready… millions of transactions" ([x402.org](https://x402.org/)). Purpose-built for exactly "make the calls cheap but metered": an agent can onboard with a wallet and pay $0.0001/request with no contract at all.
- **A2A protocol** (the namesake of our ticket): open standard for agent↔agent communication — agent discovery via **Agent Card at `/.well-known/agent-card.json`**, authentication via declared security schemes, `SendMessage`/`SendStreamingMessage` task APIs over HTTPS/JSON-RPC/SSE, long-running operations. Explicit division of labor: *"A2A crosses the boundary between agents; MCP stays within one agent, connecting it to APIs and enterprise applications"* ([a2a-protocol.org](https://a2a-protocol.org/latest/topics/what-is-a2a/)). Implication for pricing: **per-A2A-task** (or per-MCP-tool-call) is a naturally billable unit, distinct from both per-API-call and per-fill.
- **Alpaca MCP server** (2.3 above) is free today with the non-retail-flow fee reservation — the current equilibrium for agent trading access: platform access free, venue economics latent.

---

## Part 3 — Unit economics at scale (inputs cited; arithmetic **[derived]**)

**Cost side, per read call:**

- Wholesale market-data reads at tier caps: ≈ **$0.000012 → $0.0000038** per request (Twelve Data Grow/Pro, Part 2.1).
- Self-compute per REST call at scale: order **$0.00001** (engineering estimate, not externally verifiable **[est.]**).
- If agents bring their own venue credentials (BYO-key, the V1/OANDA pattern), V2's marginal read cost is compute-only. If V2 redistributes a licensed feed, each read must amortize feed licensing (Databento Standard $199/mo per user-scale feed as a public anchor; IEX Cloud's death as the failure mode).

**Revenue side, per action (the money an execution-attached platform actually earns):**

| Action | Revenue | Source |
|---|---|---|
| Futures fill (per side) | $0.09–$1.29 | NinjaTrader official |
| FX $1M traded (core pricing) | $50 (0.5 bp) | OANDA via `v2-venues-feeds.md` (primary) |
| FX $100k round-turn (spread, majors) | ~$6–12 **[est.]** | typical ~0.6–1.2 pip spreads on majors |
| Equity retail order (PFOF, 100 sh) | ~$0.10–0.30 **[est.]** | "fractions of a cent per share" (Wikipedia PFOF) |
| Robinhood-scale proof | 77% of net revenue transaction-based; $1.4B in 2021 | Wikipedia PFOF |
| Crypto (venue-typical taker) | ~0.1% notional ($10 per $10k) **[est.]** | venue-typical |

**The sensitivity that decides the model** — one modest agent, per day: ~72,000 read calls (Part 0) + 20 order calls + 2 fills.

| Pricing of reads | Agent's daily read bill | Verdict for "cheap calls" |
|---|---|---|
| $0.001/call (retail data-API style) | **$72/day** | kills agent economics |
| $0.0001/call | $7.20/day | marginal; only viable if bundled |
| $0.00001/call (≈ Twelve Data bulk rate) | **$0.72/day** | negligible — "cheap" achieved |
| Subscription-bundled (rate-capped) | $0 incremental | cheap, but platform carries idle agents |

And the offset: **one Micro futures round-turn at NinjaTrader's Free-plan rates = $0.78 revenue** (2 × $0.39); one FX $100k round-turn ≈ $6–12 **[est.]**. A single fill can fund ~8,000–100,000 reads at the $0.0001–$0.00001 prices ([derived]). That ratio is the quantitative core of the ticket: **per-fill revenue can blanket per-call costs at scale; per-call revenue cannot, by itself, cover data licensing and support** (IEX Cloud arithmetic, Part 2.1).

---

## Part 4 — Five candidate pricing structures for V2 (options for the human, not a verdict)

### Option A — Free calls, execution-side monetization (thinkorswim / Alpaca / NinjaTrader pattern)

API calls (reads *and* order placement) are **$0 and unmetered**; the platform earns per fill (commission, spread markup, core-pricing analog, or routing economics) or on the balance (margin, float).

- **Why calls stay cheap:** they are literally free — the cheapest possible price.
- **Why the platform stays viable:** revenue scales with trading activity, which is what the platform exists for; NinjaTrader does this for a living, Alpaca at zero commission via the balance sheet.
- **Trade-offs / risks:** requires either becoming (or fronting) a brokerage — the heaviest regulatory surface of all options; revenue is contingent on members actually trading (a Quantopian-shaped risk if the community is read-heavy and trade-light); venue-side clauses like Alpaca's non-retail-flow reservation can insert a second, uncontrollable fee layer; PFOF-class revenue is US-equity-specific and reputationally contested (banned in UK/EU/Canada/Australia).
- **Precedent strength:** ★★★★★ (the dominant model of the entire category).

### Option B — Freemium capacity tiers, calls rate-capped not metered (TradingView / Alpaca-free / Twelve Data pattern)

Free tier with a generous **rate cap** (e.g., Alpaca's 200 calls/min, Twelve Data's 800/day); paid tiers raise caps and capabilities. No per-call bill ever.

- **Why calls stay cheap:** a rate-capped free tier gives an agent ~28,800 calls/day at 1/min or ~864k/day at 30/min — enough for streaming-based agent loops ([derived]); within-cap usage costs the user nothing.
- **Why the platform stays viable:** subscription revenue is predictable and covers fixed costs (the TradingView/QuantConnect engine); WebSocket streaming makes read-calls nearly moot (one connection replaces polling), so the cap is an *engineering* lever as much as a pricing lever.
- **Trade-offs / risks:** idle agents are pure cost on the free tier (needs trial-fraud defenses — Stripe's 62% number is the benchmark); heavy agents can be subsidized by the tier (cap enforcement and per-agent identity needed); tier design becomes the product (TradingView spends enormous energy on capability matrices).
- **Precedent strength:** ★★★★★ in data/SaaS; ★★★★ in trading platforms (QuantConnect, Alpaca).

### Option C — Prepaid micro-credits priced near infra cost (QuantConnect QCC / Twelve Data credits / Metronome prepaid pattern)

An internal currency (QCC analog): $10 buys N credits; reads ~$10⁻⁵–$10⁻⁴ each (near the Twelve Data bulk anchor), order/A2A-task calls priced 10–100× higher; volume-decay pricing; hard budget caps.

- **Why calls stay cheap:** by construction — the credit price is set off the $0.00001 compute anchor, not off willingness-to-pay; $10 ≈ 1M reads ≈ 14 agent-days of polling ([derived]).
- **Why the platform stays viable:** credits are prepaid deferred revenue (cash-flow-positive up front); the spread between credit price and marginal cost funds data licensing and support; heavy agents self-select into paying.
- **Trade-offs / risks:** needs metering infrastructure (usage records — build on Metronome/Stripe or equivalent); needs anti-abuse (credit farms); QCC's own pricing shows the failure mode — $0.01/notification is per-call pricing that *feels* expensive; credit price discipline must be enforced forever; refunds/liability for prepaid balances.
- **Precedent strength:** ★★★★ (QuantConnect, Twelve Data, every cloud provider).

### Option D — Hybrid floor + metered overage (Stripe hybrid / Databento Standard+pay-as-you-go pattern)

Small monthly subscription (floor) covers a large included call allowance; beyond it, usage records accrue at near-cost per-call rates, billed monthly via classic invoicing. The Stripe-documented dominant hybrid of subscription + usage-based.

- **Why calls stay cheap:** the floor (e.g., $9–29/mo) covers a whole agent's read volume at $10⁻⁵; overage rates inherit the near-cost anchor; budget caps prevent bill shock.
- **Why the platform stays viable:** floor revenue covers fixed costs before the first metered cent (directly answers the IEX Cloud lesson — a revenue floor under the meter); usage revenue grows with the heaviest (most-committed) agents; matches the 27%→41% usage-based SaaS drift *and* keeps invoice simplicity.
- **Trade-offs / risks:** two prices to communicate (harder marketing than A or B); still needs metering + dispute-proof usage logs; overage resentment risk (X API's tier backlash shows how badly this can go when the floor is mispriced).
- **Precedent strength:** ★★★★★ in SaaS/billing generally; ★★★ in trading specifically.

### Option E — Agent-native per-call rails: MCP tool-call / A2A-task micropayments (x402 / ACP / Stripe Directory pattern)

Agents hold wallets (stablecoin via x402, or Stripe-side instrument via ACP/usage records); each **MCP tool call or A2A task** carries a micro-price; V2 publishes an Agent Card with pricing; discovery via Directory-style indexes. Per-call settlement at network-fee cost (x402: zero protocol fee), or aggregated monthly.

- **Why calls stay cheap:** the rail's marginal cost is a payment-network fee — sub-cent by design; no subscription locks agents out; agents with no relationship to V2 can still transact (zero-onboarding, the x402 pitch: "no accounts or personal information needed").
- **Why the platform stays viable:** pure per-call revenue at true granularity — every cost is covered by exactly the caller that caused it; and the A2A/MCP surface itself becomes a differentiated sellable product (the only one of the five options whose *product surface* is the A2A trading capability the map asks for).
- **Trade-offs / risks:** regulated-trading reality — micropayments can settle *API calls*, but **fills still require a brokerage rail** (Option A or a partner behind it); stablecoin/compliance surface if x402-flavored; protocols are young (ACP is months old, x402 Foundation operational only recently); financial-promotion/consumer-protection rules for trading APIs are uncharted for agent payers; a compromised agent wallet is a new fraud class.
- **Precedent strength:** ★★ as shipped commerce rails; ★★★★ as direction (Stripe + OpenAI + LF-governed x402 + Google-donated A2A all point here).

### Comparison at a glance

| | A: free+fills | B: capacity tiers | C: prepaid credits | D: floor+overage | E: per-call A2A rail |
|---|---|---|---|---|---|
| Price of a read call | $0 | $0 within cap | ~$10⁻⁵–10⁻⁴ | ~$10⁻⁵ after floor | ~$10⁻⁵–10⁻³ per task |
| Revenue predictability | poor (activity-contingent) | good | good (prepaid) | best (floor+meter) | poor but marginal-cost-true |
| Infra to build | brokerage/execution | rate limiter | metering + wallet | metering (Metronome-class) | payments + metering + agent cards |
| Regulatory surface | heaviest | light | light | light | medium (payments) + execution still needs A |
| Agent onboarding friction | account+KYC (brokerage) | low | low (buy credits) | low | lowest (wallet, no account) |
| Idle-agent cost to platform | low (no calls) | high | zero (prepaid) | covered by floor | zero |
| Fails how? | nobody trades | free-tier abuse | price discipline drift | floor mispriced → backlash | compliance/protocol immaturity |

**A note on composition:** these are not mutually exclusive. The natural stack is **B or D for reads + A for fills + E as the agent-facing settlement layer** — e.g., rate-capped free reads, per-fill venue revenue, and x402/ACP micropayments for premium actions (deep history, optimization runs, co-located execution slots) without forcing every agent into a subscription. QuantConnect already runs exactly this shape at small scale (free tier + node subscriptions + QCC micropayments + third-party venue accounts).

---

## Part 5 — What the human should decide before the spec can lock (feeding #326's commercial-model row)

1. **The meter.** What is the unit: REST call / WS message / MCP tool-call / A2A task / order / fill / notional? Every precedent above says: **meter reads cheap or free, meter actions and fills as the real price** — but the human picks the units V2 promises.
2. **Who pays whom.** Agent operators pay V2 (subscription/credits/micropayments) vs. venue pays/charges V2-mediated flow (PFOF-like or the Alpaca non-retital-flow clause). The Alpaca clause is the live warning: agent flow will get re-priced by venues regardless of V2's own model.
3. **What V2 is:** self-hostable software (LEAN-style open-core — then per-call pricing is the *vendor's* problem, not V2's), a hosted service (QuantConnect-style — then C/D are natural), or a broker-front (thinkorswim/Alpaca-style — then A is the model and per-call cost is marketing copy). This decision swallows the others and gates the #326 "multi-account/multi-user model" row.
4. **Feed economics.** BYO venue keys (reads ≈ free to V2) vs. V2-licensed feed redistribution (reads carry license amortization — Databento/IEX Cloud arithmetic applies directly). This is shared with #329/#334.
5. **Payments compliance posture** if E (or any stablecoin rail) is chosen for agent settlement, given the venue (OANDA/regulated brokers) behind the trades.
6. **Free-tier abuse defense** (whichever option): the Stripe Radar 62%-of-trial-fraud number is what a free agent tier faces on day one.

## Limitations

- TradingView prices are **[secondary]** (a 2026 review gist); the official page's feature matrix is primary but price-figures are JS-rendered. Re-fetch before quoting in a spec.
- QuantConnect tier prices **[unverified]** — the official pricing page is JS-hidden; feature/quota facts are from official docs.
- Alpaca's revenue-page body is JS-rendered beyond its intro sentence; margin-rate figures are **[secondary]** (BrokerChooser). The non-retail-flow clause is verbatim from their page.
- Per-fill FX-spread, PFOF-per-share, and crypto-taker figures are **[est.]** venue-typical ranges, not audited numbers; PFOF aggregates are Wikipedia-cited (CRS/Business Insider).
- X API per-request prices were not published in the TechCrunch piece — direction confirmed, magnitudes unknown.
- Pricing pages change; every number above was fetched 2026-10-06. All web access was via live fetch/search tools in-session (SearXNG + readability extraction); a few JS-rendered grids did not extract and are flagged accordingly.

## Sources

- Schwab thinkorswim overview — https://www.schwab.com/trading/thinkorswim
- TradingView pricing (feature matrix) — https://www.tradingview.com/pricing/
- TradingView prices [secondary] — https://gist.github.com/scju673/0c28e472f06dac95d342289e2119b130
- NinjaTrader pricing — https://ninjatrader.com/pricing
- QuantConnect pricing/features — https://www.quantconnect.com/pricing ; resources/quota docs — https://www.quantconnect.com/docs/v2/cloud-platform/organizations/resources ; QCC — https://www.quantconnect.com/docs/v2/cloud-platform/organizations/credit
- Quantopian (postmortem facts) — https://en.wikipedia.org/wiki/Quantopian
- Payment for order flow (aggregates, Robinhood 2021, Schwab PFOF-listing) — https://en.wikipedia.org/wiki/Payment_for_order_flow
- Alpaca how-we-make-money — https://alpaca.markets/support/how-alpaca-makes-money ; MCP server — https://alpaca.markets/mcp-server ; review [secondary] — https://brokerchooser.com/broker-reviews/alpaca-trading-review
- Twelve Data pricing — https://twelvedata.com/pricing
- Polygon.io/"Massive" pricing — https://polygon.io/pricing
- Databento pricing — https://databento.com/pricing
- IEX Cloud retirement — https://iexcloud.org/ ; recap (loss, <2% revenue) — https://finazon.io/blog/iex-cloud-is-gone-why
- X API pay-per-use — https://techcrunch.com/2025/10/21/x-is-testing-a-pay-per-use-pricing-model-for-its-api/
- Stripe Tour NY 2025 (ACP, hybrid billing, Radar 62%, Directory-era agent commerce) — https://stripe.com/newsroom/news/tour-newyork-2025
- Stripe agents & AI docs — https://docs.stripe.com/agents ; usage-based billing / Metronome — https://docs.stripe.com/billing/subscriptions/usage-based ; ACP standard — https://www.agenticcommerce.dev/
- Orb usage-based billing guide (27%→41%, bill-shock patterns) — https://www.withorb.com/blog/usage-billing-guide
- x402 — https://x402.org/
- A2A protocol — https://a2a-protocol.org/latest/topics/what-is-a2a/
- Sibling: venue & market-data survey (#329) — `docs/agents/research/v2-venues-feeds.md`
