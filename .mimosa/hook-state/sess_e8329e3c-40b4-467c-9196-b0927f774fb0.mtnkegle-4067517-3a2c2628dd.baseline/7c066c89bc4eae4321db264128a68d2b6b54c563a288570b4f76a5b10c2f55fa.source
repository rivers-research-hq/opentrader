#!/usr/bin/env python3
"""Fundamental valuation layer — intrinsic value estimation from financial statements.

Builds on data/fundamentals.py to compute:
  - Discounted Cash Flow (DCF) intrinsic value
  - Earnings Power Value (EPV) — Graham-style
  - Comparative multiples (P/E, P/B, EV/EBITDA) vs peer groups
  - Margin of safety gap
  - Composite quality/valuation score (0-100)
  - Text context for the LLM debate engine
"""

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.valuation")

# ── Sector/default assumptions for DCF ──────────────────────────────
# growth_rate: conservative earnings/FCF growth
# terminal_growth: perpetuity growth rate
# discount_rate: WACC estimate
# peer_pe: rough industry P/E for comparative valuation

INDUSTRY_ASSUMPTIONS: Dict[str, dict] = {
    "Technology": {"growth": 0.08, "terminal": 0.03, "discount": 0.10, "peer_pe": 28},
    "Communication Services": {"growth": 0.06, "terminal": 0.03, "discount": 0.09, "peer_pe": 22},
    "Consumer Cyclical": {"growth": 0.05, "terminal": 0.025, "discount": 0.10, "peer_pe": 20},
    "Consumer Defensive": {"growth": 0.03, "terminal": 0.025, "discount": 0.08, "peer_pe": 22},
    "Financial Services": {"growth": 0.04, "terminal": 0.025, "discount": 0.09, "peer_pe": 14},
    "Healthcare": {"growth": 0.06, "terminal": 0.03, "discount": 0.09, "peer_pe": 22},
    "Industrials": {"growth": 0.04, "terminal": 0.025, "discount": 0.09, "peer_pe": 18},
    "Energy": {"growth": 0.02, "terminal": 0.02, "discount": 0.10, "peer_pe": 12},
    "Utilities": {"growth": 0.02, "terminal": 0.02, "discount": 0.07, "peer_pe": 18},
    "Real Estate": {"growth": 0.03, "terminal": 0.025, "discount": 0.08, "peer_pe": 20},
    "Basic Materials": {"growth": 0.03, "terminal": 0.025, "discount": 0.09, "peer_pe": 16},
    "DEFAULT": {"growth": 0.05, "terminal": 0.025, "discount": 0.10, "peer_pe": 20},
}

PROJECTION_YEARS = 5


def _fmt(value: Optional[float], currency: bool = False, pct: bool = False) -> str:
    if value is None:
        return "N/A"
    if pct:
        return f"{value * 100:.1f}%"
    if currency:
        abs_val = abs(value)
        if abs_val >= 1e12:
            return f"${value / 1e12:.2f}T"
        if abs_val >= 1e9:
            return f"${value / 1e9:.2f}B"
        if abs_val >= 1e6:
            return f"${value / 1e6:.2f}M"
        return f"${value:,.0f}"
    return f"{value:.2f}"


def _get_assumptions(industry: Optional[str]) -> dict:
    return INDUSTRY_ASSUMPTIONS.get(industry or "DEFAULT", INDUSTRY_ASSUMPTIONS["DEFAULT"])


# ── DCF Model ──────────────────────────────────────────────────────

def compute_dcf(
    free_cash_flow: float,
    shares_outstanding: float,
    growth_rate: float = 0.05,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
    projection_years: int = PROJECTION_YEARS,
) -> Optional[dict]:
    """Compute Discounted Cash Flow intrinsic value per share.

    Uses a two-stage model: explicit projection period + terminal value.

    Returns dict with intrinsic_value, terminal_value, pv_projections,
    and assumptions, or None if inputs invalid.
    """
    if free_cash_flow <= 0 or shares_outstanding <= 0:
        return None
    if discount_rate <= terminal_growth:
        return None

    pv_sum = 0.0
    projections = []
    fcf = free_cash_flow

    for year in range(1, projection_years + 1):
        fcf *= (1.0 + growth_rate)
        pv = fcf / ((1.0 + discount_rate) ** year)
        pv_sum += pv
        projections.append({"year": year, "fcf": fcf, "pv": pv})

    terminal_fcf = fcf * (1.0 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + discount_rate) ** projection_years)

    enterprise_value = pv_sum + pv_terminal
    intrinsic_per_share = enterprise_value / shares_outstanding

    return {
        "intrinsic_value": intrinsic_per_share,
        "enterprise_value": enterprise_value,
        "pv_projections": pv_sum,
        "pv_terminal": pv_terminal,
        "projections": projections,
        "terminal_value": terminal_value,
        "assumptions": {
            "initial_fcf": free_cash_flow,
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
            "projection_years": projection_years,
        },
    }


# ── Earnings Power Value ───────────────────────────────────────────

def compute_epv(
    operating_income: float,
    tax_rate: float = 0.21,
    discount_rate: float = 0.10,
    shares_outstanding: float = 1.0,
    excess_cash: float = 0.0,
    total_debt: float = 0.0,
) -> Optional[float]:
    """Graham-style Earnings Power Value per share.

    EPV = (Adjusted EBIT * (1 - tax_rate) / discount_rate + excess_cash - debt) / shares
    """
    if operating_income <= 0 or shares_outstanding <= 0:
        return None
    distributable = operating_income * (1.0 - tax_rate)
    epv_operations = distributable / discount_rate
    epv_total = epv_operations + excess_cash - total_debt
    return epv_total / shares_outstanding


# ── Margin of Safety ────────────────────────────────────────────────

def compute_margin_of_safety(intrinsic_value: float, market_price: float) -> Optional[float]:
    """Return margin of safety as a fraction. Positive = undervalued."""
    if intrinsic_value <= 0 or market_price <= 0:
        return None
    return (intrinsic_value - market_price) / intrinsic_value


# ── Quality Score ──────────────────────────────────────────────────

def compute_quality_score(fund: dict) -> int:
    """Composite quality score (0-100) combining profitability, efficiency,
    growth sustainability, and Piotroski F-Score.

    Components:
      - Piotroski F-Score (0-9) * 5 → 0-45
      - ROE quality (durable competitive advantage) → 0-20
      - Gross margin quality → 0-15
      - Debt discipline → 0-10
      - Free cash flow conversion → 0-10
    """
    score = 0

    # Piotroski (0-9 mapped to 0-45)
    fscore = fund.get("piotroski_f_score") or 0
    score += min(fscore, 9) * 5

    # ROE: sustainable, not extreme (10-40% is healthy)
    roe = fund.get("roe")
    if roe is not None and roe > 0:
        if 0.10 <= roe <= 0.15:
            score += 10
        elif 0.15 < roe <= 0.25:
            score += 16
        elif 0.25 < roe <= 0.40:
            score += 20
        elif roe > 0.40:
            score += 14  # extreme, possibly leveraged buybacks
        else:
            score += 6

    # Gross margin: wide moat indicator
    gross = fund.get("gross_margin")
    if gross is not None and gross > 0:
        if gross >= 0.60:
            score += 15
        elif gross >= 0.40:
            score += 12
        elif gross >= 0.25:
            score += 8
        else:
            score += 4

    # Debt discipline
    dte = fund.get("debt_to_equity")
    if dte is not None:
        if dte <= 0.3:
            score += 10
        elif dte <= 0.7:
            score += 7
        elif dte <= 1.5:
            score += 4
        else:
            score += 1

    # FCF conversion: FCF / Net Income (quality of earnings)
    ni = fund.get("net_income")
    fcf = fund.get("free_cash_flow")
    if ni is not None and fcf is not None and ni > 0:
        fcf_ratio = fcf / abs(ni)
        if fcf_ratio >= 0.9:
            score += 10
        elif fcf_ratio >= 0.5:
            score += 7
        elif fcf_ratio >= 0.2:
            score += 4
        else:
            score += 1

    return min(score, 100)


# ── Valuation Summary ──────────────────────────────────────────────

def compute_valuation_summary(
    fund: dict,
    price: Optional[float] = None,
    industry: Optional[str] = None,
    tax_rate: float = 0.21,
) -> dict:
    """Generate a comprehensive valuation summary from fundamentals.

    Uses the fundamentals dict from compute_fundamentals() and computes
    DCF, EPV, and comparative multiples-based intrinsic value estimates.
    Returns a dict suitable for the debate engine.
    """
    assumptions = _get_assumptions(industry)

    # Shares outstanding
    eps = fund.get("eps")
    revenue = fund.get("revenue") or 0
    shares = (revenue / eps) if (eps and eps > 0) else 0

    fcf = fund.get("free_cash_flow") or 0
    op_inc = fund.get("operating_income") or 0
    cash = fund.get("cash") or 0
    debt = fund.get("long_term_debt") or 0
    ni = fund.get("net_income") or 0
    equity = fund.get("stockholders_equity") or 0

    dcf_result = compute_dcf(
        free_cash_flow=fcf,
        shares_outstanding=shares,
        growth_rate=assumptions["growth"],
        discount_rate=assumptions["discount"],
        terminal_growth=assumptions["terminal"],
    )

    epv = compute_epv(
        operating_income=op_inc,
        tax_rate=tax_rate,
        discount_rate=assumptions["discount"],
        shares_outstanding=shares,
        excess_cash=cash,
        total_debt=debt,
    )

    # Comparative (peer P/E)
    peer_pe = assumptions["peer_pe"]
    comp_value = (eps * peer_pe) if (eps and eps > 0) else None

    # Blended intrinsic value (average of available methods)
    estimates = []
    if dcf_result:
        estimates.append(dcf_result["intrinsic_value"])
    if epv:
        estimates.append(epv)
    if comp_value:
        estimates.append(comp_value)
    blended = sum(estimates) / len(estimates) if estimates else None

    margin = None
    upside = None
    if blended and price and price > 0:
        margin = compute_margin_of_safety(blended, price)
        upside = (blended / price - 1.0) if price > 0 else None

    quality = compute_quality_score(fund)

    return {
        "dcf_value": dcf_result["intrinsic_value"] if dcf_result else None,
        "dcf_assumptions": dcf_result["assumptions"] if dcf_result else None,
        "epv": epv,
        "peer_multiple_value": comp_value,
        "peer_pe_applied": peer_pe,
        "blended_intrinsic": blended,
        "market_price": price,
        "margin_of_safety": margin,
        "upside_pct": upside,
        "quality_score": quality,
        "is_undervalued": (margin is not None and margin > 0.15),
        "is_overvalued": (margin is not None and margin < -0.15),
        "shares_outstanding": shares,
        "fcf_yield": (fcf / (price * shares)) if (price and shares > 0 and price > 0) else None,
        "earnings_yield": (eps / price) if (eps and price and price > 0) else None,
    }


# ── Context Serialization ──────────────────────────────────────────

def valuation_to_context(v: dict) -> str:
    """Convert a valuation summary into compact context for the LLM debate engine."""
    lines = ["[VALUATION]"]

    price = v.get("market_price")
    blended = v.get("blended_intrinsic")

    if price and blended:
        margin = v.get("margin_of_safety")
        upside = v.get("upside_pct")
        lines.append(
            f"  Intrinsic: ${blended:.2f} | "
            f"Price: ${price:.2f} | "
            f"MoS: {_fmt(margin, pct=True)} | "
            f"Upside: {_fmt(upside, pct=True)}"
        )
    elif blended:
        lines.append(f"  Intrinsic: ${blended:.2f} | Market price unavailable")

    dcf = v.get("dcf_value")
    epv = v.get("epv")
    peer = v.get("peer_multiple_value")
    parts = []
    if dcf:
        parts.append(f"DCF ${dcf:.2f}")
    if epv:
        parts.append(f"EPV ${epv:.2f}")
    if peer:
        parts.append(f"Peer P/E {v.get('peer_pe_applied')}x → ${peer:.2f}")
    if parts:
        lines.append(f"  Methods: {' | '.join(parts)}")

    lines.append(f"  Quality: {v.get('quality_score')}/100")

    fy = v.get("fcf_yield")
    ey = v.get("earnings_yield")
    yield_parts = []
    if fy is not None:
        yield_parts.append(f"FCF yield {_fmt(fy, pct=True)}")
    if ey is not None:
        yield_parts.append(f"E yield {_fmt(ey, pct=True)}")
    if yield_parts:
        lines.append(f"  Yields: {' | '.join(yield_parts)}")

    status = "NEUTRAL"
    if v.get("is_undervalued"):
        status = "UNDERVALUED"
    elif v.get("is_overvalued"):
        status = "OVERVALUED"
    lines.append(f"  Signal: {status}")

    return "\n".join(lines)


def compute_and_format(
    fund: dict,
    price: Optional[float] = None,
    industry: Optional[str] = None,
) -> str:
    """One-shot: compute valuation and return context string."""
    summary = compute_valuation_summary(fund, price=price, industry=industry)
    return valuation_to_context(summary)
