#!/usr/bin/env python3
"""SEC EDGAR fundamentals ingestion — financial statements from 10-K/10-Q filings.

Parses the SEC XBRL Company Facts API to extract income statement, balance sheet,
and cash flow data: revenue, earnings, assets, liabilities, equity, margins, etc.

Caches results in data/fundamentals_cache.db with configurable TTL.

API reference: https://www.sec.gov/files/companyfacts-example.json
"""

import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("opentrader.fundamentals")

DB_PATH = Path(__file__).parent / "fundamentals_cache.db"
CIK_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&output=json"
HEADERS = {"User-Agent": "OpenTrader/1.0 (contact@example.com)", "Accept": "application/json"}

# Key XBRL taxonomy concepts for financial statements
INCOME_STATEMENT_ITEMS = {
    "Revenues": "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenue": "Revenues",
    "CostOfRevenue": "CostOfRevenue",
    "CostOfGoodsAndServicesSold": "CostOfGoodsAndServicesSold",
    "GrossProfit": "GrossProfit",
    "OperatingExpenses": "OperatingExpenses",
    "ResearchAndDevelopmentExpense": "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense": "SellingGeneralAndAdministrativeExpense",
    "OperatingIncomeLoss": "OperatingIncomeLoss",
    "InterestExpense": "InterestExpense",
    "IncomeTaxExpenseBenefit": "IncomeTaxExpenseBenefit",
    "NetIncomeLoss": "NetIncomeLoss",
    "EarningsPerShareBasic": "EarningsPerShareBasic",
    "EarningsPerShareDiluted": "EarningsPerShareDiluted",
    "WeightedAverageNumberOfSharesOutstandingBasic": "WeightedAverageNumberOfSharesOutstandingBasic",
}

BALANCE_SHEET_ITEMS = {
    "Assets": "Assets",
    "CurrentAssets": "AssetsCurrent",
    "CashAndCashEquivalents": "CashAndCashEquivalentsAtCarryingValue",
    "ShortTermInvestments": "ShortTermInvestments",
    "AccountsReceivable": "AccountsReceivableNetCurrent",
    "Inventory": "InventoryNet",
    "PropertyPlantAndEquipment": "PropertyPlantAndEquipmentNet",
    "Goodwill": "Goodwill",
    "IntangibleAssets": "IntangibleAssetsNetExcludingGoodwill",
    "TotalAssets": "Assets",
    "CurrentLiabilities": "LiabilitiesCurrent",
    "LongTermDebt": "LongTermDebtNoncurrent",
    "TotalLiabilities": "Liabilities",
    "CommonStock": "CommonStockValue",
    "RetainedEarnings": "RetainedEarningsAccumulatedDeficit",
    "StockholdersEquity": "StockholdersEquity",
    "TotalEquity": "StockholdersEquity",
}

CASH_FLOW_ITEMS = {
    "OperatingCashFlow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "CapitalExpenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "FreeCashFlow": None,  # computed: OCF - CapEx
    "DividendsPaid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "StockRepurchased": [
        "PaymentsForRepurchaseOfCommonStock",
        "PaymentsForRepurchaseOfEquity",
    ],
    "FinancingCashFlow": [
        "NetCashProvidedByUsedInFinancingActivities",
        "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
    ],
    "InvestingCashFlow": [
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
    ],
}

US_GAAP = "us-gaap"
IFRS = "ifrs-full"


def _db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """CREATE TABLE IF NOT EXISTS facts_cache
        (cik INTEGER, ticker TEXT, fetched_ts REAL, raw_json TEXT,
         PRIMARY KEY (cik))"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS cik_ticker
        (cik INTEGER PRIMARY KEY, ticker TEXT, name TEXT)"""
    )
    db.commit()
    return db


def _ticker_to_cik(ticker: str) -> Optional[int]:
    ticker = ticker.upper().strip()
    try:
        with _db() as db:
            row = db.execute(
                "SELECT cik FROM cik_ticker WHERE ticker = ?", (ticker,)
            ).fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return _fetch_cik_from_sec(ticker)


def _fetch_cik_from_sec(ticker: str) -> Optional[int]:
    try:
        req = Request(CIK_TICKER_URL, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                cik = int(entry["cik_str"])
                with _db() as db:
                    db.execute(
                        "INSERT OR REPLACE INTO cik_ticker VALUES (?, ?, ?)",
                        (cik, ticker.upper(), entry.get("title", "")),
                    )
                    db.commit()
                return cik
    except Exception as e:
        logger.debug(f"CIK lookup failed for {ticker}: {e}")
    return None


def _extract_metric(facts: dict, concept: str, unit: str = "USD",
                    taxonomy: str = US_GAAP) -> List[Tuple[str, float, str, int, str]]:
    """Extract a metric from SEC facts JSON. Returns [(period_key, value, form, fy, filed), ...].

    period_key: CY20XX or CY20XXQX or FY string
    """
    raw = []
    for tax in [taxonomy, IFRS] if taxonomy == US_GAAP else [taxonomy]:
        tax_data = facts.get("facts", {}).get(tax, {})
        if not tax_data:
            continue
        concept_data = tax_data.get(concept, {})
        if not concept_data:
            continue
        units = concept_data.get("units", {})
        for u in [unit, f"{unit}/shares", "shares", "pure"]:
            entries = units.get(u, [])
            if entries:
                for entry in entries:
                    fy = entry.get("fy") or 0
                    fp = entry.get("fp") or ""
                    filed = entry.get("filed") or ""
                    form = entry.get("form", "")
                    frame = entry.get("frame")
                    val = entry.get("val")
                    if val is None:
                        continue
                    if form not in ("10-K", "10-Q", "20-F", "10-K/A", "10-Q/A"):
                        continue
                    period_key = frame or (f"{fy}-{fp}" if fy and fp else filed[:10])
                    raw.append((period_key, val, form, fy, filed))
                break
        if raw:
            break

    # Deduplicate: for each (fy, period_key), keep the most recently filed entry
    # preferring original filings over amendments
    by_key: Dict[Tuple[int, str], Tuple[str, float, str, str]] = {}
    for pkey, val, form, fy, filed in raw:
        key = (fy, pkey)
        if key not in by_key:
            by_key[key] = (val, form, filed)
        else:
            existing_val, existing_form, existing_filed = by_key[key]
            has_10k = "10-K" in form and "10-Q" not in form and "A" not in form
            existing_10k = "10-K" in existing_form and "10-Q" not in existing_form and "A" not in existing_form
            if has_10k and not existing_10k:
                by_key[key] = (val, form, filed)
            elif has_10k == existing_10k and filed > existing_filed:
                by_key[key] = (val, form, filed)

    # Sort by fy then period, return (period_key, val, form, fy, filed)
    result = [(pkey, vf[0], vf[1], fy, vf[2])
              for (fy, pkey), vf in sorted(by_key.items(), key=lambda x: x[0])]
    return result


def _pick_annual(values: List[Tuple[str, float, str, int, str]]) -> List[Tuple[str, float]]:
    """Pick annual values per fiscal year from SEC XBRL facts.

    Periods like '2024-FY' or 'CY2024' are annual; 'CY2024Q4' is quarterly.
    We prefer original FY entries from 10-K filings. For the most recent year
    without a 10-K yet, we fall back to the latest quarterly value.
    """
    def _parse_target_fy(period: str) -> Optional[int]:
        m = re.match(r'(\d{4})-FY$', period)
        if m:
            return int(m.group(1))
        m = re.match(r'CY(\d{4})$', period)
        if m:
            return int(m.group(1))
        m = re.match(r'CY(\d{4})Q4$', period) or re.match(r'(\d{4})-Q4$', period)
        if m:
            return int(m.group(1))
        return None

    by_fy: Dict[int, Tuple[str, float, bool, bool]] = {}
    for period, val, form, fy, filed in values:
        target_fy = _parse_target_fy(period)
        if target_fy is None:
            continue
        is_annual = "-FY" in period or (period.startswith("CY") and "Q" not in period)
        is_10k = "10-K" in form and "A" not in form

        if target_fy not in by_fy:
            by_fy[target_fy] = (period, val, is_annual, is_10k)
            continue

        ep, ev, ea, ek = by_fy[target_fy]
        if is_annual and not ea:
            by_fy[target_fy] = (period, val, True, is_10k)
        elif is_annual == ea:
            if is_10k and not ek:
                by_fy[target_fy] = (period, val, is_annual, True)
            elif is_10k == ek and "-FY" in period and "-FY" not in ep:
                by_fy[target_fy] = (period, val, is_annual, is_10k)

    result = [(p, v) for p, v, _, _ in sorted(by_fy.values(), key=lambda x: _parse_target_fy(x[0]) or 0)]
    return result


def fetch_company_facts(ticker: str, force: bool = False,
                        cache_ttl: float = 86400) -> Optional[Dict[str, Any]]:
    """Fetch and parse SEC company facts for a given ticker.

    Returns a structured dict of financials or None on failure.
    Cache TTL is 24 hours by default.
    """
    ticker = ticker.upper().strip()
    cik = _ticker_to_cik(ticker)
    if not cik:
        logger.warning(f"No CIK found for {ticker}")
        return None

    # Check cache
    if not force:
        try:
            with _db() as db:
                row = db.execute(
                    "SELECT fetched_ts, raw_json FROM facts_cache WHERE cik = ?",
                    (cik,),
                ).fetchone()
                if row and time.time() - row[0] < cache_ttl:
                    return json.loads(row[1])
        except Exception:
            pass

    # Fetch from SEC
    url = FACTS_URL.format(cik=cik)
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode())
    except URLError as e:
        logger.warning(f"SEC facts fetch failed for {ticker} (CIK {cik}): {e}")
        return None

    # Cache
    try:
        with _db() as db:
            db.execute(
                "INSERT OR REPLACE INTO facts_cache VALUES (?, ?, ?, ?)",
                (cik, ticker, time.time(), json.dumps(raw)),
            )
            db.commit()
    except Exception as e:
        logger.debug(f"Cache write failed for {ticker}: {e}")

    return raw


def parse_income_statement(facts: dict) -> Dict[str, List[Tuple[str, float]]]:
    """Extract income statement metrics from SEC facts JSON.

    Returns dict mapping metric name -> [(period, value), ...]
    """
    result = {}
    for metric_name, concept in INCOME_STATEMENT_ITEMS.items():
        if concept is None:
            continue
        vals = _extract_metric(facts, concept)
        if vals:
            result[metric_name] = _pick_annual(vals)
    return result


def parse_balance_sheet(facts: dict) -> Dict[str, List[Tuple[str, float]]]:
    """Extract balance sheet metrics from SEC facts JSON."""
    result = {}
    for metric_name, concept in BALANCE_SHEET_ITEMS.items():
        if concept is None:
            continue
        vals = _extract_metric(facts, concept)
        if vals:
            result[metric_name] = _pick_annual(vals)
    return result


def parse_cash_flow(facts: dict) -> Dict[str, List[Tuple[str, float]]]:
    """Extract cash flow metrics from SEC facts JSON with concept fallbacks."""
    result = {}
    for metric_name, concepts in CASH_FLOW_ITEMS.items():
        if concepts is None:
            continue
        merged: Dict[str, float] = {}
        for concept in concepts:
            vals = _extract_metric(facts, concept)
            if not vals:
                continue
            annual = _pick_annual(vals)
            for period, val in annual:
                if period not in merged:
                    merged[period] = val
        if merged:
            result[metric_name] = sorted(merged.items(),
                                         key=lambda x: _parse_period_year(x[0]) or 0)

    # Compute free cash flow — only add CapEx where OCF exists for same period
    ocf = result.get("OperatingCashFlow", [])
    capex = result.get("CapitalExpenditure", [])
    if ocf and capex:
        capex_map = dict(capex)
        fcf = []
        for period, ocf_val in ocf:
            if period in capex_map:
                fcf.append((period, ocf_val + capex_map[period]))
        if fcf:
            result["FreeCashFlow"] = fcf

    return result


def _latest_value(series: List[Tuple[str, float]]) -> Optional[float]:
    if series:
        return series[-1][1]
    return None


def _growth_rate(series: List[Tuple[str, float]]) -> Optional[float]:
    """YoY growth between the two most recent values."""
    if len(series) >= 2:
        prev, curr = series[-2][1], series[-1][1]
        if prev and prev != 0:
            return (curr - prev) / abs(prev)
    return None


def _parse_period_year(period: str) -> Optional[int]:
    m = re.match(r'CY(\d{4})', period)
    if m:
        return int(m.group(1))
    m = re.match(r'(\d{4})-FY$', period)
    if m:
        return int(m.group(1))
    m = re.match(r'(\d{4})-Q4$', period)
    if m:
        return int(m.group(1))
    return None


def _gap_free_growth_rate(series: List[Tuple[str, float]]) -> Optional[float]:
    """YoY growth using the most recent consecutive-year pair.

    Skips over gaps caused by missing filings or concept changes.
    Returns None if no consecutive-year pair exists.
    """
    if len(series) < 2:
        return None
    for i in range(len(series) - 1, 0, -1):
        curr_yr = _parse_period_year(series[i][0])
        prev_yr = _parse_period_year(series[i - 1][0])
        if curr_yr is not None and prev_yr is not None and curr_yr - prev_yr == 1:
            prev_val, curr_val = series[i - 1][1], series[i][1]
            if prev_val and prev_val != 0:
                return (curr_val - prev_val) / abs(prev_val)
    return None


def compute_fundamentals(ticker: str, price: Optional[float] = None,
                         force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch and compute a comprehensive fundamentals snapshot for a ticker.

    Returns a dict with valuation metrics, growth rates, and quality scores,
    suitable for injecting into the debate context.
    """
    facts = fetch_company_facts(ticker, force=force)
    if not facts:
        return None

    income = parse_income_statement(facts)
    balance = parse_balance_sheet(facts)
    cashflow = parse_cash_flow(facts)

    revenue = income.get("Revenues") or income.get("Revenue") or []
    net_income = income.get("NetIncomeLoss") or []
    eps = income.get("EarningsPerShareBasic") or income.get("EarningsPerShareDiluted") or []
    gross_profit = income.get("GrossProfit") or []
    operating_income = income.get("OperatingIncomeLoss") or []
    operating_expense = income.get("OperatingExpenses") or []

    total_assets = balance.get("TotalAssets") or balance.get("Assets") or []
    total_liabilities = balance.get("TotalLiabilities") or []
    equity = balance.get("StockholdersEquity") or balance.get("TotalEquity") or []
    long_term_debt = balance.get("LongTermDebt") or []
    current_assets = balance.get("CurrentAssets") or []
    current_liabilities = balance.get("CurrentLiabilities") or []
    cash = balance.get("CashAndCashEquivalents") or []
    goodwill = balance.get("Goodwill") or []

    ocf = cashflow.get("OperatingCashFlow") or []
    fcf = cashflow.get("FreeCashFlow") or []
    capex = cashflow.get("CapitalExpenditure") or []

    # Raw values
    rev_val = _latest_value(revenue)
    ni_val = _latest_value(net_income)
    eps_val = _latest_value(eps)
    equity_val = _latest_value(equity)
    assets_val = _latest_value(total_assets)
    liab_val = _latest_value(total_liabilities)
    ltd_val = _latest_value(long_term_debt)
    ocf_val = _latest_value(ocf)
    fcf_val = _latest_value(fcf)
    cash_val = _latest_value(cash)
    gross_val = _latest_value(gross_profit)
    op_inc_val = _latest_value(operating_income)
    op_exp_val = _latest_value(operating_expense)
    cur_a_val = _latest_value(current_assets)
    cur_l_val = _latest_value(current_liabilities)
    gw_val = _latest_value(goodwill)

    # Valuation ratios
    pe_ratio = None
    pb_ratio = None
    if price and eps_val and eps_val > 0:
        pe_ratio = price / eps_val
    if price and equity_val and equity_val > 0:
        shares_outstanding = (rev_val / eps_val if eps_val and eps_val > 0 else None)
        if shares_outstanding:
            bvps = equity_val / shares_outstanding
            if bvps > 0:
                pb_ratio = price / bvps

    # Enterprise Value / EBITDA (approximate)
    ev = None
    ebitda = None
    ev_ebitda = None
    if price and equity_val and ltd_val and cash_val and ni_val:
        shares_outstanding = (rev_val / eps_val if (eps_val and eps_val > 0) else 0)
        if shares_outstanding and shares_outstanding > 0:
            market_cap = price * shares_outstanding
            ev = market_cap + ltd_val - cash_val
            # Approximate EBITDA: operating income + D&A (not directly available, use clues)
            if op_inc_val and op_inc_val > 0:
                ebitda = op_inc_val * 1.3  # rough approximation
                if ebitda > 0:
                    ev_ebitda = ev / ebitda

    # Profitability ratios
    roe = None
    roa = None
    gross_margin = None
    op_margin = None
    net_margin = None
    debt_to_equity = None
    current_ratio = None

    if equity_val and ni_val and equity_val != 0:
        roe = ni_val / equity_val
    if assets_val and ni_val and assets_val != 0:
        roa = ni_val / assets_val
    if rev_val and gross_val and rev_val != 0:
        gross_margin = gross_val / rev_val
    if rev_val and op_inc_val and rev_val != 0:
        op_margin = op_inc_val / rev_val
    if rev_val and ni_val and rev_val != 0:
        net_margin = ni_val / rev_val
    if equity_val and ltd_val and equity_val != 0:
        debt_to_equity = ltd_val / equity_val
    if cur_l_val and cur_a_val and cur_l_val != 0:
        current_ratio = cur_a_val / cur_l_val

    # Growth rates (YoY) — gap-free, only consecutive fiscal years
    rev_growth = _gap_free_growth_rate(revenue)
    earnings_growth = _gap_free_growth_rate(net_income)
    fcf_growth = _gap_free_growth_rate(fcf)
    equity_growth = _gap_free_growth_rate(equity)

    # Piotroski F-Score (0-9, fundamental quality)
    fscore = _piotroski_score(
        net_income, ocf, roa, earnings_growth,
        gross_margin, current_ratio,
        equity_val, ltd_val, debt_to_equity,
    )

    # Tangible book value
    if equity_val and gw_val:
        tangible_equity = equity_val - gw_val
    else:
        tangible_equity = equity_val

    result = {
        "ticker": ticker,
        "cik": _ticker_to_cik(ticker),
        "price": price,
        # Income
        "revenue": rev_val,
        "gross_profit": gross_val,
        "operating_income": op_inc_val,
        "net_income": ni_val,
        "eps": eps_val,
        # Balance
        "total_assets": assets_val,
        "total_liabilities": liab_val,
        "long_term_debt": ltd_val,
        "stockholders_equity": equity_val,
        "tangible_equity": tangible_equity,
        "cash": cash_val,
        "current_assets": cur_a_val,
        "current_liabilities": cur_l_val,
        "goodwill": gw_val,
        # Cash flow
        "operating_cash_flow": ocf_val,
        "free_cash_flow": fcf_val,
        "capital_expenditure": _latest_value(capex),
        # Valuation
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "ev": ev,
        "ev_ebitda": ev_ebitda,
        # Profitability
        "roe": roe,
        "roa": roa,
        "gross_margin": gross_margin,
        "operating_margin": op_margin,
        "net_margin": net_margin,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        # Growth
        "revenue_growth_yoy": rev_growth,
        "earnings_growth_yoy": earnings_growth,
        "fcf_growth_yoy": fcf_growth,
        "equity_growth_yoy": equity_growth,
        # Quality
        "piotroski_f_score": fscore,
        # Periods
        "income_periods": len(revenue),
        "balance_periods": len(total_assets),
        "cashflow_periods": len(ocf),
    }
    return result


def _piotroski_score(
    net_income: list, operating_cf: list,
    roa: Optional[float], earnings_growth: Optional[float],
    gross_margin: Optional[float], current_ratio: Optional[float],
    equity: Optional[float], long_term_debt: Optional[float],
    debt_to_equity: Optional[float],
) -> int:
    """Compute Piotroski F-Score (0-9)."""
    score = 0

    # Profitability signals
    ni_latest = _latest_value(net_income)
    ni_prev = net_income[-2][1] if len(net_income) >= 2 else None
    if ni_latest and ni_latest > 0:
        score += 1
    if roa and roa > 0:
        score += 1
    ocf_latest = _latest_value(operating_cf)
    if ocf_latest and ocf_latest > 0:
        score += 1
    if ocf_latest and ni_latest and ocf_latest / ni_latest > 1 if ni_latest else False:
        score += 1

    # Leverage/liquidity signals
    ltd_latest = _latest_value(long_term_debt) if isinstance(long_term_debt, list) else long_term_debt
    ltd_prev = long_term_debt[-2][1] if isinstance(long_term_debt, list) and len(long_term_debt) >= 2 else None
    if ltd_prev and ltd_latest and ltd_latest < ltd_prev:
        score += 1
    if current_ratio and current_ratio > 1.5:
        score += 1

    # Operating efficiency
    gm_prev = None  # simplified
    if gross_margin and gross_margin > 0:
        score += 1
    if ni_prev and ni_latest and ni_latest > ni_prev:
        score += 1

    # New shares issued (not computed without shares outstanding data)
    # Simplified: add 1 point if no sign of dilution
    if not (ni_latest and ni_prev and ni_prev > ni_latest):
        score += 1

    return score


def fundamentals_to_context(fund: dict) -> str:
    """Convert a fundamentals dict into a compact context string for the LLM debate."""
    if not fund:
        return ""

    def fmt(val, pct=False, currency=False):
        if val is None:
            return "N/A"
        if pct:
            return f"{val * 100:.1f}%"
        if currency and abs(val) >= 1e9:
            return f"${val / 1e9:.2f}B"
        if currency and abs(val) >= 1e6:
            return f"${val / 1e6:.1f}M"
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    lines = [
        f"[FUNDAMENTALS] {fund.get('ticker', '?')}",
        f"  Revenue: {fmt(fund.get('revenue'), currency=True)} | "
        f"Net Income: {fmt(fund.get('net_income'), currency=True)} | "
        f"EPS: {fmt(fund.get('eps'))}",
        f"  Growth: Rev {fmt(fund.get('revenue_growth_yoy'), pct=True)} | "
        f"Earnings {fmt(fund.get('earnings_growth_yoy'), pct=True)} | "
        f"FCF {fmt(fund.get('fcf_growth_yoy'), pct=True)}",
        f"  Profitability: Gross {fmt(fund.get('gross_margin'), pct=True)} | "
        f"Op {fmt(fund.get('operating_margin'), pct=True)} | "
        f"Net {fmt(fund.get('net_margin'), pct=True)}",
        f"  ROE: {fmt(fund.get('roe'), pct=True)} | "
        f"ROA: {fmt(fund.get('roa'), pct=True)} | "
        f"D/E: {fmt(fund.get('debt_to_equity'))}",
        f"  Valuation: P/E {fmt(fund.get('pe_ratio'))} | "
        f"P/B {fmt(fund.get('pb_ratio'))} | "
        f"EV/EBITDA {fmt(fund.get('ev_ebitda'))}",
        f"  FCF: {fmt(fund.get('free_cash_flow'), currency=True)} | "
        f"Cash: {fmt(fund.get('cash'), currency=True)} | "
        f"Debt: {fmt(fund.get('long_term_debt'), currency=True)}",
        f"  Piotroski F-Score: {fund.get('piotroski_f_score', 'N/A')}/9",
    ]

    price = fund.get("price")
    eps = fund.get("eps")
    if price and eps and eps > 0:
        lines.append(f"  Price/EPS: {price:.2f} / {eps:.2f} = P/E {price/eps:.1f}")

    return "\n".join(lines)


def fetch_fundamentals_batch(tickers: List[str], prices: Optional[Dict[str, float]] = None,
                             force: bool = False, max_concurrent: int = 5) -> Dict[str, dict]:
    """Fetch fundamentals for multiple tickers. Respects SEC rate limits."""
    results = {}
    prices = prices or {}
    for ticker in tickers:
        try:
            price = prices.get(ticker.upper())
            fund = compute_fundamentals(ticker, price=price, force=force)
            if fund:
                results[ticker] = fund
        except Exception as e:
            logger.debug(f"Fundamentals fetch failed for {ticker}: {e}")
        time.sleep(0.15)  # SEC rate limit: ~10 requests/sec max
    return results
