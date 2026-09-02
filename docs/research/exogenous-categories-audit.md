# Exogenous Data Categories Audit — Free & Backfillable for Daily Equity Signals

Date: 2026-08-09 · Read-only audit. All findings below are based on **live probes** of local
parquet caches and the sources themselves (HTTP checks, EDGAR API calls). No code changes made.

---

## TL;DR ranked verdict

| # | Signal | Daily-usable? | Frequency | Lag | Free | Backfill depth | Verdict |
|---|--------|:---:|-----------|-----|------|----------------|---------|
| 1 | **Net stock issuance (shares outstanding delta)** | ✅ YES | Quarterly→monthly (as-reported) | 0–90d (report-date caveat) | ✅ free, **already local** | **1984+** (8.5k symbols) | **BUILD — anchor signal** |
| 2 | **Statement-based buybacks / net equity issuance** (`net_common_stock_issuance`, `repurchase_of_capital_stock`) | ✅ YES (slow) | Quarterly | ~45d | ✅ free, **already local** | 2019-05+ (11k symbols) | **BUILD — complements #1 for 2019+** |
| 3 | **Corporate insider trades (Form 4)** | ✅ YES | Daily (acceptance timestamps) | ~1–3 days | ✅ free, **already local** | 1993+ (3.58M filings) | **BUILD — only daily-fresh data here** |
| 4 | **Aggregate institutional ownership change (from 13F)** | ⚠️ PARTIAL | Quarterly | 45 days | ✅ free (EDGAR) | 1993+ meta / 2001+ full-text | **BUILD as slow quarterly regime feature** |
| 5 | **Fund flows — N-PORT (per-fund, per-quarter, flows + holdings)** | ⚠️ PARTIAL | Quarterly | ~60–90d | ✅ free (EDGAR) | 2018+ | **BUILD (aggregate), low priority** |
| 6 | **Fund flows — ETF/mutual price+volume proxy** | ✅ YES (proxy) | Daily | 0 | ✅ free, **already local** | 1999+ (SPY/QQQ/IWM/DIA/GLD/TLT local) | **BUILD — but it is a proxy, not true flows** |
| 7 | **Fund flows — ICI monthly aggregates** | ❌ NO | Monthly | ~1 mo | free content but bot-gated (403) | long | **DO NOT BUILD — monthly, gated, low edge** |
| 8 | **ETF flows — etf.com / etfdb.com / fintel** | ❌ NO | Daily | 1d | **gated/paywalled** (403) | — | **DEAD-ON-ARRIVAL for free** |
| 9 | **Pension funds (CalPERS/CalSTRS)** | ❌ NO | Annual/holdings, quarterly stats | months | PDFs, partially free | shallow | **DEAD-ON-ARRIVAL for daily signals** |

---

## 1. EQUITY ISSUERS / ISSUANCE SIGNALS — already local, verified

All four files probed with pandas/pyarrow (actual schemas, counts, ranges):

### 1a. `stock_shares_outstanding.parquet` — the issuance-anomaly anchor
- **Schema (3 cols):** `symbol (str)`, `report_date (str, YYYY-MM-DD)`, `shares_outstanding (int64)`
- **Counts:** 1,152,774 rows · **8,569 symbols** · dates **1984-01-31 → 2026-06-01**
- **Cadence:** quarterly 1984–~2000 (exactly quarter-end dates), then quarter-end + month-end
  (4–5 dates/quarter recently, AAPL verified month-by-month; median 107 rows/symbol, max 2,581)
- **Coverage:** grows from ~2.2k rows/yr (1984) to ~92k rows/yr (2025). ~35k rows/symbol-year at peak.
- **Issuance proxy:** 12-month % change in shares outstanding → the classic Fama-French net-issuance
  anomaly (low issuers outperform). Also `Δ(SO)/SO` as stock-supply regime feature.
- **⚠️ Caveat (important):** `report_date` is the **period-end (as-reported) date, not the filing
  date** — AAPL rows are exact quarter ends (03-31, 06-30, 09-30, 12-31) plus month-ends. Info became
  public only at filing (10-Q/10-K: 40–60d later). For a fair backtest, either lag 45–90d, or join to
  `stock_sec_filing.parquet` (same symbol/CIK, form_type 10-K/10-Q/8-K) to recover actual
  `filing_date`/`acceptance_date_time`.
- **Split risk:** values are as-reported; a split/reverse-split appears as a jump — needs
  split adjustment via price-file factor, or a delta-clip heuristic.

### 1b. `stock_dividend_events.parquet`
- **Schema:** `symbol`, `report_date`, `amount (decimal(20,4))`
- **Counts:** 300,114 rows · 4,893 symbols · **1991-02 → 2026-06** (thin before 1994: 4 rows/yr)
- **Use:** dividend-yield / div-cut signals — secondary for the issuance story.

### 1c. `stock_sec_filing.parquet` — bonus: insider trades are daily-fresh
- **Schema (10 cols):** `symbol, cik, accession_number, company_name, form_type,
  form_type_description, filing_date, report_date, acceptance_date_time, filing_url`
- **Counts:** 7,557,772 rows · 10,126 symbols / 7,522 CIKs · **1993-08-13 → 2026-06-11**
- **Form mix (top):** Form 4 (insider trades) **3.58M**, 8-K 1.18M, 6-K 648k, SC 13G/A 419k,
  10-Q 317k, Form 3 254k, SC 13G 191k, 10-K 103k, SC 13D/A 78k, **13F-HR 28,715**, 20-F 16.7k…
- **Signal:** Form 4 with `acceptance_date_time` gives a **daily** insider-buy signal (1–3d lag to
  public). 10-K/10-Q/8-K give exact filing dates to re-date the issuance signal in 1a.
- **13F caveat:** only **237 institutions** (big banks/insurers: Brookfield, BofA, Morgan Stanley,
  BMO, JPM, UBS, WFC, GS…) — NOT a usable hedge-fund universe; that must come from EDGAR (sec. 2).

### 1d. `stock_statement.parquet` — buybacks/issuance line items
- **Schema (6 cols):** `symbol, report_date, item_name, item_value (decimal(38,2)), finance_type,
  period_type`
- **Counts:** 28,733,050 rows · 11,146 symbols · **dates 2019-05-31 → 2026-05-31** (1,027,222 rows
  have junk `report_date = "TTM"` — filter `^\d{4}`). Deep coverage starts 2022 (~4.5M rows/yr).
- **finance_type:** balance_sheet 11.39M, cash_flow 8.97M, income_statement 8.37M
  **period_type:** quarterly 18.80M, annual 9.93M
- **Direct issuance/buyback items found (regex-scan of item_name, 1.46M matches):**
  - `net_common_stock_issuance` — **146,947 rows / 10,024 symbols** (neg = net buyback)
  - `repurchase_of_capital_stock` — 100,472 rows / 6,673 symbols (neg values = $ spent)
  - `treasury_shares_number` — 96,121 rows / 6,183 symbols (share count, sign ambiguous — check)
  - `common_stock_issuance` — 101,667 rows / 8,140 symbols
- **Verdict:** cash-flow-statement buyback $ is the cleanest buyback signal, but **only 2019+** —
  use shares_outstanding (1a) for the long history, statements for the 2019+ refinement.

---

## 2. HEDGE FUNDS — 13F (SEC EDGAR) — free, quarterly+45d lag only

### Live probe results (2026-08-09, one request each, User-Agent set):
- **Full-text search:** `GET https://efts.sec.gov/LATEST/search-index?q="13F-HR"&forms=13F-HR`
  → **HTTP 200, JSON**, hits incl. `form`, `file_date`, `period_ending`, `adsh`, `display_names`.
  Cap ~10k hits per query (use date-range pagination: `dateRange=custom&startdt=&enddt=`).
- **Filings index:** `GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&output=atom`
  → **HTTP 200, Atom feed** (also `action=getcompany&type=...` per-CIK, and
  `https://www.sec.gov/Archives/edgar/full-index/<year>/QTR<n>/master.idx` bulk **since 1993**, verified
  `1993/QTR1/master.idx` exists).
- **Rate limits:** no key needed, but SEC demands a descriptive User-Agent (contact info) and
  ~10 req/s max — backfill must be throttled/serialized.

### Reality check:
- **Frequency:** quarterly (13F-HR due within 45 days of quarter end). No daily cadence, ever.
- **Lag:** ≥45d after quarter end, plus ~1-2d SEC processing → the freshest possible signal is
  ~45–60d stale at its announcement moment.
- **Universe:** only managers with ≥$100M in 13F securities; short positions and most derivatives
  NOT reported; holdings in aggregate dollars + shares at quarter end only.
- **Backfill depth:** EDGAR metadata (full-index) **1993+**; full-text search officially **2001+**
  (a 1994 hit exists as edge case; don't rely on it); machine-readable XML information tables
  reliable ~**1999–2000+**; pre-1998 only scanned images (not backfillable programmatically).

### Derived signals that ARE buildable (free):
1. **Aggregate institutional ownership change per stock** — sum all 13F manager holdings at each
   quarter end (weight by manager), take Δ shares held → "institutional flow" proxy. This is the
   only scalable 13F-derived series, but it is **ownership-change, not true flow** (price moves
   inside quarter confound), quarterly, and 45d stale.
2. Hedge-fund-only subset requires manager classification (13F filers include banks, pensions,
   insurers — hedge funds are a subset; classifier itself must be built, e.g. from fund names).
3. **Free derived datasets exist** (e.g. "SEC 13F" HuggingFace/GitHub parquet dumps) but quality is
   variable; raw EDGAR XML is the trustworthy path (full-index → filing → information table XML).

### Verdict
**Usable only as a slow quarterly regime/flow feature** (45d lag, ~1999+/2001+ depth). It will not
produce daily turnover; keep it as a 3-12 month rebalance overlay. Never a day-0 event signal.

---

## 3. PENSION FUNDS — CalPERS / CalSTRS — dead on arrival for daily use

### Reality check (verified live):
- CalPERS: publishes **total fund AUM monthly** in press releases (site reachable, 200) and a
  **full public holdings list ~annually/semi-annually** (PDF/CSV under "public holdings" — page
  returns 404 on the guessed URL; it is a maintained, human-navigated publication, not an API).
- CalSTRS: quarterly stats + annual investment report (site reachable, 200).
- **No API, no structured feeds.** Data is PDF/press-release extraction; holdings lag 3–12 months;
  pension allocation changes are slow, small in signal, and swamped by market moves.

### Verdict
**Not worth building.** Frequency (annual-ish holdings) and lag (months) exclude it from any daily
or even monthly equity signal. If a "smart money" long-horizon feature is wanted, 13F aggregate
ownership already covers the same institution class at quarterly frequency with 45d lag.

---

## 4. FUND FLOWS — true daily flows are gated; free proxies exist

### Live probe results:
- **etf.com "ETF flows"** → **403** (bot-block/SS&C paywall). **DEAD for free.**
- **etfdb.com /etf-flows/** → 404 (page moved); site's flow data effectively gated. **DEAD.**
- **fintel.io** → 403 (gated). **DEAD.**
- **ICI (`ici.org/research/stats/flows`)** → **403** (bot-gate; the underlying monthly aggregate
  flow press releases are publicly free content, but scraping is blocked; ~4-week lag, monthly).
- **N-PORT on EDGAR** → **verified live & free** (browse-edgar `type=NPORT-P` returns current
  filings). Per-fund quarterly reports since **2018** with **actual flow $ in/out** + holdings.
  (Full-text search returns 0 for `forms=NPORT-P` — use browse-edgar/full-index instead.)
  Lag: N-PORT due within 60–90 days after quarter end.

### Best free proxies (ranked):
1. **Local price+volume of ETFs** (already in `stock_prices.parquet`: 35.4M rows, 11,719 symbols,
   1999-11-18 → 2026-03-26, incl. SPY, QQQ, IWM, DIA, GLD, TLT) → ETF "flow proxy" via
   volume-share, turnover, and AUM≈price×shares drift. Daily, zero lag, but **proxy ≠ flow** —
   it cannot separate organic investor flow from market beta.
2. **EDGAR N-PORT (2018+)** → true per-fund flow $, quarterly, 60–90d lag; aggregate by
   asset-class/expense-ratio bucket for a genuine "money in/out of equities" regime feature.
3. **ICI monthly aggregates** → true aggregate flows, monthly, ~4-week lag, but bot-gated (403);
   obtainable via press-release fetch with proper UA, low priority.

### Verdict
True **daily** fund-flow data has **no free source** (etf.com/fintel/etfdb all gated). Build the
daily price/volume proxy now; add N-PORT quarterly aggregates as a slow regime feature if the
edge justifies it. Skip ICI (monthly, gated, low incremental value).

---

## 5. WHAT TO BUILD vs DEAD-ON-ARRIVAL

### Build (in priority order)
1. **Net-issuance factor from `stock_shares_outstanding`** — 12-mo ΔSO%, 1984+, 8.5k symbols.
   Re-date via sec_filing or use ≥45d lag; clip split jumps. Anchor exogenous factor.
2. **Insider-trade signal from Form 4** (sec_filing) — daily acceptance timestamps, 1993+.
   The only genuinely daily-fresh exogenous series in the local cache.
3. **Buyback signal from `stock_statement`** (`repurchase_of_capital_stock`,
   `net_common_stock_issuance`) — 2019+, quarterly, ~45d lag; refine #1 for recent years.
4. **13F aggregate institutional-ownership Δ** — backfill from EDGAR (full-index 1993+/XML
   1999+), quarterly, 45d lag; slow regime feature.
5. **ETF price/volume flow proxy** — daily, local, 1999+; label as proxy.
6. **N-PORT aggregate fund-flow feature** — 2018+, quarterly, free; optional, low priority.

### Dead on arrival (do not build)
- Pension fund holdings (CalPERS/CalSTRS) — annual, months-lagged, no API.
- Daily ETF flows (etf.com / etfdb / fintel) — paywalled/gated.
- ICI monthly flows — gated, monthly, marginal over N-PORT.
- Any 13F-derived *daily* signal — structurally impossible (quarterly, 45d lag).
- 13F backfill before ~1999 (no machine-readable data; images only).

### Engineering notes
- EDGAR scraping rules: descriptive User-Agent with contact info required; ~10 req/s cap;
  backfill 13F via `full-index/master.idx` (1993+) → accession → XML `information_table`.
- `stock_statement.report_date` contains ~1M `"TTM"` junk rows — always regex-filter `^\d{4}`.
- `stock_prices.report_date` is a **date string** (`YYYY-MM-DD`), not epoch — the apparent
  numeric range in an earlier probe was a column-misread artifact.
