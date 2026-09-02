# Universe bridge — live universe vs experts' universes vs FTMO instruments

Code-verified 2026-08-23 against `mot/industry_map.py`, `mot/tradable_universe.py`,
`harness.py`, `strategies/experts.py`, plus the tournament evidence in `docs/CONTEXT.md`.

## 1. The live harness universe (what it actually is today)

- `harness.py` `universe_mode=True` (default) → `mot/industry_map.py::get_universe_tickers()`
  = the **511-ticker industry registry** (40 sub-industries, GICS 11 sectors).
  The scout LLM-curates **511 → 20 → 6** focus symbols per cycle.
- Fallback (no registry): `TRADABLE_UNIVERSE` = ~66 names (20 crypto + 20 US
  equities + 7 FX majors + commodities/ETFs + ag/mining/energy/specialty).
- Actual trade staging (`STAGES`): BTC only → {BTC,ETH,SOL} → {BTC,ETH,SOL,
  AAPL,NVDA,SONY}, gated on hours + return.
- Exchange: `config/harness_config.json` → Finnhub (stocks) + crypto via
  MultiExchangeRouter; "real prices, paper settlement".

## 2. Reconcile the "19-symbol universe" claim — STALE boilerplate

`docs/CONTEXT.md`, `AGENTS.md`, and `strategies/experts.py` all repeat "NOT
validated on the harness's real-time **19-symbol** universe". **Nothing in the
current code produces 19 symbols.** The live radar is 511 (focus 6); the fallback
universe is ~66. The honest-boundary substance is correct (experts not validated
on the live universe), but the **number "19" is stale** and should be updated to
"511-registry radar / 6-symbol focus" wherever it appears.

## 3. The 9 verified experts and their native universes

From `strategies/experts.py` (VerifiedExpert registry) + CONTEXT.md:

| Expert | OOS Calmar | maxDD | Native universe | FTMO-tradeable? |
|---|---|---|---|---|
| `laggard` | 1.666 | −7.5% | intl 10-asset (indices/FX/gold/oil) | **YES** |
| `multiasset` | 1.289 | −9.0% | 13-asset basket (FX/indices/commodities) | **YES** |
| `bayes` | 1.148 | −10.4% | intl (indices/FX/gold/oil) | **YES** |
| `spectral` | 1.000 | −13.3% | intl (FFT gate × breadth) | **YES** |
| `kalman` | 0.988 | −12.7% | intl | **YES** |
| `hurst` | 0.967 | −11.3% | intl | **YES** |
| `wavelet` | 0.803 | −11.7% | intl | **YES** |
| `entropy` | 0.667 | −13.8% | intl | **YES** |
| `momtrend` | 0.938 | −13.0% | US 300-name single stocks | **NO** (no US CFDs) |
| contrarian worst-5 | (3/4 folds, 9.1% ann) | — | US 57 large-caps | **NO** (no US CFDs) |

FTMO instruments = FX/metals/indices/commodities/crypto CFDs (no US single-stock
CFDs — see the FTMO facts ticket). So the **FTMO-eligible field is exactly the
international/FX/commodity expert set** — which is the same set that transferred
OOS. The US-equity experts (momtrend, contrarian worst-5, spectral-US, copula-US)
are excluded by instrument, not just drawdown.

## 4. The bridge gap (what the map must close)

- Live radar = **511 US-equity names + crypto**; FTMO = **FX/indices/commodities/
  crypto CFDs**. Overlap is only: the crypto leg (BTC/ETH/SOL as crypto CFDs) and
  a handful of index/commodity ETFs (SPY/QQQ/GLD/SLV/USO/UNG as CFDs).
- The FTMO-eligible experts (`laggard`, `multiasset`, intl abstract winners)
  operate on **indices/FX/metals/commodities** — a universe the harness does **not**
  currently trade (its equity radar is US stocks; its FX list is 7 majors in the
  static fallback only).
- **Conclusion:** the map's "regime-switch routing on the FTMO universe" requires
  standing up an **FTMO-facing universe (FX/indices/commodities/crypto CFDs)** and
  re-pointing the eligible experts at it — the live equity radar cannot be reused
  for the prop leg.

## Open items for the map

1. Confirm crypto-CFD + index/commodity-CFD availability on the US path (see FTMO ticket).
2. Decide whether the prop leg trades a new FTMO universe (OANDA) separate from the
   equity radar, or re-uses the harness's crypto leg only.
3. Update the stale "19-symbol" figure in CONTEXT.md / AGENTS.md / experts.py.
