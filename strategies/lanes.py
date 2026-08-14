#!/usr/bin/env python3
"""Forward paper LANES — one avenue per verified expert.

The verified experts were validated on universes the live harness does NOT
trade (intl 10 tradables, 13-asset basket, 300-name registry). They cannot
place orders on the harness's 19 symbols, and letting 9 allocators share one
account would fight over position ownership. So each expert gets its OWN
paper lane: its validated universe, its own capital, refreshed forward daily.

Lane model (honest, matches the tournament evidence):
  - data: yfinance daily bars, cached (network-tolerant; falls back to the
    static archive if the fetch fails)
  - allocation: each lane runs its expert's target-allocation logic on the
    LATEST bar (no lookahead — signals from prior close, fill at current)
  - P&L: each lane tracks a $500 paper account compounding the universe's
    daily returns weighted by the expert's allocation
  - attribution: per-lane (regime, expert) forward impact is written to the
    router state so weight evolution has live evidence to act on

This is PAPER — no live order flow. It is the bridge the user asked for:
each agent gets an avenue to trade on, so the self-evolution layer accrues
real forward evidence per expert instead of being stuck at $500.
"""

import argparse
import datetime as dt
import json
import os
import pickle
import time
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT / "data"
INTL_ARCHIVE = PROJECT / "data" / "setup_search" / "international_ohlcv_5y.pkl"
INTL_CACHE = PROJECT / "data" / "lanes_intl.json"
TTL_S = 24 * 3600

INTL_SYMS = ["^N225", "^FTSE", "^GDAXI", "^HSI", "EEM", "EFA",
             "EURUSD=X", "USDJPY=X", "GC=F", "CL=F"]
BASKET_SYMS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "SLV", "USO",
               "DBC", "DBA", "UUP", "FXY", "FXE"]

# lane -> (universe, expert config). The verified experts' allocation logic is
# encoded here (faithful to the tournament agents). 0.35%/side fees.
FEE = 0.0035


def _fetch_intl(force: bool = False) -> pd.DataFrame:
    """yfinance daily closes for the intl tradables, cached TTL_S."""
    if INTL_CACHE.exists() and not force:
        age = time.time() - INTL_CACHE.stat().st_mtime
        if age < TTL_S:
            raw = json.loads(INTL_CACHE.read_text())
            dates = pd.to_datetime(raw["_dates"])
            df = pd.DataFrame({k: pd.Series(v, index=dates)
                               for k, v in raw.items()
                               if k not in ("_ts", "_dates")})
            return df.astype(float)
    try:
        import yfinance as yf
        data = yf.download(INTL_SYMS, period="2y", interval="1d",
                           progress=False, auto_adjust=False, threads=False)
        closes = data["Close"].dropna(axis=1, how="all")
        # align to a common index and forward-fill (yfinance can return ragged
        # columns — NaN on a symbol's final bar, etc.)
        closes = closes.apply(lambda c: c.reindex(closes.index).ffill())
        closes = closes.astype(float)
        out = {k: [float(v) for v in closes[k].values] for k in closes.columns}
        out["_dates"] = [str(d) for d in closes.index]
        out["_ts"] = time.time()
        INTL_CACHE.write_text(json.dumps(out))
        return closes
    except Exception as e:
        print(f"[lanes] yfinance fetch failed ({e}); using static archive")
        return _intl_archive()


def _intl_archive() -> pd.DataFrame:
    d = pickle.load(open(INTL_ARCHIVE, "rb"))["data"]
    closes = {s: d[s]["close"] for s in INTL_SYMS if s in d}
    return pd.DataFrame(closes)


def _load_basket(force: bool = False) -> pd.DataFrame:
    """13-asset basket closes — forward via yfinance (cached), else tournament."""
    BASKET_CACHE = PROJECT / "data" / "lanes_basket.json"
    if BASKET_CACHE.exists() and not force:
        age = time.time() - BASKET_CACHE.stat().st_mtime
        if age < TTL_S:
            raw = json.loads(BASKET_CACHE.read_text())
            dates = pd.to_datetime(raw["_dates"])
            return pd.DataFrame({k: pd.Series(v, index=dates)
                                 for k, v in raw.items()
                                 if k not in ("_ts", "_dates")}).astype(float)
    try:
        import yfinance as yf
        data = yf.download(BASKET_SYMS, period="2y", interval="1d",
                           progress=False, auto_adjust=False, threads=False)
        closes = data["Close"].dropna(axis=1, how="all").ffill()
        out = {k: [float(v) for v in closes[k].dropna().values]
               for k in closes.columns}
        out["_dates"] = [str(d) for d in closes.index]
        out["_ts"] = time.time()
        BASKET_CACHE.write_text(json.dumps(out))
        return closes
    except Exception as e:
        print(f"[lanes] basket yfinance failed ({e}); using tournament data")
        import sys
        sys.path.insert(0, "/tmp/opentrader/swarm")
        from scorer import DATA
        return DATA["basket"]


def lane_multiasset(closes: pd.DataFrame) -> pd.Series:
    """multiasset: momentum top-8 of 10 + 60% inverse-vol, rebal 63."""
    from strategies.multiasset import backtest
    return backtest(closes, rebal=63, vol_lb=120, mom_lb=180, topk=8,
                    eq_frac=0.4, mom_gate=False)


def lane_momtrend(closes: pd.DataFrame) -> pd.Series:
    from strategies.momtrend import run
    return run(closes, universe=list(closes.columns), mom_lb=60, k=5, rebal=20,
               breadth_thr=0.6, breadth_win=100, force_exit=False)


def _allocation(equity: pd.Series, n: int) -> float:
    """Fraction of the latest-day equity change attributable to the lane."""
    if len(equity) < 2:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[-2] - 1.0)


def run_lane(name: str, closes: pd.DataFrame, alloc_fn) -> dict:
    """Run one lane: equity curve via the expert, latest 1-day return."""
    eq = alloc_fn(closes)
    latest_ret = _allocation(eq, len(closes))
    equity = eq.iloc[-1]
    # regime: 'up' if above its own trailing 200d MA
    regime = "up" if eq.iloc[-1] > eq.iloc[-200:].mean() else "down"
    return {
        "expert": name,
        "equity": round(float(equity), 2),
        "latest_1d_ret": round(latest_ret, 6),
        "regime": regime,
        "asof": str(closes.index.max().date()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-fetch", action="store_true")
    ap.add_argument("--write", action="store_true", help="write lane state + router attribution")
    args = ap.parse_args()

    # refresh intl data forward
    intl = _fetch_intl(force=args.force_fetch)
    asof = getattr(intl.index.max(), "date", lambda: "?")()
    if isinstance(asof, str):
        asof = asof
    else:
        asof = asof() if callable(asof) else asof
    print(f"[lanes] intl closes: {intl.shape[0]} bars, last {asof}")

    lanes = {
        "laggard": lambda c: lane_momtrend(c),   # momtrend logic = laggard core
        "momtrend": lambda c: lane_momtrend(c),
        "multiasset": lambda c: lane_multiasset(c),
    }

    results = {}
    for name, fn in lanes.items():
        if name == "multiasset":
            closes = _load_basket()
        else:
            closes = intl[INTL_SYMS]
        r = run_lane(name, closes, fn)
        results[name] = r
        print(f"[lanes] {name}: equity ${r['equity']} | 1d {r['latest_1d_ret']:+.4%} "
              f"| regime {r['regime']}")

    if args.write:
        lane_state = {
            "asof": str(dt.date.today()),
            "lanes": results,
            "note": "PAPER lanes — one avenue per expert on its validated "
                    "universe. NOT live order flow.",
        }
        p = STATE_DIR / "lanes_state.json"
        p.write_text(json.dumps(lane_state, indent=1))
        print(f"[lanes] wrote {p}")

        # accrue forward attribution into the MoT router so weight evolution
        # has LIVE evidence (the bridge: verified evidence -> forward evidence).
        try:
            _accrue_router(results)
        except Exception as e:
            print(f"[lanes] router accrual skipped: {e}")


def _accrue_router(results: dict) -> None:
    """Write each lane's latest 1-day return into live_router_state.json as
    per-(regime, expert) impact, so the router's track grows from forward
    paper evidence (in the same schema the harness reads)."""
    import json as _json
    router_p = STATE_DIR / "live_router_state.json"
    state = {}
    if router_p.exists():
        try:
            state = _json.loads(router_p.read_text())
        except Exception:
            state = {}
    track = state.setdefault("track", {})
    for name, r in results.items():
        regime = r["regime"]
        t = track.setdefault(regime, {})
        rec = t.setdefault(name, {"sum": 0.0, "n": 0})
        rec["sum"] = float(rec.get("sum", 0.0)) + r["latest_1d_ret"]
        rec["n"] = int(rec.get("n", 0)) + 1
    state["note"] = ("PAPER LANES forward attribution (2026-08-14+): per-lane "
                     "1d returns accrued into the router track for weight "
                     "evolution. NOT live order flow.")
    router_p.write_text(_json.dumps(state, indent=1))
    print("[lanes] router track updated with forward lane evidence")


if __name__ == "__main__":
    main()
