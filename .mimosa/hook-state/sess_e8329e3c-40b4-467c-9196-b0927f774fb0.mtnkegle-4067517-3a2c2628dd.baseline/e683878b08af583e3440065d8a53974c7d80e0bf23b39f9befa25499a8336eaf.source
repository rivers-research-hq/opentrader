#!/usr/bin/env python3
"""fx_shadow — shadow paper lane for epoch-registry challengers (Track B FX).

Loads its candidate directly from the signal gym (single source of truth —
no drift between what was verified and what shadows). Default: c08_mr_fade_cot
(gym survivor 2026-08-31: IS PF 1.73 n=34 / OOS PF 2.54 n=22 — the c04
mean-reversion fade plus a COT crowded-positioning filter). Override with
--candidate <name>. The candidate receives a ShadowCtx mirroring the gym's
Ctx for the methods candidates use (close/ma/exog/symbols — keep in sync
with scripts/signal_gym.Ctx), built on real completed OANDA D1 candles.

Risk shape is applied by THIS module, uniform for every candidate (gym
convention): top-2 by stable insertion order, $10k notional, stop/target
1.5x/2.5x ATR-14 (ATR over the 15 bars before the signal bar), 14-bar max
hold, stop checked before target on each bar. Entry uses the candidate's
own selection only.

PURE PAPER: this module places NO orders. Prices are real completed OANDA D1
candles (get_bars filters pending candles); fills are simulated at the signal
bar's close into data/fx_shadow_ledger.jsonl with paper=true. This is the
ADR-0009 shadow registry — order flow is only granted at the shadow->live
boundary with human signoff. It must not run in the same venue book as the
daily runner (fx_runner closes anything not in ITS target).

Universe: 16 instruments (7 majors + 9 liquid crosses) for evidence velocity
— candidates select from the whole book; c08 only picks the 6 COT-mapped
majors (crosses and unmapped pairs are honestly skipped by the candidate
itself). The gym walkforward verification ran on the 7-major candle cache;
the ledger is per-symbol, so that subset remains sliceable for the
head-to-head. No orders are placed, so no account instrument-enabling is
needed; symbols OANDA won't price simply never enter ctx.

FIRE LOG: every faded symbol on every processed bar is appended to
data/fx_shadow_fires.jsonl (ts, symbol, fade_depth, selected). The
non-selected fires are the off-policy counterfactuals the value head needs —
"what would the third-ranked fade have done" is otherwise unobservable.

One deviation from the gym, conservative: spread cost 0.0001 x units is
subtracted on every exit (the gym's target branch added it back — sign bug
there; not replicated). Shadow PnL is therefore slightly pessimistic vs the
gym baseline.

Per-symbol asof guard: each symbol's newest completed bar is processed at
most once (state.last_bar), so reruns on the same day are idempotent.

State:   data/fx_shadow_state.json   (sole writer: fx_shadow)
Fills:   data/fx_shadow_ledger.jsonl (append-only, deduped, paper=true)
Fires:   data/fx_shadow_fires.jsonl  (append-only, counterfactual log)
Usage:   python3 -m strategies.fx_shadow [--apply]   (default: dry)
"""

import importlib.util
import bisect
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from exchange.oanda import OandaExchange  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent
STATE = PROJECT / "data" / "fx_shadow_state.json"
LEDGER = PROJECT / "data" / "fx_shadow_ledger.jsonl"
FIRES = PROJECT / "data" / "fx_shadow_fires.jsonl"
GYM_CANDS = PROJECT / "data" / "signal_gym" / "candidates"
EXOG = PROJECT / "data" / "exog_cache.json"
SHADOW_CANDIDATE = "c08_mr_fade_cot"  # gym survivor 2026-08-31; --candidate overrides

FADE = -0.015       # c04 fade reference (fire-log context only)
TOP_N = 2           # gym: stable top-2 by weight
NOTIONAL = 10_000   # gym uniform risk: $10k per position
ATR_STOP, ATR_TP, HOLD = 1.5, 2.5, 14
SPREAD = 0.0001

# 7 majors (gym-verified subset) + 9 liquid crosses for evidence velocity
FX_SHADOW_UNIVERSE = [
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "GBP_JPY", "AUD_USD", "USD_CAD",
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_CAD",
    "AUD_JPY", "AUD_NZD", "NZD_JPY", "NZD_USD",
]


def _fill_key(f):
    return (str(f.get("ts")), f.get("symbol"), f.get("side"), f.get("reason"))


def _append_ledger(fills):
    if not fills:
        return
    seen = set()
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    seen.add(_fill_key(json.loads(line)))
                except Exception:
                    pass
    with LEDGER.open("a") as f:
        for fill in fills:
            if _fill_key(fill) in seen:
                continue
            seen.add(_fill_key(fill))
            f.write(json.dumps(fill, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _ma20(closes, i):
    """Gym convention: mean of the 20 closes BEFORE bar i."""
    if i < 20:
        return None
    return sum(closes[i - 20:i]) / 20.0


def _atr14(bars, i):
    """Gym convention: 14 TRs from the 15 bars BEFORE bar i."""
    if i < 15:
        return None
    trs = []
    for j in range(i - 14, i + 1):
        h, l, pc = bars[j].high, bars[j].low, bars[j - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


class ShadowCtx:
    """Mirror of scripts/signal_gym.Ctx for the methods gym candidates use
    (close/close_n/ma/atr/mom/exog) — keep in sync with the gym. Dates are
    epoch-second ints like the gym's candle cache."""

    def __init__(self, series, dates, i, symbols, exog_series=None):
        self.series = series
        self.dates = dates
        self.i = i
        self.symbols = symbols
        self.date = dates[i]
        self.exog_series = exog_series or {}

    def _px(self, sym, j):
        return self.series.get(sym, {}).get(self.dates[j])

    def close(self, sym):
        px = self._px(sym, self.i)
        return px[3] if px else None

    def close_n(self, sym, k):
        j = self.i - k
        px = self._px(sym, j) if j >= 0 else None
        return px[3] if px else None

    def ma(self, sym, n):
        vals = [self._px(sym, j) for j in range(max(0, self.i - n), self.i)]
        vals = [x[3] for x in vals if x]
        return sum(vals) / len(vals) if len(vals) == n else None

    def atr(self, sym, n):
        vals = [self._px(sym, j) for j in range(max(0, self.i - n - 1), self.i)]
        if len(vals) < 2:
            return None
        trs = [max(vals[k][1] - vals[k][2], abs(vals[k][1] - vals[k - 1][3]),
                   abs(vals[k][2] - vals[k - 1][3])) for k in range(1, len(vals))]
        return sum(trs) / len(trs)

    def mom(self, sym, k):
        c, ck = self.close(sym), self.close_n(sym, k)
        return c / ck - 1 if c and ck else None

    def exog(self, key):
        """Point-in-time: latest observation with a 3-day publication lag
        (COT Tuesday-position reports go public Friday) — mirrors gym.
        Sorted-key index cached on the series dict for bisect lookup."""
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


def load_candidate(name):
    path = GYM_CANDS / f"{name}.py"
    if not path.exists():
        raise SystemExit(f"[fx-sh] candidate not found: {path}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "NAME") and hasattr(mod, "entry"), f"{path.name}: needs NAME and entry(ctx)"
    return mod


def _append_fires(fires):
    if not fires:
        return
    seen = set()
    if FIRES.exists():
        for line in FIRES.read_text().splitlines():
            if line.strip():
                try:
                    f = json.loads(line)
                    seen.add((str(f.get("ts")), f.get("symbol")))
                except Exception:
                    pass
    with FIRES.open("a") as f:
        for fire in fires:
            key = (str(fire.get("ts")), fire.get("symbol"))
            if key in seen:
                continue
            seen.add(key)
            f.write(json.dumps(fire, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run(apply=False):
    cand_name = SHADOW_CANDIDATE
    if "--candidate" in sys.argv:
        cand_name = sys.argv[sys.argv.index("--candidate") + 1]
    cand = load_candidate(cand_name)
    exog = json.load(open(EXOG)) if EXOG.exists() else {}

    ex = OandaExchange()
    if not ex.connect():
        raise SystemExit("[fx-sh] connect failed — check config/oanda_keys.json")
    print(f"[fx-sh] shadow lane (gym candidate: {cand.NAME}, paper) — book: {len(FX_SHADOW_UNIVERSE)} instruments")
    symbols = FX_SHADOW_UNIVERSE

    state = json.loads(STATE.read_text()) if STATE.exists() else {"positions": {}, "last_bar": {}}
    book, last_bar = state.setdefault("positions", {}), state.setdefault("last_bar", {})
    fills, fires = [], []

    # newest completed bar per symbol (per-symbol asof guard)
    ctx = {}
    for sym in symbols:
        bars = ex.get_bars(sym, "1d", 60)
        if len(bars) < 22:
            continue
        i = len(bars) - 1
        if last_bar.get(sym) == bars[i].timestamp:
            continue  # asof guard: already processed this bar
        ctx[sym] = (bars, i)

    # 1. exits on open shadow positions (gym order: stop, then target, then hold)
    for sym in list(book):
        if sym not in ctx:
            continue
        bars, i = ctx[sym]
        pos = book[sym]
        pos["bars_seen"] = pos.get("bars_seen", 0) + 1
        px = bars[i]
        exit_px, reason = None, None
        if px.low <= pos["sl"]:
            exit_px, reason = pos["sl"], "mr-fade-exit-stop"
        elif px.high >= pos["tp"]:
            exit_px, reason = pos["tp"], "mr-fade-exit-target"
        elif pos["bars_seen"] >= HOLD:
            exit_px, reason = px.close, "mr-fade-exit-hold"
        if exit_px is not None:
            pnl = (exit_px - pos["entry"]) * pos["units"] - SPREAD * pos["units"]
            fills.append({"ts": px.timestamp, "symbol": sym, "side": "SELL",
                          "quantity": pos["units"], "price": round(exit_px, 5),
                          "order_id": None, "paper": True, "reason": reason,
                          "pnl": round(pnl, 2)})
            print(f"[fx-sh] EXIT  {sym} ({reason}) @ {exit_px:.5f} pnl {pnl:+.2f}")
            del book[sym]

    # 2. entries: candidate-driven picks (gym ctx semantics), stable top-2
    series = {sym: {b.timestamp: (b.open, b.high, b.low, b.close) for b in bars}
              for sym, (bars, _) in ctx.items()}
    alldates = sorted({ts for s in series.values() for ts in s})
    picks = {}
    by_date = {}
    for sym in symbols:
        if sym not in ctx or sym in book:
            continue
        by_date.setdefault(ctx[sym][0][ctx[sym][1]].timestamp, []).append(sym)
    for d, syms in sorted(by_date.items()):
        sctx = ShadowCtx(series, alldates, alldates.index(d), syms, exog_series=exog)
        try:
            p = cand.entry(sctx)
            assert isinstance(p, dict)
        except Exception as e:
            print(f"[fx-sh] ! candidate entry failed on {d}: {e}")
            continue
        picks.update(p)
    ordered = [sym for sym, _w in sorted(picks.items(), key=lambda kv: -kv[1])]
    for sym in ordered:  # fire log: every candidate signal (counterfactuals included)
        bars, i = ctx[sym]
        closes = [b.close for b in bars]
        ma = _ma20(closes, i)
        if ma and closes[i]:
            fires.append({"ts": bars[i].timestamp, "symbol": sym,
                          "fade_depth": round(closes[i] / ma - 1, 5), "selected": False})
    for sym in ordered[:TOP_N]:
        bars, i = ctx[sym]
        px = bars[i]
        atr = _atr14(bars, i)
        if not atr or atr <= 0 or px.close <= 0:
            continue
        units = int(NOTIONAL / px.close)
        book[sym] = {"units": units, "entry": px.close, "sl": px.close - ATR_STOP * atr,
                     "tp": px.close + ATR_TP * atr, "entry_ts": px.timestamp, "bars_seen": 0}
        fills.append({"ts": px.timestamp, "symbol": sym, "side": "BUY",
                      "quantity": units, "price": round(px.close, 5), "order_id": None,
                      "paper": True, "reason": "mr-fade-entry", "sl": book[sym]["sl"],
                      "tp": book[sym]["tp"]})
        for fire in fires:
            if fire["symbol"] == sym and fire["ts"] == px.timestamp:
                fire["selected"] = True
        print(f"[fx-sh] ENTRY {sym} {units}u @ {px.close:.5f} "
              f"SL {book[sym]['sl']:.5f} TP {book[sym]['tp']:.5f}")
    if len(ordered) > TOP_N:
        print(f"[fx-sh] {len(ordered)} candidate signals, top-{TOP_N} selected; "
              f"{len(ordered) - TOP_N} logged as counterfactual fires")

    for sym, (bars, i) in ctx.items():
        last_bar[sym] = bars[i].timestamp

    # 3. persist (dry runs write nothing — the evidence trail only ever
    #    describes actually-processed bars; state file is atomic)
    if apply:
        _append_fires(fires)
        _append_ledger(fills)
    if apply:
        newest_ts = max((bars[i].timestamp for bars, i in ctx.values()),
                        default=state.get("updated"))
        tmp = STATE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"positions": book, "last_bar": last_bar,
                                   "updated": newest_ts}, indent=2))
        os.replace(tmp, STATE)
        print(f"[fx-sh] state written ({len(book)} shadow positions)")
    else:
        print("[fx-sh] dry run — no state write")

    # 4. running stats (heuristic paper accounting, labeled)
    pnls = []
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                try:
                    p = json.loads(line).get("pnl")
                    if p is not None:
                        pnls.append(float(p))
                except Exception:
                    pass
    if pnls:
        wins = [p for p in pnls if p > 0]
        gl = abs(sum(p for p in pnls if p <= 0))
        pf = (sum(wins) / gl) if gl else float("inf")
        print(f"[fx-sh] shadow book so far (paper, spread-adj): n={len(pnls)} "
              f"WR {len(wins) / len(pnls):.1%} PF {pf:.2f} cum {sum(pnls):+,.2f}")


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)
