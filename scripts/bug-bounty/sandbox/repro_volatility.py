#!/usr/bin/env python3
"""Verify: cycle-varying seed_offset breaks the volatility heuristic freeze."""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from exchange.alpaca_paper import AlpacaPaperExchange


def scout_volatility_fallback(exch, universe, cycle):
    scored = []
    for sym in universe:
        bars = exch.get_bars(sym, limit=20, seed_offset=cycle)
        if len(bars) >= 5:
            cp = [b.close for b in bars[-5:]]
            vol = (max(cp) - min(cp)) / cp[-1] if cp[-1] else 0
            scored.append((vol, sym))
    scored.sort(reverse=True)
    return scored


def main():
    from mot.tradable_universe import TRADABLE_UNIVERSE
    from mot.dynamic_discovery import refresh_from_exchange

    exch = AlpacaPaperExchange(initial_cash=100000.0)
    universe = refresh_from_exchange(exch, TRADABLE_UNIVERSE)
    crypto = [s for s in universe if "/" in s]
    stocks = [s for s in universe if "/" not in s]
    print(f"Universe: {len(universe)} ({len(crypto)} crypto, {len(stocks)} stock/ETF)")

    # Simulate 5 scout cycles
    cycles = [3, 6, 9, 12, 15]
    all_top6 = []
    for cycle in cycles:
        scored = scout_volatility_fallback(exch, universe, cycle)
        top6 = [s for _, s in scored[:6]]
        all_top6.append(top6)
        c_cnt = sum(1 for s in top6 if "/" in s)
        s_cnt = sum(1 for s in top6 if "/" not in s)
        print(f"  Cycle {cycle:>3d}: {c_cnt}C/{s_cnt}S  {top6}")

    # Freeze check
    unique = set(tuple(t) for t in all_top6)
    print(f"\nUnique top-6 sets: {len(unique)} / {len(cycles)}")
    if len(unique) >= len(cycles) * 0.5:
        print("PASS: Freeze broken — cycles produce varied picks.")
    else:
        print(f"WARN: Only {len(unique)} unique sets.")

    # Regression: seed_offset=0 should match seed_offset=0 (cached)
    print("\nRegression: old behavior with seed_offset=0")
    a = [s for _, s in scout_volatility_fallback(exch, universe, 0)[:6]]
    b = [s for _, s in scout_volatility_fallback(exch, universe, 0)[:6]]
    print(f"  Run a: {a}")
    print(f"  Run b: {b}")
    print(f"  Same: {a == b} (expected True — deterministic + cached)")


if __name__ == "__main__":
    if "PYTHONHASHSEED" not in os.environ:
        os.environ["PYTHONHASHSEED"] = "0"
    main()
