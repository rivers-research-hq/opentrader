# Baltic Dry Index (freight) — source profile

## Consume me
- **Purpose**: daily dry-bulk shipping freight index (BDI + capesize/panamax/supramax sub-indices) as an exogenous daily series for the OpenTrader exogenous-data falsifier (ticket #91) — attach to fullcross dates 1996-2026, test against the deep-tail DSR bar.
- **Auth**: varies by source — Baltic Exchange API is **member/subscription-gated**; S&P Global blocks bots (403). No free API found in probe.
- **Sample call/load**: `unknown` — no working free endpoint established. See Unknowns.

## Kind: Dataset (the actual target — a daily time series)
- **Format**: expected daily values (index points), date → value
- **Location**: not found as a free machine-readable source in this probe
- **Size**: ~1996-2026 daily ≈ 7,500 points for BDI
- **Schema / columns**: date, BDI (and ideally capesize BPI BSI sub-indices)
- **Licensing**: Baltic Exchange data is proprietary/paid; free mirrors are unofficial

## Kind: API (Baltic Exchange — probed, gated)
- **Base URL**: `https://www.balticexchange.com/en/data-services/support/api.html` (API documented; access requires member subscription)
- **Auth**: subscription/API key — how the user would authenticate is unknown; do NOT ask for credentials in this profile
- **Endpoints**: documented on the API page (real-time + historical freight data); rate-limited (HTTP 429 + Retry-After documented)
- **Pagination**: unknown
- **Rate limits**: documented as per-endpoint; 429 + Retry-After on exceed
- **Errors**: unknown beyond 429
- **Goal depth**: research → a daily BDI series aligned to the fullcross date range; a client is NOT needed yet

## Probe log (what was actually tried)
- Baltic Exchange site: reachable (301), API page exists, member-gated
- S&P Global (spglobal.com): 403 bot-block
- FRED: `BDI`, `BALTIC`, `BCOAL`, `COAL`, `RCOAL` series IDs all 400 (not present); FRED search endpoint flaky but VIXCLS/etc. confirmed working — so FRED simply does not carry freight
- Yahoo Finance `^BDI`: not found
- Hugging Face: `Michele1996/BALTIC` exists but contains only tutorial images; HF search for shipping/freight/coal returns nothing useful
- EIA API: `coal` category exists (200) but sub-paths (`inventories`, `consumption`) returned 502 during probe (API flaky at probe time; separate coal profile possible later)

## Unknowns
- **A working free BDI source**: none found. Candidates to try (all unverified): (1) Baltic Exchange historical data via member account the user may hold; (2) free BDI archives on investing.com / tradingeconomics (scrape — fragile, TOS risk); (3) paid data vendors (Bloomberg/Refinitiv) if the user has access; (4) Kaggle BDI datasets (unverified existence); (5) EIA coal inventories as a *substitute* "energy flows" series (partially probed, 502 at probe time).
- **Historical depth**: whether any found source covers 1996+ (BDI history) vs only recent years.
- **Sub-indices**: availability of capesize/panamax splits, not just headline BDI.
- **License**: for any non-official mirror found later.

## Decision needed downstream
Per the falsifier bar: the freight series must backfill to daily bars over the fullcross date range and clear the date-clustered deep-tail DSR (≥95th pctile) — the same bar VIX already passed. If no free source exists, the honest fallback is: (a) use EIA coal flows as the "physical economy" proxy, or (b) record freight as inaccessible and test coal as the only available "story" signal.
