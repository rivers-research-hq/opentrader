#!/usr/bin/env python3
"""Live paper shadow of the best rule-based config, running alongside the LLM
harness for a live A/B comparison.

Each cycle it fetches fresh daily OHLCV (yfinance), applies the setup from
setup_search/best.json incrementally (exit ladder then entries), and persists
its own paper state + equity curve to data/shadow_aab/. Trades are long-only,
$0.35/side fees — identical cost model to the harness.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from setup_search.core import FEE_PER_SIDE, clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align
from setup_search.engine import _features, _score_at

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "shadow_aab"
OUT.mkdir(parents=True, exist_ok=True)

SYMS = [
    "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "GOOGL", "META", "JPM",
    "XOM", "JNJ", "PG", "KO", "DIS", "CSCO", "WMT", "NFLX",
]

START_CASH = 500.0


def _load_state():
    p = OUT / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"cash": START_CASH, "positions": {}, "equity": [], "trades": [], "last_date": None}


def _save_state(s):
    tmp = OUT / "state.json.tmp"
    tmp.write_text(json.dumps(s, indent=1))
    tmp.replace(OUT / "state.json")


def _feed(s, date, sym, side, qty, price, reason):
    line = {
        "ts": time.time(),
        "date": str(date.date()) if hasattr(date, "date") else str(date),
        "sym": sym,
        "side": side,
        "qty": round(qty, 6),
        "price": round(price, 4),
        "reason": reason,
        "equity": round(s["cash"] + sum(
            p["qty"] * p["last"] for p in s["positions"].values()), 2),
    }
    with open(OUT / "feed.jsonl", "a") as f:
        f.write(json.dumps(line) + "\n")


def tick(cfg, state, closes, highs, lows, date):
    syms = sorted(closes.keys())
    feat = _features(closes, highs, lows, vols, cfg)

    spy = closes.get(REGIME_SYM)
    regime = None
    if cfg["regime_filter"] and spy is not None:
        regime = bool((spy > spy.rolling(int(cfg["regime_window"]), min_periods=10).mean()).iloc[-1])

    last = closes[syms[0]].index[-1]
    scores = _score_at(
        {s: feat[s].iloc[-1] for s in syms}, cfg, {s: 0.0 for s in syms}
    )
    close_t = {s: float(closes[s].iloc[-1]) for s in syms}
    hi_t = {s: float(highs[s].iloc[-1]) for s in syms}
    lo_t = {s: float(lows[s].iloc[-1]) for s in syms}

    for s in list(state["positions"].keys()):
        p = state["positions"][s]
        if s not in close_t:
            continue
        p["bars"] += 1
        p["last"] = close_t[s]
        entry = p["entry"]
        exit_price = None
        reason = None
        if hi_t[s] >= entry * (1 + cfg["tp"]):
            exit_price = entry * (1 + cfg["tp"]); reason = "tp"
        elif lo_t[s] <= entry * (1 - cfg["sl"]):
            exit_price = entry * (1 - cfg["sl"]); reason = "sl"
        elif cfg["trailing_pct"] > 0:
            p["peak"] = max(p["peak"], hi_t[s])
            trail = p["peak"] * (1 - cfg["trailing_pct"])
            if lo_t[s] <= trail:
                exit_price = trail; reason = "trail"
        if exit_price is None and p["bars"] >= cfg["max_hold"]:
            exit_price = close_t[s]; reason = "max_hold"
        if exit_price is None and float(scores.get(s, 0.0)) < cfg["sell_thresh"]:
            exit_price = close_t[s]; reason = "signal"
        if exit_price is not None:
            proceeds = p["qty"] * exit_price - FEE_PER_SIDE
            state["cash"] += proceeds
            pnl = proceeds - p["cost"]
            state["trades"].append({
                "sym": s, "entry": entry, "exit": exit_price,
                "pnl": round(pnl, 4), "pnl_pct": round(pnl / p["cost"], 4),
                "bars": p["bars"], "reason": reason, "date": str(last.date()),
            })
            _feed(state, last, s, "SELL", p["qty"], exit_price, reason)
            del state["positions"][s]

    equity = state["cash"] + sum(p["qty"] * close_t[s] for s, p in state["positions"].items())
    cands = []
    for s in syms:
        if s in state["positions"] or s == REGIME_SYM:
            continue
        sc = float(scores.get(s, -99))
        if sc < cfg["buy_thresh"] or close_t[s] <= 0:
            continue
        if regime is not None and not regime:
            continue
        cands.append((s, sc))
    cands.sort(key=lambda x: -x[1])

    for s, sc in cands:
        if len(state["positions"]) >= cfg["max_positions"]:
            break
        notional = cfg["risk_pct"] * equity
        if notional < cfg["min_notional"]:
            continue
        exposure = sum(p["qty"] * close_t[s] for s, p in state["positions"].items())
        if exposure / max(equity, 1) + notional / max(equity, 1) > cfg["max_exposure"]:
            continue
        if notional + FEE_PER_SIDE > state["cash"]:
            notional = max(0.0, state["cash"] - FEE_PER_SIDE)
            if notional < cfg["min_notional"]:
                continue
        qty = notional / close_t[s]
        cost = qty * close_t[s] + FEE_PER_SIDE
        state["cash"] -= cost
        state["positions"][s] = {
            "qty": qty, "entry": close_t[s], "cost": cost,
            "peak": close_t[s], "bars": 0, "last": close_t[s],
        }
        _feed(state, last, s, "BUY", qty, close_t[s], "signal")

    equity = state["cash"] + sum(p["qty"] * close_t[s] for s, p in state["positions"].items())
    state["equity"].append({"date": str(last.date()), "equity": round(equity, 2)})
    state["last_date"] = str(last.date())
    state["equity"] = state["equity"][-2000:]
    state["trades"] = state["trades"][-500:]
    _save_state(state)
    return equity, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=1800)
    ap.add_argument("--config", default=str(PROJECT / "data" / "setup_search" / "best.json"))
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cfg = clamp_config(json.loads(Path(args.config).read_text()).get("config", {}))
    state = _load_state()
    data = load_ohlcv("1y")
    syms = SYMS + [REGIME_SYM]
    al = align(data, syms)
    closes, highs, lows, _ = al
    print(f"[shadow] cfg loaded; {len(closes)} symbols; interval={args.interval}s")

    while True:
        try:
            data = load_ohlcv("1y")
            al = align(data, SYMS + [REGIME_SYM])
            closes, highs, lows, _ = al
            date = next(iter(closes.values())).index[-1]
            if state.get("last_date") == str(date.date()):
                if args.once:
                    break
                time.sleep(args.interval)
                continue
            eq, d = tick(cfg, state, closes, highs, lows, date)
            print(f"[shadow] {str(d.date())} equity=${eq:.2f} "
                  f"positions={len(state['positions'])} "
                  f"trades={len(state['trades'])} cash=${state['cash']:.2f}")
        except Exception as e:
            print(f"[shadow] cycle error: {e}")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
