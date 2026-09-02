# The Jane Street Playbook: What a Market Maker Actually Does, and What a Retail-Scale Harness Can Steal

**Research note — read-only, no code changes.**
**Context:** OpenTrader is a rule-primary momentum harness (daily bars via Finnhub, SPY-vs-96d regime gate, VIX z-score gate that has blocked all fills for 600+ cycles in calm regimes). The question: what does Jane Street actually do, in the microstructural sense, and which of those techniques are concretely transplantable into a retail-scale, daily-bar, long-only systematic system?

**Method:** every claim below is checked against its primary source — Jane Street's own pages ([page]), Signals & Threads transcripts ([transcript]), arXiv abstracts ([abstract]), full paper text ([text]), or Crossref bibliographic records. Claims that cannot be traced are labeled **[inference]**. No quotes are fabricated; every quotation is verbatim from the cited source. Verified 2026-08-12.

---

## 1. Executive summary — what Jane Street actually does

- **Jane Street is a liquidity provider first, a directional trader second.** Their own pages describe the firm as "a leading market maker and liquidity provider," pricing >10,000 ETFs (primary and secondary markets), >25,000 bonds, ~3,800 option classes, and equities on 200+ venues in 45+ countries; they report ~$400B of daily filled dollars and >$900B of client bond trading in 2025 ([page] janestreet.com client-offering; ML page).
- **Their edge is microstructural, not predictive-of-direction.** They earn the spread and the arbitrage between related instruments (ETF vs basket, cash vs derivatives, cross-venue). The "who-we-are" page is explicit: "We understand individual products and the context that informs their prices down to their subtlest details. This allows us to provide liquidity during the market's most volatile moments" ([page] who-we-are).
- **They treat markets as a low-signal, regime-shifting environment and organize research accordingly.** ML research lead In Young Cho: financial ML is "one unit of useful data and 99 units of garbage and you do not know what the useful data is and you do not know what the garbage or noise is"; Ron Minsky: markets are "mostly now random and find a little bit of remaining signal" because "when you see regularities in the behavior of prices, you're incentivized to trade against those and that beats them out of the market" ([transcript] Signals & Threads ep. 22, "Finding Signal in the Noise," 2025-03-10).
- **Their alpha is managed at the level of inventory and adverse selection, not at the level of "which way is the market going."** The canonical literature they sit on (Glosten–Milgrom 1985; Kyle 1985; Avellaneda–Stoikov 2008; Guéant–Lehalle–Fernandez-Tapia 2013) frames the problem as: quote a two-sided price such that spread income minus expected losses to better-informed counterparties minus the cost of holding unwanted inventory is positive.
- **They are explicitly a research lab with a trading desk attached** ("Think of Jane Street as a research lab with a trading desk attached to it," ML page), with a stated belief that "deep learning is the future of quantitative trading" — but their own research leader stresses that the same discipline of simple-first models, out-of-sample honesty, and few hypotheses applies in low-data regimes ([transcript] ep. 22).
- **Risk is studied as correlations and tails, and that is what funds boldness.** "We carefully study how trading risks might be bigger or more interrelated than they appear, and this allows us to be especially bold" ([page] who-we-are) — i.e., the risk system, not the signal, is the capacity constraint.
- **What this harness can steal is not the edge itself but the control layers:** realized-vol forecasting instead of a binary VIX gate, order-flow/imbalance features, session-split execution, inventory-style position management, and cross-sectional (market-neutral) residual signals for the planned portfolio ranker. What it cannot steal: speed, flow knowledge, capital, and the maker/rebate infrastructure ([§4](#4-what-cannot-be-replicated-honest-limits)).

---

## 2. Their edge mechanics — why market makers win

### 2.1 The spread is compensation for adverse selection, not for effort

The foundational result is Glosten & Milgrom (1985), "Bid, ask and transaction prices in a specialist market with heterogeneously informed traders," *Journal of Financial Economics* 14(1), 71–100, doi:10.1016/0304-405X(85)90044-3 [Crossref record]. Their model shows the bid-ask spread arises from asymmetric information: a market maker who quotes both sides loses on average to informed traders who only trade when the quote is to their advantage, and recovers that loss from uninformed ("liquidity-motivated") traders. The spread is thus a toll on information asymmetry. Kyle (1985), "Continuous Auctions and Insider Trading," *Econometrica* 53(6), 1315–1335, doi:10.2307/1913210 [Crossref record], formalizes the other half: the price impact of an order is itself a signal of information (the famous λ). Together: **adverse selection is the tax, and the spread is the toll that covers it.**

### 2.2 How a market maker's day actually works (in their own words)

The Signals & Threads episode 22 transcript gives the internal description, via a concrete example of a pension fund's quarterly rebalance ([transcript] ep. 22, In Young Cho):

> "being on the opposite side of a flow that is millions of dollars can be quite disconcerting. You'll have on your computer program that is designed to interact on the exchange, sold a share of XYZ stock, and then you'll continue to sell on the exchange and you'll basically say, **what am I missing? How large is the eventual size going to be?** And in that uncertainty, a thing that you might say is, well, it might just be the case that I'm getting something very wrong and I'm going to make sure that I do something a little bit more conservative while I try to figure things out."

Three mechanics are visible in this passage:

1. **Flow uncertainty ⇒ quote conservatism.** An unexplained stream of one-sided fills is treated as possible informed flow, and the response is to reduce size/aggressiveness until the flow's nature is identified. This is the operational form of adverse selection management.
2. **Counterparty identity is information.** The same flow from a known pension rebalance is benign; from an unknown counterpart it is toxic. Knowing the counterparty changes the quote (the episode describes charging a better price to a known, benign rebalancer).
3. **The profit function is two-sided.** They monetize flow by being on both sides across many instruments, not by predicting direction. Their client page: "we excel at providing competitive prices even during periods of dislocation and volatility, and by holding and managing risk over longer time periods we can execute complicated trades with less market impact" ([page] client-offering) — the phrase "holding and managing risk" is the inventory dimension.

### 2.3 Inventory risk and quote skewing — the formal machinery

The quantitative framework (all verified [abstract], arXiv):

- **Avellaneda & Stoikov (2008), "High-frequency trading in a limit order book," *Quantitative Finance* 8(3), 217–224, doi:10.1080/14697680701381228** — the canonical model: a market maker maximizes expected terminal wealth (with a risk-aversion parameter γ) by choosing bid/ask quotes; order arrival intensity falls with the distance of the quote from the mid-price, and inventory creates variance, so the optimal quotes **skew away from inventory** — long inventory ⇒ lower the bid relative to the ask. The key output: the optimal spread grows with volatility (σ), risk aversion (γ), and remaining horizon (T).
- **Guéant, Lehalle & Fernandez-Tapia (2013), "Dealing with the Inventory Risk," *Mathematics and Financial Economics* 7(4), 477–495, doi:10.1007/s11579-012-0087-0** — extends the framework under explicit inventory constraints; shows optimal quotes under an inventory cap, again skewed by inventory, with closed-form approximations.
- **Guéant (2016), "Optimal market making," arXiv:1605.01862** [abstract]: the survey abstract states the structure plainly: "Since they seldom buy and sell simultaneously, and therefore hold long and/or short inventories, they also need to mitigate the risk associated with price changes, and subsequently **skew their quotes dynamically**."
- **Fodra & Labadie (2012), "High-frequency market-making with inventory constraints and directional bets," arXiv:1206.4810** [abstract]: shows how a maker can "make directional bets on market trends whilst keeping under control her inventory risk" — non-symmetric quotes that favor being hit on the side consistent with the bet, with an inventory-risk-aversion parameter trading off P&L mean vs variance (in their numerics, giving up ~5% of benchmark P&L roughly doubled the Sharpe).

**The synthesis for this repo's purposes [inference from the above, labeled]:** a market maker's "alpha" is (i) spread capture from being passive, (ii) priced for adverse selection via the spread, (iii) capped by inventory risk via quote skewing. There is no point in this chain that requires predicting direction; the risk-bearing capacity of the inventory is the binding constraint, and volatility enters every formula as a *continuous* quantity (σ), never as a binary gate.

### 2.4 ETF arbitrage as the archetype of their non-directional edge

Jane Street's flagship product is ETF market making in both primary and secondary markets (>10,000 ETFs; "trading spanning both the primary and secondary ETF markets," client-offering page). The primary/secondary mechanism — buying (creating) or redeeming ETF shares against the underlying basket when the ETF price deviates from its NAV — is a **relative-value arbitrage**: it needs no opinion on the market, only on the *dislocation* between two linked prices, and it is bounded by creation/redemption fees. **[inference from the page's description + standard market-structure mechanics]** This is the same logic as their cross-asset options/underlying trading: price the relationships, hold the residual, skew the quotes. The deep point for a small trader: Jane Street's directional exposure is a *byproduct* of a relative-value book, hedged across instruments, not a forecast.

---

## 3. Translatable techniques (concrete, mapped to this harness)

The harness's current architecture (from CONTEXT.md and the code, verified read-only): rule floor = walkforward-validated long-only rule; regime = SPY vs 96-day average; `data/vix_gate.py` blocks all trading unless trailing-250 VIX z-score ≥ 0.5 (validated +12.47%/day vs +4.13% always, but currently 0 fills over 600+ cycles because calm days never open the gate); paper fills happen at the last known close in one shot with a static slippage percentage (`exchange/paper.py`).

The following techniques are ordered roughly by (value to this system) × (ease of implementation with daily data).

### T1. Replace the binary VIX gate with a continuous realized-vol forecast (HAR / range-based)

- **Source:** Corsi (2009), "A Simple Approximate Long-Memory Model of Realized Volatility," *Journal of Financial Econometrics* 7(2), 174–196, doi:10.1093/jjfinec/nbp001 [Crossref record; working version SSRN doi:10.2139/ssrn.626064]. The HAR model regresses today's realized volatility on its daily, weekly, and monthly components — a "heterogeneous autoregression" that reproduces long-memory behavior with a handful of OLS coefficients and is the standard practical vol forecaster [abstract; formulation is the paper's title object].
- **The flaw in the current gate it replaces:** `vix_gate.py` computes a 250-day z-score of VIXCLS and returns a boolean. That is a *level* filter on implied vol, not a forecast; it is externally dependent (FRED), and its failure mode is exactly what the harness has experienced: a binary on/off with a threshold calibrated on a 250-day window can stay closed for 600+ cycles. A forecast-based gate degrades gracefully: it produces a number every day.
- **Concrete mapping:** compute realized vol from the daily OHLC bars the harness already has (range-based proxies — Garman–Klass or Parkinson estimators need only OHLC, which Finnhub daily bars provide), then a HAR forecast of tomorrow's vol from the daily/weekly/monthly components. Replace `allow_trading()` with a continuous sizing/eligibility function: full size when forecast vol percentile is high, *scaled* size when low — or, if the gate must stay boolean for the validated rule, use it on the *forecast* percentile rather than the raw z-score, which is smoother and causal. Note: the repo's own research note `docs/research/factor-regime-persistence.md` already establishes the literature position that the *vol/risk state* is the stable-direction conditioning variable (Henkel–Martin–Nardari 2011; Bollerslev–Tauchen–Zhou 2009; Martin 2017) — the fix is the *instrument* (forecast, continuous) not the *direction* (high-vol good), which the literature supports.
- **Why it fits Jane Street's practice:** in the A–S framework the spread/size is a continuous function of σ. There is no Jane Street analogue to a binary market-open gate; volatility scales risk, it does not switch markets off [inference from §2.3's framework, labeled].

### T2. Add volume-weighted ("trading time") features to the signal, not just calendar-time features

- **Source:** Avellaneda & Lee (2010), "Statistical Arbitrage in the US Equities Market," *Quantitative Finance* 10(7), 761–782, doi:10.1080/14697680903124632 [Crossref record; full working-paper text verified at NYU mirror]. Abstract: "We introduce a method to take into account daily trading volume information in the signals (using 'trading time' as opposed to calendar time), and observe significant improvements in performance in the case of ETF-based signals. ETF strategies which use volume information achieve a Sharpe ratio of 1.51 from 2003 to 2007." Text (verified): signals estimated in trading time are "effectively equivalent to multiplying daily returns by a factor which is inversely proportional to the trading volume."
- **Concrete mapping:** the rule floor's momentum/RSI windows are calendar-time. A cheap, causal variant: weight recent days by volume (or by dollar volume) when computing the momentum score, so a thin, drifting day counts less than a heavy-volume day. This is one feature transformation on data the harness already fetches — no new data source.
- **Second-order version [inference, labeled]:** relative volume (today's volume vs its 20-day median) as a cross-sectional tradability/conviction feature — high relative volume on the signal day is the retail analogue of "confirmed flow."

### T3. Execution: split the fill over the session instead of one bar-close fill

- **Source:** Almgren & Chriss (2001), "Optimal execution of portfolio transactions," *Journal of Risk* 3(2), doi:10.21314/jor.2001.041 [Crossref record]. The framework: every trade pays a **temporary** cost (spread + short-horizon impact) and moves price via **permanent** impact; the optimal execution schedule minimizes expected impact cost subject to a constraint on the variance of the implementation shortfall (price risk). The canonical result: splitting a large order into a schedule of child orders trades impact against risk, with more risk-averse traders executing faster. **[The framework's formulation is the paper's title object; the specific schedule formulas are standard textbook content — not quoted here.]**
- **Current behavior (verified in code):** `exchange/paper.py` `place_order()` fills the whole order instantly at the last known close with a static slippage percent, and a random partial-fill ratio. There is no timing dimension: the harness cannot experience intraday price risk because it has modeled none.
- **Concrete mapping:** even before any smart algorithm, the execution layer should represent a session: split a signal's order into 2–4 child orders at defined session points (e.g., open + midday + late afternoon), with fills at the corresponding bar prices. This is implementable on daily data only if the data source gains intraday granularity (Finnhub minute candles), or on daily bars by using O/H/L/C of the entry bar as a rough intraday proxy. The deeper point from AC: the *schedule* is a control variable — the harness currently treats entry price as exogenous, which makes its 12.28% stop / 17.81% target numbers hostage to wherever the single fill lands.
- **Honest scope note:** at this repo's capital scale (15% of a ≤$10k account ≈ $1.5k per position), market impact is negligible; the cost that matters is the **spread**, i.e., the static-slippage assumption itself. The AC lesson that transfers even at small size is: *know your cost function and schedule against it* — and the first step is measuring it, which the current paper exchange already does via `_slippage_pct` but never validates against realized outcomes.

### T4. Spread/queueing awareness as a symbol-selection filter (Amihud-type screens)

- **Source:** Amihud (2002), "Illiquidity and Stock Returns: Cross-Section and Time-Series Effects," *Journal of Financial Markets* 5(1), 31–56 (Crossref record for the SSRN version, doi:10.2139/ssrn.3139180) — the standard illiquidity measure |return|/dollar-volume. The A&L paper [text, verified] is also directly relevant: their backtest assumes "a slippage/transaction cost of 0.05% or 5 basis points per trade (a round-trip transaction cost of 10 basis points)" across a universe of stocks with >$1B market cap — i.e., they chose a tradability floor so the cost assumption was plausible, and it still mattered enough to cut the PCA strategy's Sharpe from its pre-2003 level.
- **Concrete mapping:** the validated 16-name rule's screen is absolute, not rank-based (CONTEXT.md), so it can hold names too illiquid for its own cost model. A causal, daily-bar-computable tradability check (dollar-volume floor, e.g., Amihud ratio below a percentile, or minimum ADV) as a *fill-quality filter* on top of the score screen would make the static-slippage assumption honest per symbol. This is the retail-scale version of "we don't quote where we can't manage the adverse selection."

### T5. Inventory-style position management: correlation-aware exposure, not just per-position stops

- **Source:** the quote-skewing machinery of §2.3 (A–S 2008; GLFT 2013; Guéant 2016 [abstracts, verified]) and Jane Street's self-description: "We carefully study how trading risks might be bigger or more interrelated than they appear, and this allows us to be especially bold" ([page] who-we-are) and "by holding and managing risk over longer time periods we can execute complicated trades with less market impact" ([page] client-offering).
- **Concrete mapping:** the risk contract (6 concurrent positions, 15% each, 95% exposure) counts *names*, not *correlated exposure*. A daily-bar-computable analogue of inventory skewing: (a) compute a rolling pairwise correlation (or beta to SPY) among the 16-name universe from the 35M-row offline dataset; (b) cap effective exposure per correlated cluster (e.g., "no more than 30% of the book in names with pairwise corr > 0.6"); (c) when the book is at its exposure cap, the *selector* should prefer the new candidate with the lowest correlation to existing holdings — which is exactly what a market maker's quote skewing does (favor fills that reduce risk concentration). Note this applies at portfolio level; the long-only rule cannot skew a two-sided quote, but it can refuse to add the 7th correlated name.

### T6. Cross-sectional residual mean reversion for the portfolio ranker (Tier 3)

- **Source:** Avellaneda & Lee (2010) [text, verified]: signals are generated on **residuals** of returns against risk factors — PCA eigenportfolios or sector ETFs — modeled as mean-reverting OU processes; "we choose as entry point for trading any residual that deviates by 1.25 standard deviations from equilibrium, and we exit trades if the residual is less than 0.5 standard deviations from equilibrium," with a **fixed 60-day trailing estimation window** chosen once "to avoid data-mining," and models rejected when the fitted mean-reversion time exceeds ~1.5 months (κ > 252/30). Results verified from the abstract: PCA-based strategies ~1.44 Sharpe 1997–2007 (0.9 in 2003–07); ETF-based ~1.1 (1.51 with volume-weighted signals in 2003–07); performance collapses in the August 2007 liquidity crisis, consistent with the Khandani–Lo (2007) "unwinding" mechanism (SSRN doi:10.2139/ssrn.1015987) — systematic strategies exiting simultaneously pushed prices further against the crowd.
- **Concrete mapping:** the repo already plans a Tier-3 offline cross-sectional ranker. The A&L template fits it directly: (a) regress each name's daily returns on SPY (or SPY + sector ETF) over a fixed ~60-day window; (b) fit an OU/AR(1) to the residual to get its mean-reversion half-life; (c) only trade residuals whose half-life is short relative to the holding horizon (their 1.5-month rule of thumb); (d) enter at ~1.25σ deviation, exit at ~0.5σ. **Honest caveats:** A&L is long-short and market-neutral; a long-only harness can use only the long leg, which halves the strategy and leaves the book with residual beta. And their own results degrade after 2002–2007 — this is not a free lunch, it is a documented, decaying edge with a well-understood crash mode (which the repo's tail library should already model).
- **Cross-reference:** Gatev, Goetzmann & Rouwenhorst (2006), "Pairs Trading: Performance of a Relative Value Arbitrage Rule," *Journal of Financial Economics* 79(4) (NBER WP 7032, doi:10.3386/w7032) — the simplest distance-based pairs rule also documented significant out-of-sample profits. Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers," *Journal of Finance* 48(1), doi:10.1111/j.1540-6261.1993.tb04702.x, and Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum," *Journal of Financial Economics* 104(2), 228–250 (SSRN doi:10.2139/ssrn.2089463) — the cross-sectional vs time-series momentum distinction that the "rule floor (time-series) + ranker (cross-sectional)" split of this repo already mirrors [Crossref records].

### T7. Research-process discipline (the cheapest transfer of all)

From the transcript [ep. 22, verified quotes]:
- "In research, most of the ideas are bad" (Minsky) — the repo's arena/shadow machinery already institutionalizes this.
- On low-data honesty: with "very low amounts of data... the trade-off that you have is because you are so data limited, you would prefer to not leave that many data points out of sample and just be very careful about the number of hypotheses that you test" (Cho) — a direct endorsement of the repo's walk-forward/regime-window approach over hold-out splits on 5 years of data.
- On regime change: "a financial crisis seems to occur roughly every year... there are lots of events after which the distribution of features or the returns that you might see in your data just kind of changes and dealing with those regime changes" (Cho) — validation for the epoch engine (ADR-0006) and the tail library.
- On data quality: survivorship bias is called out explicitly as "a pretty bad way to go about it" (Cho) — the 35M-row dataset's survivor handling is a first-class research feature, not a nicety.

---

## 4. What cannot be replicated (honest limits)

1. **Latency and physics.** "There are trading systems we build where we sweat the performance details down to a range of 10 nanos, more or less is like a material part of our overall time budget" (Cho, [transcript] ep. 22). Colocation, FPGAs, custom multicast feeds (ep. 3, "Multicast and the Markets," [transcript summary]: exchanges themselves are built on single-threaded matching engines + multicast) — none of it is available to a retail daily-bar harness, and none of it should be pursued there.
2. **Flow knowledge and counterparty identity.** The pension example ([transcript] ep. 22) shows the edge in knowing *who* is on the other side and whether their flow is informed. A retail trader's fills are anonymous retail flow routed by a broker; the informational asymmetry runs the other way.
3. **Maker-side economics.** Spread capture requires being a registered/active two-sided quoter: maker rebates, exchange membership, access to auctions, primary-market creation/redemption rights (ETF AP status), wholesale/retail order flow (their US wholesaling unit trades "directly with many of the biggest retail brokerage firms," client-offering page). A retail account pays the spread; it cannot collect it.
4. **Capital and inventory capacity.** "$400 billion daily filled dollars" and "$900B traded with clients in bonds in 2025" (ML page; client-offering page) are not just scale — the client page says explicitly that the ability to "hold and manage risk over longer time periods" is *how* they offer better execution. Holding inventory through dislocation is a capital function. At $10k, there is no inventory capacity, so there is no inventory alpha.
5. **Data.** "A few tens of terabytes of market data every day" (Cho, [transcript] ep. 22), 1+ exabytes stored, sub-second visualization tooling. The harness's daily OHLC is a 1e-12 fraction of the information set, with no order book, no auctions, no venue-level detail.
6. **Talent and iteration loops.** Hundreds of researchers with "short time to joy" tooling (ep. 22). One agent with a laptop iterates at ~1e-3 the rate; the arena is the correct compensation, but it does not close the gap.
7. **Their own result shows the edge decays and crashes.** A&L's Sharpe halves after 2002–2007 and breaks in August 2007 (Khandani–Lo unwinding); McLean & Pontiff (2016) (already in the repo's research corpus) put ~26% OOS decay on published predictors. Nothing in this playbook is a permanent-money machine; the honest prior is that each transplantable technique is worth a fraction of its source's headline number.

**What a small system CAN replicate (recap):** vol forecasting from its own OHLC data (T1), volume-weighted signal construction (T2), scheduling/execution structure with a modeled cost function (T3), tradability filters (T4), correlation-aware position management (T5), cross-sectional residual signals for the ranker (T6), and research-process discipline (T7) — none of which require speed, capital, or market-maker status, and all of which use data the harness already has or can cheaply fetch.

---

## 5. The top-5 list for this repo's current architecture

Ranked by (expected value to the rule-primary daily-bar system) × (fit to existing code) × (implementation cost):

1. **Continuous vol forecast (HAR/range-based) replacing the binary VIX z-gate** — directly unblocks the 0-fills-over-600-cycles failure while preserving the literature-supported "high-vol is the good regime" direction (see repo note factor-regime-persistence.md); uses only daily OHLC + a linear regression.
2. **Session-split execution with a measured cost function** — turns the one-shot close fill (paper.py) into a 2–4 child-order schedule, making entry-price risk an explicit, controllable variable per Almgren–Chriss; also forces the slippage assumption to be validated rather than static.
3. **Volume-weighted ("trading time") features in the score screen** — one transformation on existing data; the only feature change here with a direct, verified Sharpe-improving citation (A&L 2010: 1.1 → 1.51 in 2003–07 for ETF-based signals).
4. **Correlation-aware position sizing/exposure caps (inventory-style risk)** — maps the market maker's quote-skewing principle onto the risk contract without touching the validated entry rule: cap cluster exposure, prefer uncorrelated names when at the cap.
5. **Tradability/illiquidity filter (dollar-volume floor, Amihud-style)** — makes the cost assumptions per-symbol honest and is the retail analogue of "we don't quote where adverse selection is unmanageable."

---

## References

### Jane Street primary sources (all fetched and read 2026-08-12)

1. Jane Street, "Machine Learning at Jane Street" — https://www.janestreet.com/join-jane-street/machine-learning/ [page]: "research lab with a trading desk attached"; $400B daily filled dollars; tens of thousands of GPUs; 1+ exabytes storage; "Market data is 'regime-y'"; "our own actions influence the data we're trying to model."
2. Jane Street, "Client Offering" — https://www.janestreet.com/what-we-do/client-offering/ [page]: market maker/liquidity provider self-description; >10,000 ETFs primary+secondary; >25,000 bonds, $900B client trading 2025; ~3,800 option classes; wholesale market making >10,000 securities; JX/JX-EU/JCX platforms.
3. Jane Street, "Who We Are" — https://www.janestreet.com/who-we-are/ [page]: "provide liquidity during the market's most volatile moments"; "we carefully study how trading risks might be bigger or more interrelated than they appear, and this allows us to be especially bold"; risk/postmortem culture.
4. Jane Street, "Global Capital Markets" — https://www.janestreet.com/what-we-do/global-capital-markets/ [page]: internally funded capital base.
5. Signals & Threads, ep. 22, "Finding Signal in the Noise: Machine Learning and the Markets" (In Young Cho), 2025-03-10 — https://signalsandthreads.com/finding-signal-in-the-noise/ [transcript, full text read]: all ep-22 quotes; research process (exploration → data collection → modeling → productionization); 100-units-of-data/99-garbage; regime changes; 10ns-to-human horizons; pension-service adverse-selection example; survivorship bias; "most of the ideas are bad."
6. Signals & Threads, ep. 23, "Building Tools for Traders" (Ian Henry), 2025-05-28 — https://signalsandthreads.com/building-tools-for-traders/ [summary + excerpt]: trader-configurable tools on the options desk.
7. Signals & Threads, ep. 3, "Multicast and the Markets" (Brian Nigito), 2020-09-23 — https://signalsandthreads.com/multicast-and-the-markets/ [summary]: exchange architecture (single-threaded matching, multicast feeds).
8. Jane Street Tech Talks — https://www.janestreet.com/tech-talks/ [index]: e.g., "Production Engineering When Trading Billions of Dollars a Day" (Mark Doss).

### Academic sources (verified via Crossref, arXiv, or full text, 2026-08-12)

9. Glosten, L. & Milgrom, P. (1985). Bid, ask and transaction prices in a specialist market with heterogeneously informed traders. *Journal of Financial Economics* 14(1), 71–100. doi:10.1016/0304-405X(85)90044-3
10. Kyle, A. (1985). Continuous Auctions and Insider Trading. *Econometrica* 53(6), 1315–1335. doi:10.2307/1913210
11. Avellaneda, M. & Stoikov, S. (2008). High-frequency trading in a limit order book. *Quantitative Finance* 8(3), 217–224. doi:10.1080/14697680701381228
12. Avellaneda, M. & Lee, J.-H. (2010). Statistical arbitrage in the US equities market. *Quantitative Finance* 10(7), 761–782. doi:10.1080/14697680903124632 — full working-paper text verified: http://www.math.nyu.edu/faculty/avellane/AvellanedaLeeStatArb071108.pdf
13. Guéant, O., Lehalle, C.-A. & Fernandez-Tapia, J. (2013). Dealing with the Inventory Risk: A solution to the market making problem. *Mathematics and Financial Economics* 7(4), 477–495. doi:10.1007/s11579-012-0087-0 (arXiv:1105.3115)
14. Guéant, O. (2016). Optimal market making. arXiv:1605.01862 (survey abstract verified).
15. Fodra, P. & Labadie, M. (2012). High-frequency market-making with inventory constraints and directional bets. arXiv:1206.4810
16. Almgren, R. & Chriss, N. (2001). Optimal execution of portfolio transactions. *Journal of Risk* 3(2). doi:10.21314/jor.2001.041
17. Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. *Journal of Financial Econometrics* 7(2), 174–196. doi:10.1093/jjfinec/nbp001 (working version doi:10.2139/ssrn.626064)
18. Cont, R., Kukanov, A. & Stoikov, S. (2014). The Price Impact of Order Book Events: Market Orders, Limit Orders and Cancellations. *Journal of Financial Econometrics* 12(1), 47–88 (working version doi:10.2139/ssrn.1373762).
19. Gatev, E., Goetzmann, W. & Rouwenhorst, K. G. (2006). Pairs Trading: Performance of a Relative Value Arbitrage Rule. *Journal of Financial Economics* 79(4) (NBER WP 7032, doi:10.3386/w7032).
20. Jegadeesh, N. & Titman, S. (1993). Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency. *Journal of Finance* 48(1). doi:10.1111/j.1540-6261.1993.tb04702.x
21. Moskowitz, T., Ooi, Y. H. & Pedersen, L. H. (2012). Time Series Momentum. *Journal of Financial Economics* 104(2), 228–250 (SSRN doi:10.2139/ssrn.2089463).
22. Khandani, A. & Lo, A. (2007). What Happened to the Quants in August 2007? (SSRN doi:10.2139/ssrn.1015987) — cited via Avellaneda–Lee §7.
23. Amihud, Y. (2002). Illiquidity and Stock Returns: Cross-Section and Time-Series Effects. *Journal of Financial Markets* 5(1), 31–56 (SSRN doi:10.2139/ssrn.3139180).

### Repo sources (read for mapping, not research sources)

24. `data/vix_gate.py` (trailing-250 VIXCLS z-score, threshold 0.5, boolean allow) and `harness.py` (gate consumption, lines ~2435–2503).
25. `exchange/paper.py` (instant one-shot fills at last close, static slippage, random partial fill).
26. `docs/research/factor-regime-persistence.md` (in-repo literature review: vol-regime gate is the stable-direction component; PT-2002-style break-aware sign estimation).
27. `docs/CONTEXT.md` (rule floor, regime, risk contract, three-tier structure, epoch engine).
