# FX alt-data inventory — 7 majors, 2008+ (2026-09-05)

Research subagent output (agent_a41088b6, ~22 calls, primary sources verified where marked V). Filed per ticket #206 (map #198) — the exogenous feature-space expansion.

## Ranked inventory (V = verified this session, U = unverified)

| Source | Span | Access | Freq | Causal chain | Priced-in risk |
|---|---|---|---|---|---|
| 1. IMF PCPS via FRED — one free file/API: iron ore 62% Fe CFR Tianjin, EU TTF gas, WTI/Brent, US nat gas, copper, coal. FRED CSVs start 1992-01 (flat period-avg pre-~2008; use 2008+ spot era) | 18y+ | fred.stlouisfed.org/series/PIORECRUSDM, PNGASEUUSDM (V: start dates pulled); API free, citation required | Monthly | Iron ore/coal→China steel→AUD ToT; crude/gas→CAD; TTF→EUR/CHF energy shock | **Moderate-high** — iron ore is watched daily by AUD traders; value = regime state, not timing |
| 2. IMF CTOT — commodity terms-of-trade index per economy, 182 economies, 1962+, ≤45 commodities (V: exists, described on imf.org/commodity-prices; per-country pulls U) | 60y+ | data.imf.org, free | Infreq-updated | Purpose-built ToT for AUD, CAD, NZD — the exact construct | Lower — academic, less flow-watched |
| 3. NOAA ONI/ENSO (V: 1950–present, free, moved to ERSSTv6 table) + PDO (NCEI page live, span 1900+ U) | 50–120y | cpc.ncep.noaa.gov ONI_v5; ncei.noaa.gov/access/monitoring/pdo | Monthly | ENSO→AUS drought/wheat→AUD; weaker: Canadian prairies→CAD | **Low** — slow weather state, no FX flow watches it |
| 4. GDT dairy auctions (V: since 2008, twice-monthly, results public; bulk/API = paid GDT Insight) | 18y | globaldairytrade.info | 2×/mo | Dairy→NZD→AUD/NZD cross→indirect AUD_USD | High for NZD books; irregular timing dents mechanical pricing |
| 5. EIA (V: spot tables 1986+; crack spreads derivable ULSD−WTI, not published; API needs free key — standard, U here) | 40y | eia.gov, free | Weekly/daily | Distillate cracks = US refining demand→CAD crude complex | High — WPSR is market-moving |
| 6. Baker-Bloom-Davis EPU (V: free, CC-BY, monthly US/Global/China/Japan/UK; start dates U — US 1985 per papers) | ~40y | policyuncertainty.com | Monthly | Policy uncertainty→USD haven, JPY/CHF demand, AUD/CAD risk-off | Moderate-high — heavily used in academia |
| 7. USGS Mineral Commodity Summaries (V: annual, free, 1996–2026, DOI'd data release; coal excluded as fuel) | 30y | usgs.gov | Annual | Supply-side context for iron ore/copper→AUD | Low but **too slow for signals** — context only |
| 8. World Bank WDI (verified-by-possession: already allowlisted) | 1960+ | api.worldbank.org | Annual | EM distress/China indicators→USD regimes | Low, annual-only regime filter |
| 9. Target2 balances (U — ECB BSI dataset wrong, BLY 404'd, Bundesbank pages 404'd today; expect free via ECB/Bundesbank/Italy) | 2008+ ideal | TBD | Monthly | Eurozone fragmentation tail→EUR/CHF | Lower — episodic tail-risk, less flow-priced |
| 10. Alberta WCS–WTI differential + AECO (U — dashboard moved/JS-gated; known free monthly) | ~2010+ | economicdashboard.alberta.ca | Monthly | Heavy-oil discount = real CAD ToT wedge vs WTI | Moderate |
| 11. Baltic Dry Index (U — bot/pay-walled at source; **no free full history found**) | n/a | balticexchange.com | Daily | Global trade volume→AUD/CAD | n/a — access fails |
| 12. worldsteel monthly crude steel (U — free tier unclear; subscriptions sold), NBS China monthly (U), DCE iron ore futures 2013+ (U), BoJ accounts + Japan trade balance (U — URLs 404'd today, known free) | — | — | — | — | — |

## Integrate first (walkforward regime-conditioning layer)

1. **FRED/IMF PCPS commodity panel** — one pull covers AUD (iron ore/coal), CAD (crude/gas), EUR/CHF (TTF); monthly panel joins our carry/2y yield panel trivially; 2008+ spot era gives a clean 18y test window; CTOT as the ready-made ToT index if per-country series pull cleanly.
2. **ONI + PDO** — zero overlap with anything we hold, longest history of any candidate, slow-moving (3-mo averages) → cheap honest OOS folds; the only path to expressing the weather→ag-export→AUD chain.
3. **EPU (now) / Target2 (pending verification)** — policy-uncertainty and fragmentation conditioning for the haven flows (USD/JPY/CHF) that our rate-differential features don't capture. EPU wins the slot today purely because access is confirmed.

## Honest verdict

Partial yes, concentrated in two places. (a) **AUD/CAD terms of trade**: iron ore/TTF/crude differentials are genuinely causal and we hold no commodity-price state — but they are adjacent to OHLCV and substantially priced in, so expect them to earn their keep as regime conditions, not entry signals. (b) **Slow weather regimes (ENSO/PDO)**: least-watched, longest-history input, but the causal chain to a specific pair is the longest and most lagged — treat as a prior, not a signal. For **USD_JPY** nothing here beats what we already hold (MOF interventions, BoJ, trade surprises); BoJ/trade records were only blocked by URL 404s, not access policy. For **GBP** no candidate surfaced at all. Dairy maps to NZD (not traded); BDI/USGS/WDI fail on access or cadence; most remaining volume (GDT, WCS, steel) serves markets we don't trade. Net: alt-data adds a real, testable conditioning layer for AUD/CAD and modest tail-risk inputs for EUR/CHF/JPY — it does not add a causal alpha source for the majors' core rate/risk drivers.

**Flagged UNVERIFIED**: Target2 access, Alberta WCS/AECO URLs, BDI free history, worldsteel free tier, EPU/PDO start dates, BoJ/MOF URLs (404 today), DCE futures access, GDT bulk history depth. Verified facts trace to: fred.stlouisfed.org (PIORECRUSDM, PNGASEUUSDM CSV starts 1992-01), imf.org/commodity-prices, cpc.ncep.noaa.gov, ncei.noaa.gov, globaldairytrade.info, policyuncertainty.com, eia.gov, usgs.gov, worldbank.org. If persisted, this belongs at `docs/agents/research/fx-alt-data-inventory-2026-09-05.md` — not written per subagent constraints.
