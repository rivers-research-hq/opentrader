#!/usr/bin/env python3
"""signal_gym — walkforward verifier for candidate FX signals (Track B research).

A CANDIDATE is a Python file in data/signal_gym/candidates/ defining:
    NAME   = "unique-name"
    def entry(ctx) -> dict   # {symbol: weight}; only instruments to LONG
    # optional: def exit(ctx, sym) -> bool   (default exits: ATR stop/target/hold)

The gym applies UNIFORM risk shape to every candidate (ATR stop/target/hold,
$10k notional per position, spread cost) so candidates compete on entry
selection, not on risk parameters — fewer degrees of freedom to overfit.

Walkforward: first 60% of dates = in-sample, last 40% = out-of-sample.
A candidate SURVIVES only if: IS trades >= 10 and IS PF >= 1.2, and
OOS trades >= 5 and OOS PF >= 1.0. Everything else is dead.

Candles are cached once from the OANDA practice API (7 majors, 500 D1).
"""

import ast
import bisect
import importlib.util
import json
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path("/home/mrc/opentrader")
GYM = PROJECT / "data" / "signal_gym"
CAND_DIR = GYM / "candidates"
CACHE = GYM / "candles.json"
EXOG = PROJECT / "data" / "exog_cache.json"
SPREAD = 0.0001
TOP_N = 2
CASH0 = 100_000.0
K, ATR_STOP, ATR_TP, HOLD = 5, 1.5, 2.5, 14


def fetch_candles():
    sys.path.insert(0, str(PROJECT))
    from exchange.oanda import OandaExchange
    ex = OandaExchange()
    ex.connect()
    out = {}
    for sym in ex.discover_symbols():
        bars = ex.get_bars(sym, "1d", 500)
        out[sym] = {b.timestamp: (b.open, b.high, b.low, b.close) for b in bars}
    CACHE.write_text(json.dumps(out))
    return out


def load_candles():
    if not CACHE.exists():
        return fetch_candles()
    return json.load(CACHE.read_text() and open(CACHE))


class Ctx:
    """Read-only market context handed to candidate functions."""

    def __init__(self, series, dates, i, symbols, exog_series=None):
        self.series = series
        self.dates = dates
        self.i = i
        self.symbols = symbols
        self.date = dates[i]
        self.exog_series = exog_series or {}

    def exog(self, key):
        """Point-in-time exogenous value: latest cached observation whose
        publication date is usable at the bar's date. COT reports carry
        Tuesday positions and go public Friday -> 3-day publication lag.
        Sorted-key index is cached on the series dict for bisect lookup."""
        series = self.exog_series.get(key)
        if not series:
            return None
        ks = series.get("_sorted_keys")
        if ks is None:
            ks = sorted(k for k in series if k != "_sorted_keys")
            series["_sorted_keys"] = ks
        d = datetime.utcfromtimestamp(int(self.date)).strftime("%Y-%m-%d")
        usable = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
        j = bisect.bisect_right(ks, usable)
        return series[ks[j - 1]] if j else None

    def close(self, sym):
        px = self.series.get(sym, {}).get(self.dates[self.i])
        return px[3] if px else None

    def close_n(self, sym, k):
        j = self.i - k
        if j < 0:
            return None
        px = self.series.get(sym, {}).get(self.dates[j])
        return px[3] if px else None

    def ma(self, sym, n):
        vals = [self.series.get(sym, {}).get(self.dates[j]) for j in range(max(0, self.i - n), self.i)]
        vals = [x[3] for x in vals if x]
        return sum(vals) / len(vals) if len(vals) == n else None

    def atr(self, sym, n):
        vals = [self.series.get(sym, {}).get(self.dates[j]) for j in range(max(0, self.i - n - 1), self.i)]
        if len(vals) < 2:
            return None
        trs = [max(vals[k][1] - vals[k][2], abs(vals[k][1] - vals[k - 1][3]),
                   abs(vals[k][2] - vals[k - 1][3])) for k in range(1, len(vals))]
        return sum(trs) / len(trs)

    def mom(self, sym, k):
        c, ck = self.close(sym), self.close_n(sym, k)
        return c / ck - 1 if c and ck else None


def check_safety(path):
    """Cheap insurance: candidates must not import, open files, or call exec/eval."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError(f"{path.name}: imports are not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("open", "exec", "eval", "compile", "__import__"):
                raise ValueError(f"{path.name}: {node.func.id}() is not allowed")
    return True


def load_candidate(path):
    check_safety(path)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "NAME") and hasattr(mod, "entry"), f"{path.name}: needs NAME and entry(ctx)"
    return mod


def simulate(cand, series, dates, symbols, is_end, exog=None):
    cash = CASH0
    book = {}
    trades = {"is": [], "oos": []}
    eq = []
    for i, d in enumerate(dates):
        if i < 60:
            continue
        e = cash
        for sym, pos in book.items():
            px = series.get(sym, {}).get(d)
            if px:
                e += (px[3] - pos["entry"]) * pos["units"]
        eq.append(e)
        ctx = Ctx(series, dates, i, symbols, exog_series=exog)
        for sym in list(book):
            px = series.get(sym, {}).get(d)
            if not px:
                continue
            pos = book[sym]
            pnl = None
            if hasattr(cand, "exit"):
                try:
                    if cand.exit(ctx, sym):
                        pnl = (px[3] - pos["entry"]) * pos["units"] - SPREAD * pos["units"]
                except Exception:
                    pass
            else:
                if px[2] <= pos["stop"]:
                    pnl = (pos["stop"] - pos["entry"]) * pos["units"] - SPREAD * pos["units"]
                elif px[1] >= pos["target"]:
                    pnl = (pos["target"] - pos["entry"]) * pos["units"] + SPREAD * pos["units"]
                elif i - pos["day"] >= HOLD:
                    pnl = (px[3] - pos["entry"]) * pos["units"] - SPREAD * pos["units"]
            if pnl is not None:
                cash += pnl
                bucket = "is" if pos["day"] < is_end else "oos"
                trades[bucket].append(pnl)
                del book[sym]
        try:
            picks = cand.entry(ctx)
            assert isinstance(picks, dict)
        except Exception as e:
            print(f"    ! entry() failed on {d}: {e}")
            continue
        top = sorted(picks.items(), key=lambda kv: -kv[1])[:TOP_N]
        for sym, _w in top:
            px = series.get(sym, {}).get(d)
            if not px or sym in book:
                continue
            atr = ctx.atr(sym, 14) or 0
            if atr <= 0:
                continue
            units = int(10_000 / px[3])
            book[sym] = {"entry": px[3], "units": units,
                         "stop": px[3] - ATR_STOP * atr, "target": px[3] + ATR_TP * atr,
                         "day": i}
    return trades, eq


def stats(pnl_list):
    if not pnl_list:
        return None
    wins = [t for t in pnl_list if t > 0]
    gl = abs(sum(t for t in pnl_list if t <= 0))
    pf = (sum(wins) / gl) if gl else float("inf")
    return {"n": len(pnl_list), "wr": len(wins) / len(pnl_list) * 100,
            "pf": pf, "pl": sum(pnl_list)}


def main():
    GYM.mkdir(parents=True, exist_ok=True)
    CAND_DIR.mkdir(parents=True, exist_ok=True)
    series = load_candles()
    alldates = sorted({d for sym in series for d in series[sym]})
    symbols = list(series)
    is_end = int(len(alldates) * 0.6)
    exog = json.load(open(EXOG)) if EXOG.exists() else {}
    exog_keys = [k for k in exog if k != "meta"]
    print(f"signal gym — {len(symbols)} majors, {len(alldates)} D1 dates, "
          f"IS {alldates[0]}..{alldates[is_end-1]}, OOS {alldates[is_end]}..{alldates[-1]}")
    print(f"uniform risk: ${10_000}/pos, {ATR_STOP}/{ATR_TP} ATR stop/target, {HOLD}d hold, {SPREAD}/side")
    print(f"exogenous cache: {len(exog_keys)} series {exog_keys if exog_keys else '(none — exog candidates will honestly produce no picks)'}\n")

    cands = sorted(CAND_DIR.glob("*.py"))
    if not cands:
        print("no candidates — write files into data/signal_gym/candidates/")
        return
    survivors = []
    for path in cands:
        try:
            cand = load_candidate(path)
        except Exception as e:
            print(f"  {path.name}: REJECTED ({e})")
            continue
        try:
            trades, eq = simulate(cand, series, alldates, symbols, is_end, exog=exog)
        except Exception as e:
            print(f"  {getattr(cand, 'NAME', path.name)}: RUNTIME ERROR ({e})")
            continue
        s_is, s_oos = stats(trades["is"]), stats(trades["oos"])
        fmt = lambda s: f"n={s['n']:3d} WR {s['wr']:4.1f}% PF {s['pf']:4.2f} P/L ${s['pl']:+6,.0f}" if s else "n=  0"
        survives = (s_is and s_oos and s_is["n"] >= 10 and s_is["pf"] >= 1.2
                    and s_oos["n"] >= 5 and s_oos["pf"] >= 1.0)
        tag = "★ SURVIVES" if survives else "dead"
        print(f"  {getattr(cand, 'NAME', path.stem):32s} IS[{fmt(s_is)}]  OOS[{fmt(s_oos)}]  {tag}")
        if survives:
            survivors.append((cand.NAME, s_is, s_oos))
    print(f"\nresult: {len(survivors)} survivor(s) of {len(cands)} candidates "
          f"(survival bar: IS n>=10 PF>=1.2, OOS n>=5 PF>=1.0)")
    for name, s_is, s_oos in survivors:
        print(f"  ★ {name}: OOS P/L ${s_oos['pl']:+,.0f}, OOS PF {s_oos['pf']:.2f}")


if __name__ == "__main__":
    main()
