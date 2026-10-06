# V2 venue & market-data survey (wayfinder ticket #329)

- **Date:** 2026-10-04
- **Scope:** Trading-venue APIs + market-data feeds for V2 (FX-first, multi-asset ambition, per spec map #326).
- **Status:** Research recommendation — **the human locks the shortlist** (this is not a verdict, not an ADR, opens no gate).
- **Method:** Primary sources (official vendor/exchange docs, fetched today) wherever possible; secondary sources (pricing guides, news) are labeled as such and used only for list prices that vendors hide behind JS-rendered pages. Costs marked **[unverified]** could not be confirmed from a primary page.
- **Repo context:** V1 (`exchange/oanda.py`, `docs/agents/fx-ops.md`) runs OANDA v20 **practice**, REST-polling only (no streams), with `clientExtensions` lane tags, server-side SL/TP, and venue-authoritative state. None of the below requires touching V1's live tree.

---

## Part 0 — What carries over from V1 (OANDA v20 practice)

V1 already speaks v20 REST against `https://api-fxpractice.oanda.com` with a personal access token (`exchange/oanda.py:69`). The v20 surface V1 uses (orders, pricing, instruments, transactions, candle history, account state) is the **same API in production** — the only differences at `api-fxtrade.oanda.com` are the account and the regulatory reality of live money. Concretely, the following V1 assets transfer unchanged:

- Bearer-token auth, one host swap for live (practice vs live endpoints documented side by side in the [v20 Development Guide](https://developer.oanda.com/rest-live-v20/development-guide/)).
- Order semantics V1 already encodes truthfully (no `orderFillTransaction` = rejected, guaranteed-stop cancels) — this is venue behavior, identical live.
- `clientExtensions` lane tagging + the shared resolver — venue-side feature, carries over.
- Full order type set: market, market-if-touched, stop, limit, TP/SL, trailing stop, OCO (TP/SL pair only), FOK/IOC/DAY/GTD(≤100d)/GTC durations, price bounds, partial close ([v20 API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)).
- Candle history from S5 to monthly, 5000 records/page, complete depth ([API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)).

What V1 does **not** use yet and V2 should inherit from the same API:

- **Streaming pricing** (`stream-fxpractice.oanda.com`, ≤20 active streams/IP, ≤2 new connections/s) and the **transactions/events stream** ("all account and trading related events" — [API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)). This would replace V1's polling entirely; REST is capped at 120 req/s/IP ([Development Guide](https://developer.oanda.com/rest-live-v20/development-guide/)).
- v20 FIX is "Institutional customers only" — irrelevant for V2 ([API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)).

**Practice-account cost:** $0, self-serve (demo signup: [hub.oanda.com/apply/demo](https://hub.oanda.com/apply/demo); "API Enabled: Online/Self-serve" per the [API comparison](https://developer.oanda.com/rest-live-v20/api-comparison/)). Expiry policy on inactivity is **[unverified]** — no primary page states it; the empirical evidence is that V1's practice account has run continuously since 2026-09.

**Live costs (when eventually promoted):** OANDA offers spread-only pricing or "core pricing" — commission $50 per $1M traded on ~70 FX pairs with raw spreads (announcement: [Investopedia, secondary](https://www.investopedia.com/news/oanda-introduces-core-pricing/)); $20 inactivity fee after 12 months ([Investopedia, secondary](https://www.investopedia.com/best-brokers-for-forex-trading-4587882)). US entity trades currencies + metals + CFDs per division (v20 docs: "Trade currencies, metals, and CFD's" — [Development Guide](https://developer.oanda.com/rest-live-v20/development-guide/)).

---

## Part 1 — Trading venue comparison

### Table 1 — Venues at a glance

| | **OANDA v20** (V1, carries over) | **Interactive Brokers** | **Alpaca** | **cTrader Open API** | **MetaTrader 5** | **LMAX Global** (B2B FX exemplar) |
|---|---|---|---|---|---|---|
| **Assets** | FX (~70 pairs), metals, CFDs (division-dependent) | Global: equities, options, futures, FX, bonds, metals, funds | US stocks/ETFs, options, crypto (no FX) | FX + CFDs incl. indices/commodities (broker-dependent) | Broker-dependent: FX, CFDs, exchange futures/stocks | 100+ instruments: FX, metals, indices, commodities, crypto CFDs |
| **Order types** | Market/Limit/Stop/MarketIfTouched/TP-SL/trailing/OCO(TP+SL)/bounds; FOK-IOC-DAY-GTD-GTC | TWS: full suite incl. bracket/conditional; CP Web API: large subset, "may not have full parity yet" | Market, Limit, Stop, Stop-Limit, + advanced bracket/OCO | Everything official cTrader apps can do | Broker/terminal-dependent | CLOB limit/market (price-time priority, no last look) |
| **Streaming model** | HTTP price stream + events stream (≤20 streams/IP) | TWS: TCP socket callbacks; CP API: REST + WebSocket market data | REST + WebSocket | Protobuf/JSON messages over persistent connection | Terminal-local; bridges vary | MTF matching (~3ms avg); API via engagement (FIX standard) **[verify w/ sales]** |
| **Rate limits** | REST 120 req/s/IP; 20 streams; 2 conn/s | Not published globally; 100 concurrent data lines default | 200/min free → 10,000/min paid; 30→∞ WS symbols | 50 req/s non-historical, 5 req/s historical per connection | Broker/terminal-dependent | Not published |
| **Pricing (trading)** | Spread-only or core ($50/M, secondary) | Commissions; FX quotes data fee-waived | Commission-free stocks (options extra); no FX | Broker spreads/commissions | Broker spreads + bridge costs (MetaApi subscription) | Institutional spreads; application-based onboarding |
| **Auth** | Bearer personal access token | TWS: local socket (no auth); CP API: login via gateway session (daily 2FA re-auth), OAuth 1.0a possible | API key/secret headers; OAuth (Broker API) | OAuth2 cTID application; Protobuf or JSON | Broker login; MetaApi = cloud token | Institutional onboarding |
| **Paper/demo** | **Practice — live in V1 since 2026-09, $0** | **Paper account, free** | **Paper account, free, $100k default, free IEX real-time** | **Demo accounts, free, via API** | Demo accounts (broker-dependent, free) | Not advertised; application-based |
| **Rust story** | REST/WSS only (`oanda` crate v0.1.0/2023 = dead) | `ibapi` 5.0.0 (TWS, active, 234k dl) or `ibkr` 0.6.0 (CP Web API, new); or plain REST/WSS | REST/WSS only (no official Rust; official: Python/Go/JS/C#) | No crate; Spotware protobufs via prost/tonic, or JSON | No crate; MetaApi REST/WSS or ZeroMQ bridge | FIX via `quickfix` crate (0.2.2, 408k dl) |

### 1.1 OANDA v20 — see Part 0. Recommended as-is for launch.

### 1.2 Interactive Brokers

**Two distinct APIs** ([IBKR API page](https://www.interactivebrokers.com/en/trading/ib-api.php)):

- **TWS API** — TCP socket protocol to TWS or IB Gateway; official clients in Python/Java/C++/C#/VB; language-agnostic by design ("any library… must be sending and receiving these data in the same format" — [TWS API introduction](https://www.interactivebrokers.com/docs/tws-api/doc/introduction)). Headless operation via community [ib-gateway-docker](https://github.com/gnzsnz/ib-gateway-docker) (IB Gateway + IBC).
- **Client Portal Web API** — REST over a local Java gateway (`https://localhost:5000/v1/api/…`), requires a **funded IBKR account** and browser login to authenticate the session ([campus lesson: Launching and Authenticating the Gateway](https://www.interactivebrokers.com/campus/trading-lessons/launching-and-authenticating-the-gateway/)); lighter than TWS but "much younger… may not have full parity quite yet" ([campus lesson: What is the CP API](https://www.interactivebrokers.com/campus/trading-lessons/what-is-ibkrs-client-portal-api/)). Docs: [interactivebrokers.github.io/cpwebapi](https://interactivebrokers.github.io/cpwebapi/).

**Paper trading:** free IBKR paper accounts (campus signup offers a "free IBKR paper trading account"; lessons recommend paper before live).

**Market data (individual non-pro, from the [IBKR Market Data Pricing page](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)):**

- Free: real-time non-consolidated US streaming (Cboe One + IEX), 100 concurrent lines default (scales with commissions/equity), 100 snapshot quotes/mo.
- US Securities Snapshot & Futures Value Bundle: **$10/mo** (waived at ≥$30/mo commissions).
- OPRA Top-of-Book (L1): **$1.50/mo non-pro** (waived at ≥$20/mo commissions; $32.75/mo professional).
- CME/CBOT/NYMEX/COMEX real-time L1: **$1.55/mo each** non-pro (L2 $12.10).
- **IBKR Currencies (FX): Fee Waived.**
- Min $500 equity to hold data subscriptions; commission waivers make effective cost $0 for an active account.

**Rust:** [`ibapi`](https://crates.io/crates/ibapi) v5.0.0 — unofficial but actively maintained (updated 2026-10; 234k downloads, 103k in the last 90 days), async + blocking clients for TWS and IB Gateway. [`ibkr`](https://crates.io/crates/ibkr) v0.6.0 — typed Client Portal Web API client with first-party OAuth 1.0a for headless access (new, low adoption). Alternatively plain REST/WSS against the CP gateway.

**Fit:** the broadest multi-asset paper environment available to an individual (equities + options + futures incl. CME FX futures + FX IDEALPRO + bonds + metals), with a genuinely free paper account and near-free data. The tax: a JVM gateway and session babysitting (CP) or a local socket daemon (TWS).

### 1.3 Alpaca

- **Assets:** US stocks/ETFs, options, crypto ([api-evangelist overview, secondary](https://github.com/api-evangelist/alpaca); official docs). **No FX trading** — its data API carries FX only via crypto/none.
- **Paper:** free for all users, real-time IEX data, default $100k, unlimited resets; paper-only accounts are IEX-entitled; simulates fills against NBBO, no market impact/slippage modeling (official: [Paper Trading doc](https://docs.alpaca.markets/us/docs/paper-trading)).
- **Order types:** market, limit, stop, stop-limit plus advanced bracket/OCO ([alpaca.markets/stocks](https://alpaca.markets/stocks)); fractional for market/limit/stop/stop-limit day orders ([docs](https://docs.alpaca.markets/us/docs/fractional-trading)).
- **Auth:** `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers; OAuth client-credentials for Broker API ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api)).
- **Rust:** official SDKs are Python/Go/NodeJS/C# only ([docs](https://docs.alpaca.markets/us/docs/about-market-data-api)); no official Rust; the `alpaca` crates.io name is an unrelated bioinformatics package. REST/WSS is simple enough to hand-roll.

**Fit:** the cheapest credible equities/crypto paper lane for V2's multi-asset leg — $0 — but no FX.

### 1.4 cTrader Open API

- Protocol/SDK: Protobuf or JSON over a persistent connection to the cTrader backend; **official SDKs C# and Python only**; demo **and** live trading both supported through the API (official: [Open API overview](https://help.ctrader.com/open-api/)).
- Rate limits: 50 req/s non-historical, 5 req/s historical **per connection** (same page).
- Assets: FX + CFDs through any cTrader-affiliated broker; instruments broker-dependent ([ctrader.com](https://ctrader.com/) "Forex & CFD trading platform").
- Paper: demo accounts recommended for development, no hard restrictions (same overview page).
- **Rust:** no `ctrader` crate on crates.io (checked 2026-10-04). Path: compile Spotware's public protobufs with prost/tonic, or use JSON mode.

**Fit:** attractive second FX venue (broker-diversified, true multi-asset CFDs, clean protocol, free demo) — but adds a second broker relationship for instruments OANDA already covers.

### 1.5 MetaTrader 5 (bridge options)

- MetaQuotes' only sanctioned programmatic integration is the `metatrader5` Python package — **Windows x86-64 wheels only** ([PyPI release files](https://pypi.org/project/metatrader5/)); the API binds to a locally running MT5 terminal.
- Bridge options:
  - **MetaApi** cloud service — REST/WebSocket MT4/MT5 access, language-neutral, subscription tiers (one free MT account, 7-day trials, historical market data access, dedicated servers at higher tiers); current per-account prices are behind a JS pricing widget / "temporarily unavailable" API-pricing banner **[unverified]** ([metaapi.cloud](https://metaapi.cloud/)).
  - **ZeroMQ EA bridges** (community): MT terminal hosts an EA, Rust/Python talks ZeroMQ (e.g. [eareview tick-data bridges list, secondary](https://eareview.net/tick-data-suite)).
  - **Wine + terminal** on Linux (unsupported by MetaQuotes).
- **Rust:** no crate; MetaApi is plain REST/WSS; ZeroMQ usable from Rust.
- **Fit:** recommend **against** for V2 unless a specific instrument only exists behind an MT5 broker. Windows coupling (or a paid cloud middleman) is a permanent operational tax, and every broker-era defect class we documented in V1 (venue truth vs cache) gets worse through bridges.

### 1.6 B2B FX venues — LMAX Global as the exemplar

- LMAX Global = the professional/retail arm of LMAX Group (FCA UK, CySEC EU, NZ, Mauritius): "brokers and professional traders", 100+ instruments (FX, metals, equity indices, commodities, crypto CFDs), MTF CLOB with strict price/time priority, no last-look rejections, ~3ms average matching, liquidity pools in London/NY/Tokyo/Singapore (official: [lmax.com/global](https://www.lmax.com/global)). Onboarding is application-based ("Apply for an LMAX Global account"), not self-serve.
- API access: engagement-based; FIX connectivity is the institutional standard (the page does not publish self-serve API docs — **[verify with sales]**). Rust can speak FIX via the maintained [`quickfix`](https://crates.io/crates/quickfix) bindings (C++ QuickFIX, 408k downloads, active).
- **Fit:** phase-2+ only — the destination if/when the FX arm graduates from retail practice to venue-grade execution; not a V2 launch candidate.

---

## Part 2 — Market-data feed comparison

### Table 2 — Feeds at a glance

| | **Massive (ex-Polygon.io)** | **Databento** | **Alpaca data** | **IBKR data subs** | **dxFeed** | **IEX Cloud** | **FX tick feeds** (OANDA stream, Dukascopy, TrueFX) |
|---|---|---|---|---|---|---|---|
| **Assets** | US stocks, options, forex (1k+ pairs), crypto, indices | Equities, options (OPRA), futures (CME/CBOT/NYMEX/COMEX), 45+ venues, 650k+ symbols | US stocks (IEX/SIP), options (OPRA/indicative), crypto | Global per-exchange subs (incl. CME L1, OPRA L1, FX waived) | Everything (equities/futures/options/FX/indices/crypto) | — **service shut down 2024-08-31** | FX majors/crosses |
| **Streaming** | REST + WebSocket (Advanced tiers) | Raw TCP / WSS via official clients | REST + WebSocket | TWS/CP streaming (100 lines default) | FIX/web/proprietary | — | WSS (OANDA), FIX (TrueFX) |
| **History** | 2y → 20+y by tier | 16+y CME futures; 1y L1 / 1mo L2-L3 on Standard | Since 2016 | Long per-exchange | Deep, customized | — | Dukascopy: free tick→monthly export |
| **Rate limits** | 5 calls/min free; unlimited paid | Unlimited API calls | 200/min → 10k/min | 100 concurrent lines | Contract | — | OANDA: 20 streams |
| **Pricing (non-pro)** | Stocks: $0/$29/$79/$199; FX: ~$29/~$199; Options: ~$99/~$249 (ladders partly secondary) | $0 usage-based + $125 credits; Standard **$199/mo** (licenses incl.); Plus $1,750/mo | Free Basic (IEX); **$99/mo** Algo Trader Plus | $1.50-$10 subs, waivable | **Enterprise, sales-only** | — | OANDA free w/ account; Dukascopy free; TrueFX **$4,950/mo** Pro |
| **Auth** | API key (Bearer) | API key | Key/secret | Gateway session | Contract/SDK key | — | Token/registration |
| **Rust** | No official (Python/Go/JS official) | **Official crate, 983k dl** | Hand-roll REST/WSS | via `ibapi`/`ibkr` | `dxfeed` crate = bindings to licensed C SDK | — | REST/WSS or FIX |

### 2.1 Massive (formerly Polygon.io)

Polygon.io became Massive.com on 2025-10-30; keys/accounts/`api.polygon.io` endpoints continue to work during the transition ([Massive blog via QVeris, secondary](https://qveris.ai/guides/polygon-pricing-optimized)). Their pricing page is JS-rendered (no scrapeable numbers), so tier prices below mix a 2026-verified guide and an older published schedule:

- **Stocks (2026-verified, secondary):** Basic $0 (EOD, 5 calls/min, 2y) → Starter $29 (unlimited calls, 15-min delayed, 5y, WSS/flat files) → Developer $79 (10y, trades, still delayed) → Advanced $199 (real-time, quotes, 20+y, flat files) ([QVeris guide, checked 2026-07-24, secondary](https://qveris.ai/guides/polygon-pricing-optimized)).
- **Other ladders (older published schedule, secondary — re-verify before buying):** Options Developer $99 / Advanced $249; Crypto Starter $29 / Advanced $199; **Forex Starter ~$29 (1,000+ pairs, aggregates)** / **Advanced ~$199 (real-time + WebSocket)**; Indices Developer $49 ([apis.io plan profile](https://apis.io/plans/massive-com/polygon-plans-pricing/)).
- Conflict to flag: the older schedule lists Stocks Developer as IEX-real-time; the 2026 guide says Developer is delayed and real-time starts at Advanced. Trust the 2026 guide, but confirm on the live pricing page at purchase time.

### 2.2 Databento

From the official [pricing page](https://databento.com/pricing): usage-based historical ($/GB, no subscription, **$125 free credits** on signup), **Standard $199/mo** (live + historical, **exchange license fees included**, 1 year L1 history, 1 month L2/L3, up to 2 devices), Plus $1,750/mo (annual contract, external distribution), Unlimited $4,500/mo. Core historical CME/CBOT/NYMEX/COMEX is usage-based; usage-based *live* was being deprecated (US equities unavailable; deprecation of other datasets announced for 2025-03-31). 45+ exchanges, 650k+ symbols, 16+ years futures history; self-service licensing with a non-pro questionnaire. **Rust: an official first-party client** — "Python, C++, and Rust client libraries" (pricing page); the [`databento`](https://crates.io/crates/databento) crate has 983k downloads and is actively maintained. For FX specifically, Databento's relevant product is **CME FX futures** (not spot).

### 2.3 Alpaca data plans

Official ([About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api)): Basic (free, default on paper+live): IEX-only equities, indicative-only options, 30 WS symbols, latest-15-min historical restriction, 200 calls/min. **Algo Trader Plus $99/mo**: all US exchanges (SIP), OPRA options feed, unlimited WS symbols, 10,000 calls/min. (Broker API partner tiers: $0 Standard → $2,000/mo StandardPlus10000.) No FX product.

### 2.4 IBKR subscriptions — see §1.2. Cheapest credible path to consolidated-ish US equities + OPRA + CME data for an individual, with waivers making it ~$0 for active accounts.

### 2.5 dxFeed — licensing reality

dxFeed (Devexperts) is a **B2B market-data vendor**: real-time/delayed/historical feeds across all asset classes ([dxfeed.com/market-data](https://dxfeed.com/market-data/)), listed as an OPRA Vendor with terminals/datafeeds/APIs ([OPRA participant-vendor list](https://www.opraplan.com/)). There is **no public price list, no self-serve individual tier, no published API** — sales engagement, enterprise contract, and SDKs in C++/Java/.NET. Community Rust bindings exist ([`dxfeed` crate](https://crates.io/crates/dxfeed), v0.2.4, wraps the licensed C SDK `libdxfeed-sys`) but they presuppose the C SDK license. Typical contract sizes are quoted anecdotally in the $500+/mo range — **[unverified]**. **Conclusion: dxFeed is a phase-2/enterprise option only; it is not procurable at MVP budget.**

### 2.6 IEX Cloud — dead

IEX Group announced 2024-05-31 that all IEX Cloud products would retire, and the service **ceased operating 2024-08-31** ([Wikipedia: IEX](https://en.wikipedia.org/wiki/IEX); [Alpha Vantage migration analysis, secondary](https://www.alphavantage.co/iexcloud_shutdown_analysis_and_migration/)). The IEX *exchange* lives on and its quotes are consumed through vendors (free via Alpaca Basic or IBKR's free non-consolidated Cboe One + IEX streaming — [IBKR pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)). **Remove IEX Cloud from any V2 plan; route IEX data through those two free paths.**

### 2.7 OPRA costs (options)

OPRA is the consolidated SIP for US options; recipients are Vendors (redistribution, direct contract) or Subscribers (internal use), each non-professional or professional; delayed data carries no fees; non-pros receive via a Vendor and the Vendor pays OPRA's small per-subscriber fees ([OPRA overview](https://www.opraplan.com/)). Practical non-pro costs by vendor:

- **IBKR:** OPRA Top-of-Book L1 $1.50/mo (waived at ≥$20/mo commissions) — [IBKR pricing page](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php).
- **Alpaca:** OPRA feed included in Algo Trader Plus $99/mo ([Alpaca docs](https://docs.alpaca.markets/us/docs/about-market-data-api)).
- **Databento:** OPRA license fees included in Standard $199/mo ([Databento pricing](https://databento.com/pricing)).
- **Massive:** Options Developer ~$99 / Advanced ~$249 ([apis.io, secondary](https://apis.io/plans/massive-com/polygon-plans-pricing/)).
- Direct/professional: IBKR lists OPRA pro at $32.75/mo; direct OPRA Vendor contracts are enterprise-priced by fee schedule.

### 2.8 FX tick feeds

- **OANDA v20 pricing stream** — free with the account V1 already has; ≤20 concurrent streams; ticks + heartbeats ([Development Guide](https://developer.oanda.com/rest-live-v20/development-guide/)). First choice for V2 live paper.
- **Dukascopy Historical Data Export** — free download of FX/commodities data from tick-by-tick to monthly granularity ([Dukascopy historical page](https://www.dukascopy.com/swiss/english/marketwatch/historical/)). The default backtest corpus for FX.
- **TrueFX** — indicative interbank streaming (Integral OCX sourcing); now marketed as B2B plans: **Professional $4,950/mo**, Institutional $7,450/mo with 3-level depth, FIX delivery ([truefx.com](https://www.truefx.com/)). The historically-free public API is no longer advertised — **[free tier: unverified]**. Enterprise-tier only.
- **Databento CME FX futures** (usage-based / Standard $199/mo) — the exchange-traded FX proxy.
- **Massive Currencies** — ~$29 (aggregates, 1k+ pairs) to ~$199 real-time/WSS ([apis.io, secondary](https://apis.io/plans/massive-com/polygon-plans-pricing/)).

---

## Part 3 — Rust client story (crates.io, checked 2026-10-04)

| Venue/feed | Crate | Version / status | Downloads | Verdict |
|---|---|---|---|---|
| OANDA v20 | `oanda` | v0.1.0, 2023, no repo — effectively dead | 1.5k | **REST/WSS-only**; surface is small (V1's adapter proves it) |
| IBKR TWS | `ibapi` (wboayue/rust-ibapi) | v5.0.0, updated 2026-10, async+blocking | 234k (103k recent) | **Usable, actively maintained**, unofficial |
| IBKR CP Web API | `ibkr` | v0.6.0, 2025-11 created, OAuth 1.0a headless | 254 | promising but young — audit before trusting |
| Alpaca | — (official: Python/Go/JS/C#) | — | — | **REST/WSS-only**, hand-rolled |
| cTrader | — (none exists) | — | — | compile Spotware protobufs (prost/tonic) or JSON mode |
| MT5 | — (none exists) | — | — | MetaApi cloud REST/WSS or ZeroMQ bridge |
| FIX venues (LMAX) | `quickfix` (quickfix-rs) | v0.2.2, updated 2026-10, C++ bindings | 408k | viable for any FIX venue |
| Databento | `databento` (**official**) | v0.63.0, updated 2026-09 | 983k | **best-in-class**: first-party official Rust |
| dxFeed | `dxfeed` (spotgamma) | v0.2.4, bindings to licensed C SDK | 22k | only useful after an enterprise dxFeed contract |

Bottom line: for a Rust V2, **OANDA/Alpaca are thin REST/WSS adapters; IBKR has a real crate for TWS; Databento is the only feed with an official Rust client.** cTrader/MT5 have no first-class path — consistent with ranking them phase-2.

---

## Part 4 — Recommended shortlist (for the human to lock — not a verdict)

### Launch set (V2 MVP, paper-first, estimated ≈ $0–$12/mo)

1. **OANDA v20 — carry V1 over wholesale + add streaming.** Already-live practice env, one host swap for future live. $0. Action: v2 adapter = V1 semantics + pricing/events streams.
2. **IBKR paper account + one of its two APIs — the multi-asset leg.** Equities/options/futures/bonds/metals/FX (IDEALPRO) in one paper account, free; data effectively free (Cboe One+IEX non-consolidated streaming; $1.50 OPRA L1 and $1.55 CME L1 waivable; FX quotes waived). Rust: `ibapi` (TWS socket, mature crate) vs `ibkr` (CP Web API, REST+OAuth headless) — pick one; that choice is the first thing to lock.
3. **Alpaca paper — optional equities/crypto second opinion.** $0, free real-time IEX, dead-simple REST/WSS. Include only if V2 wants a zero-cost equities lane independent of IBKR onboarding.
4. **Backtest corpus:** Dukascopy free FX tick export + OANDA candle history (+ Databento $125 free credits for equities/options/futures history).

**Estimated launch cost: $0/month fixed** (IBKR subs optional: +$1.50–$10.00 until commission waivers kick in). Exchange-rate pain at $0: non-consolidated US quotes and IEX-only Alpaca.

### Phase-2 candidates (unlock when a concrete need appears)

| Candidate | Trigger | Est. cost |
|---|---|---|
| **Databento Standard** | research needs bulk/live OPRA or CME (incl. FX futures) history | $199/mo |
| **Alpaca Algo Trader Plus** | SIP/OPRA breadth without IBKR | $99/mo |
| **Massive (Polygon)** | need 1k+ FX pairs aggregate data or their equities breadth | $29–$199/mo per ladder |
| **cTrader Open API** | second FX venue / broker-diversified CFDs, free demo | $0 to develop; broker spreads live |
| **MT5 (MetaApi/ZeroMQ)** | an instrument only available behind an MT5 broker | MetaApi subscription **[unverified]** + broker costs |
| **LMAX Global** | graduating FX execution to a professional MTF venue | application-based |
| **dxFeed / TrueFX Professional** | institutional-grade consolidated feeds | enterprise (TrueFX $4,950/mo; dxFeed sales-only) |

### Explicitly retired

- **IEX Cloud** — service shut down 2024-08-31.
- **`oanda` Rust crate** — dead; hand-roll.
- **MT5 as a launch venue** — Windows/broker taxes out of the gate.

---

## Part 5 — Decisions the human needs to lock

1. **Launch shortlist:** OANDA(carry-over) + IBKR paper + optional Alpaca paper — yes/no?
2. **IBKR adapter path:** TWS API via `ibapi` (mature, socket daemon) vs Client Portal Web API via `ibkr` (REST, newer, not full parity, session re-auth)? 
3. **Data budget for phase-2:** none / one $99 tier / one $199 tier?
4. **Venue exclusions:** confirm cTrader, MT5, LMAX, dxFeed deferred (not excluded) until their triggers fire.
5. **Professional-status risk:** all costs above assume individual non-pro status; any move toward managing external money flips many of these to professional/enterprise pricing (e.g. OPRA $32.75/mo+ via IBKR, Databento Plus $1,750/mo) and voids retail pricing ladders — worth an explicit guardrail in the V2 spec.

---

## Sources

Primary (fetched 2026-10-04): OANDA [Development Guide](https://developer.oanda.com/rest-live-v20/development-guide/), [API Comparison](https://developer.oanda.com/rest-live-v20/api-comparison/), [demo apply](https://hub.oanda.com/apply/demo) · IBKR [TWS API intro](https://www.interactivebrokers.com/docs/tws-api/doc/introduction), [Market Data Pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php), [IB API page](https://www.interactivebrokers.com/en/trading/ib-api.php), [campus CP-API lessons](https://www.interactivebrokers.com/campus/trading-lessons/what-is-ibkrs-client-portal-api/) · Alpaca [Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading), [About Market Data API](https://docs.alpaca.markets/us/docs/about-market-data-api), [Fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading), [stocks page](https://alpaca.markets/stocks) · cTrader [Open API overview](https://help.ctrader.com/open-api/) · MetaQuotes [metatrader5 on PyPI](https://pypi.org/project/metatrader5/), [MetaApi](https://metaapi.cloud/) · LMAX [Global](https://www.lmax.com/global) · Databento [Pricing](https://databento.com/pricing) · OPRA [overview](https://www.opraplan.com/) · TrueFX [homepage](https://www.truefx.com/) · Dukascopy [historical data export](https://www.dukascopy.com/swiss/english/marketwatch/historical/) · Massive [pricing](https://massive.com/pricing), [currencies](https://massive.com/currencies) · crates.io API records for `oanda`, `ibapi`, `ibkr`, `databento`, `dxfeed`, `quickfeed` · repo `exchange/oanda.py` (read-only).

Secondary (labeled at point of use): QVeris [Polygon/Massive pricing guide 2026](https://qveris.ai/guides/polygon-pricing-optimized) · apis.io [Massive plan profile](https://apis.io/plans/massive-com/polygon-plans-pricing/) · Investopedia [OANDA core pricing](https://www.investopedia.com/news/oanda-introduces-core-pricing/), [Best forex brokers 2026](https://www.investopedia.com/best-brokers-for-forex-trading-4587882) · Wikipedia [IEX](https://en.wikipedia.org/wiki/IEX) · Alpha Vantage [IEX Cloud shutdown analysis](https://www.alphavantage.co/iexcloud_shutdown_analysis_and_migration/) · api-evangelist [Alpaca overview](https://github.com/api-evangelist/alpaca) · gnzsnz/ib-gateway-docker.
