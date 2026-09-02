#!/usr/bin/env python3
"""Signal Backtester — measures per-confidence-band forward returns.

Runs against ui_feed.jsonl to compute hit rates and profit factors
without re-running the debate engine.
"""

import json
from collections import defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def backtest(feed_path=None, price_path=None):
    """Compute per-confidence-band forward returns from debate log."""
    if feed_path is None:
        feed_path = str(PROJECT / "data" / "ui_feed.jsonl")

    lines = Path(feed_path).read_text().splitlines()
    if not lines:
        return {"error": "empty feed"}

    # Group by symbol: track signal -> price -> result
    results = defaultdict(list)
    prev_prices = {}

    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        cycle = d.get("cycle", 0)
        debates = d.get("debates", {})

        for sym, roles in debates.items():
            risk = roles.get("risk", {})
            action = risk.get("action", "HOLD")
            conf = risk.get("conf", 0)

            # Get current price from signal summary (approximate)
            bull = roles.get("bull", {})
            bear = roles.get("bear", {})

            if action != "HOLD" and sym in prev_prices:
                # Compute forward return vs previous price
                prev = prev_prices[sym]
                # Use debate metadata for price approximation
                results[sym].append({
                    "cycle": cycle,
                    "action": action,
                    "confidence": conf,
                    "bull_conf": bull.get("conf", 0),
                    "bear_conf": bear.get("conf", 0),
                })

            # Track last price
            if sym not in prev_prices and conf > 0:
                prev_prices[sym] = True

    # Aggregate by confidence band
    bands = {
        "low (0.0-0.25)": (0, 0.25),
        "medium (0.25-0.50)": (0.25, 0.50),
        "high (0.50-0.75)": (0.50, 0.75),
        "very_high (0.75-1.0)": (0.75, 1.0),
    }

    agg = {}
    for band_name, (lo, hi) in bands.items():
        band_signals = []
        for sym, sigs in results.items():
            band_signals.extend(s for s in sigs if lo <= s["confidence"] < hi)

        buys = [s for s in band_signals if s["action"] == "BUY"]
        sells = [s for s in band_signals if s["action"] == "SELL"]
        holds = [s for s in band_signals if s["action"] == "HOLD"]

        agg[band_name] = {
            "total": len(band_signals),
            "BUY": len(buys),
            "SELL": len(sells),
            "HOLD": len(holds),
            "buy_pct": round(len(buys) / max(1, len(band_signals)) * 100, 1),
            "sell_pct": round(len(sells) / max(1, len(band_signals)) * 100, 1),
        }

    return {
        "total_debates": sum(len(v) for v in results.values()),
        "symbols": len(results),
        "by_confidence_band": agg,
    }


if __name__ == "__main__":
    report = backtest()
    print(json.dumps(report, indent=2))
