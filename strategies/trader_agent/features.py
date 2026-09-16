"""Feature extraction for the agentic trader.

Reads the DuckDB accrual store and produces a daily context vector for one
FX pair: recent price action, ATR, volume, macro regime flags, and the
latest exogenous series.

Usage:
    from strategies.trader_agent.features import daily_context
    ctx = daily_context("EUR_USD", days=60)
"""
import duckdb
import json
from datetime import datetime, timezone, timedelta

STORE = "/home/mrc/opentrader-data/store.duckdb"
FRED_SERIES = {
    "DCOILWTICO": "wti_crude",
    "VIXCLS": "vix",
    "T10Y2Y": "yield_curve",
    "DFF": "fed_funds",
    "DTWEXBGS": "dxy",
    "T10YIE": "breakeven_inflation",
    "BAA": "baa_spread",
    "AAA": "aaa_spread",
    "PPIACO": "ppi",
}


def daily_context(symbol: str, days: int = 60) -> dict:
    """Fetch features for one pair: recent bars, macro regime, exog signals.

    Returns a dict that can be serialised to JSON for the agent prompt.
    """
    con = duckdb.connect(STORE, read_only=True)

    # --- price bars (last N days) ---
    bars = con.execute("""
        SELECT ts, open, high, low, close, volume
        FROM bars
        WHERE symbol = ? AND timeframe = '1d'
        ORDER BY ts DESC
        LIMIT ?
    """, (symbol, days)).fetchdf()

    result = {
        "symbol": symbol,
        "asof": datetime.now(timezone.utc).isoformat(),
        "bars": bars.to_dict("records") if not bars.empty else [],
    }

    # --- ATR (14-day, as fraction) ---
    if len(bars) >= 15:
        high = bars["high"].values
        low = bars["low"].values
        close = bars["close"].values
        tr = [max(h - l, abs(h - pc), abs(l - pc))
              for h, l, pc in zip(high[:14], low[:14], close[1:15])]
        atr = sum(tr) / len(tr) / close[0] if close[0] else 0
        result["atr_pct"] = round(atr * 100, 3)
    else:
        result["atr_pct"] = None

    # --- recent change (1d, 5d, 20d) ---
    if len(bars) >= 2:
        closes = bars["close"].values
        result["ret_1d_pct"] = round((closes[0] / closes[1] - 1) * 100, 3)
        result["ret_5d_pct"] = round((closes[0] / closes[min(5, len(closes) - 1)] - 1) * 100, 3)
        result["ret_20d_pct"] = round((closes[0] / closes[min(20, len(closes) - 1)] - 1) * 100, 3)
    else:
        result["ret_1d_pct"] = result["ret_5d_pct"] = result["ret_20d_pct"] = None

    # --- volume anomaly ---
    if len(bars) >= 21:
        vols = bars["volume"].values[:21].astype(float)
        vol_mean = vols[1:].mean()
        result["vol_ratio"] = round(vols[0] / vol_mean, 3) if vol_mean > 0 else 1.0
    else:
        result["vol_ratio"] = None

    # --- latest structured macro values from the accrual store ---
    # exog is a long table: (series, date, value). Read only the latest
    # observation for the FRED series we use; no network call in the agent.
    macro = {}
    for fred in FRED_SERIES:
        row = con.execute("""
            SELECT date, value FROM exog
            WHERE series = ? AND value IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """, ("FRED:" + fred,)).fetchone()
        if row:
            try:
                macro[fred] = {"date": str(row[0]), "value": float(row[1])}
            except (TypeError, ValueError):
                pass
    result["exog"] = macro
    result["exog_date"] = max((v["date"] for v in macro.values()), default=None)

    # --- macro regime flags ---
    exog = result["exog"]
    regimes = {}
    oil = exog.get("DCOILWTICO", {}).get("value")
    vix = exog.get("VIXCLS", {}).get("value")
    curve = exog.get("T10Y2Y", {}).get("value")
    if oil is not None:
        regimes["oil_price"] = round(oil, 2)
        regimes["oil_shock"] = oil > 85
    if vix is not None:
        regimes["vix"] = round(vix, 1)
        regimes["risk_off"] = vix > 25
    if curve is not None:
        regimes["yield_curve"] = round(curve, 2)
        regimes["curve_inverted"] = curve < 0
    result["regime"] = regimes

    con.close()
    return result


def all_symbols() -> list[str]:
    """Return all available D1 symbols in the accrual store."""
    con = duckdb.connect(STORE, read_only=True)
    rows = con.execute("SELECT DISTINCT symbol FROM bars WHERE timeframe='1d' ORDER BY symbol").fetchall()
    con.close()
    return [r[0] for r in rows]
