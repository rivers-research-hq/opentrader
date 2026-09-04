#!/usr/bin/env python3
"""A/B Debate Test — replay historical cycles through both debate paths.

Usage:
    python3 tools/ab_debate_test.py [--cycles N] [--symbols BTC,ETH,SOL]

This replays the most recent N cycles through BOTH the existing fast_debate()
and the new ADIR independent_debate(), then compares:
  - Action agreement rate
  - Confidence distributions
  - Bull/Bear spread (genuine disagreement)
  - Latency
  - Position sizing differences
"""

import json
import logging
import os
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List

# Add opentrader to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mot.agents.debate import DebateEngine
from mot.agents.adir_debate import AdirDebateEngine, AdirConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("ab_test")

HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "history")
LLAMA_HOST = "http://127.0.0.1:5802"


def load_cycles(n: int = 20) -> List[dict]:
    """Load the most recent N cycles from history."""
    files = sorted(
        [f for f in os.listdir(HISTORY_DIR) if f.startswith("cycle_") and f.endswith(".json")],
        key=lambda f: int(f.replace("cycle_", "").replace(".json", "")),
        reverse=True,
    )
    cycles = []
    for f in files[:n]:
        path = os.path.join(HISTORY_DIR, f)
        try:
            with open(path) as fh:
                cycles.append(json.load(fh))
        except Exception as e:
            logger.warning(f"Failed to load {f}: {e}")
    # Sort by cycle number ascending
    cycles.sort(key=lambda c: c.get("cycle", 0))
    return cycles


def build_context_from_cycle(cycle: dict, symbol: str,
                              macro_data: dict = None) -> Dict[str, str]:
    """Reconstruct debate context from cycle JSON data.

    Returns a dict with keys matching the debate engine's expected inputs:
    ohlcv_json, portfolio_json, regime_json, economics_json, news_json.
    """
    prices = cycle.get("prices", {})
    symbol_regimes = cycle.get("symbol_regimes", {})
    positions = cycle.get("positions", [])
    cash = cycle.get("cash", 0)
    portfolio_value = cycle.get("portfolio_value", 0)
    metrics = cycle.get("metrics", {})

    current_price = float(prices.get(symbol, 0))
    regime_data = symbol_regimes.get(symbol, {})

    # ── OHLCV: reconstruct from available data ──
    ohlcv = {
        "symbol": symbol,
        "bars": [{"close": current_price}],  # Minimal: only current price available
    }

    # ── Portfolio ──
    pos_dict = {}
    for p in positions:
        pos_dict[p.get("symbol", "")] = float(p.get("quantity", 0))

    # Also include current symbol's position from the positions list
    # Recalculate portfolio to match cycle state
    portfolio = {
        "total_value": float(portfolio_value),
        "cash": float(cash),
        "positions": pos_dict,
        "entry_price": 0.0,  # Not available per-symbol in cycle
    }

    # ── Regime ──
    regime = {
        "regime": regime_data.get("regime", "unknown"),
        "confidence": float(regime_data.get("confidence", 0.5)),
        "thesis": regime_data.get("thesis", ""),
    }

    # ── Economics (macro) ──
    economics = macro_data or {}

    # ── News / Sentiment ──
    fear_greed = metrics.get("fear_greed", {})
    if isinstance(fear_greed, dict):
        fg_val = int(fear_greed.get("value", 50))
        fg_class = str(fear_greed.get("classification", "Neutral"))
    else:
        fg_val = 50
        fg_class = "Neutral"

    news = {
        "sources": {
            "fear_greed": {"value": fg_val, "classification": fg_class},
            "coingecko_global": {
                "total_market_cap_usd": 2.5e12,
                "market_cap_change_24h_pct": 0.0,
                "btc_dominance_pct": 55.0,
            },
            "btc_stats": {
                "price_usd": current_price if "BTC" in symbol else 0,
                "price_change_24h_pct": 0.0,
                "price_change_7d_pct": 0.0,
                "ath_usd": 109000,
                "ath_change_pct": -40.0,
            },
            "coingecko_trending": {"top_trending": []},
        }
    }

    return {
        "ohlcv_json": json.dumps(ohlcv),
        "portfolio_json": json.dumps(portfolio),
        "regime_json": json.dumps(regime),
        "economics_json": json.dumps(economics),
        "news_json": json.dumps(news),
    }


def _normalize_action(action: str) -> str:
    """Normalize action string for comparison."""
    return str(action).upper().strip()


def run_ab_on_cycle(cycle: dict,
                     fast_engine: DebateEngine,
                     adir_engine: AdirDebateEngine,
                     symbols: List[str]) -> List[dict]:
    """Run both debate engines on each symbol in a cycle."""
    results = []
    context_inputs = build_context_from_cycle(cycle, symbols[0])  # Base template

    for sym in symbols:
        ctx = build_context_from_cycle(cycle, sym)
        try:
            # ── Fast Debate ──
            t0 = time.time()
            fast_result = fast_engine.fast_debate(
                ohlcv_json=ctx["ohlcv_json"],
                portfolio_json=ctx["portfolio_json"],
                regime_json=ctx["regime_json"],
                economics_json=ctx["economics_json"],
                news_json=ctx["news_json"],
            )
            fast_time = (time.time() - t0) * 1000

            # ── ADIR Debate ──
            t0 = time.time()
            adir_result = adir_engine.independent_debate(
                ohlcv_json=ctx["ohlcv_json"],
                portfolio_json=ctx["portfolio_json"],
                regime_json=ctx["regime_json"],
                economics_json=ctx["economics_json"],
                news_json=ctx["news_json"],
            )
            adir_time = (time.time() - t0) * 1000

            # ── Compare ──
            action_agree = _normalize_action(fast_result.action) == _normalize_action(adir_result.action)
            conf_delta = abs(fast_result.confidence - adir_result.confidence)

            fast_spread = abs(fast_result.bull_vote.confidence - fast_result.bear_vote.confidence)
            adir_spread = abs(adir_result.bull_vote.confidence - adir_result.bear_vote.confidence)

            result = {
                "cycle": cycle.get("cycle", 0),
                "symbol": sym,
                "current_price": cycle.get("prices", {}).get(sym, 0),
                "fast": {
                    "action": fast_result.action,
                    "confidence": fast_result.confidence,
                    "position_pct": fast_result.position_pct,
                    "reason": fast_result.reason,
                    "duration_ms": round(fast_time),
                    "bull_confidence": fast_result.bull_vote.confidence,
                    "bear_confidence": fast_result.bear_vote.confidence,
                    "bull_bear_spread": fast_spread,
                },
                "adir": {
                    "action": adir_result.action,
                    "confidence": adir_result.confidence,
                    "position_pct": adir_result.position_pct,
                    "reason": adir_result.reason,
                    "duration_ms": round(adir_time),
                    "bull_confidence": adir_result.bull_vote.confidence,
                    "bear_confidence": adir_result.bear_vote.confidence,
                    "bull_bear_spread": adir_spread,
                },
                "metrics": {
                    "action_agree": action_agree,
                    "confidence_delta": round(conf_delta, 4),
                    "position_delta": round(abs(fast_result.position_pct - adir_result.position_pct), 4),
                    "spread_improvement": round(adir_spread - fast_spread, 4),
                    "latency_ratio": round(adir_time / max(1, fast_time), 2),
                },
            }
            results.append(result)

            # Print per-symbol result
            agree_mark = "✓" if action_agree else "✗"
            spread_dir = "↑" if adir_spread > fast_spread else "↓"
            print(f"  {sym:10s} | {agree_mark} agree | "
                  f"Fast: {fast_result.action:4s} {fast_result.confidence:.0%} "
                  f"(Bull {fast_result.bull_vote.confidence:.0%}/{fast_result.bear_vote.confidence:.0%} "
                  f"spread={fast_spread:.0%}) | "
                  f"ADIR: {adir_result.action:4s} {adir_result.confidence:.0%} "
                  f"(Bull {adir_result.bull_vote.confidence:.0%}/{adir_result.bear_vote.confidence:.0%} "
                  f"spread={adir_spread:.0%} {spread_dir}) | "
                  f"{fast_time:6.0f}ms vs {adir_time:6.0f}ms")

        except Exception as e:
            logger.error(f"  {sym}: AB test error: {e}", exc_info=True)
            results.append({
                "cycle": cycle.get("cycle", 0),
                "symbol": sym,
                "error": str(e),
            })

    return results


def print_summary(all_results: List[dict]):
    """Print aggregate comparison report."""
    valid = [r for r in all_results if "metrics" in r]
    errors = [r for r in all_results if "error" in r]

    if not valid:
        print("\n⚠️  No valid results to summarize.")
        return

    n = len(valid)
    agreements = sum(1 for r in valid if r["metrics"]["action_agree"])
    agree_rate = agreements / n

    fast_confs = [r["fast"]["confidence"] for r in valid]
    adir_confs = [r["adir"]["confidence"] for r in valid]
    fast_spreads = [r["fast"]["bull_bear_spread"] for r in valid]
    adir_spreads = [r["adir"]["bull_bear_spread"] for r in valid]
    fast_times = [r["fast"]["duration_ms"] for r in valid]
    adir_times = [r["adir"]["duration_ms"] for r in valid]

    # Action distribution
    fast_actions = defaultdict(int)
    adir_actions = defaultdict(int)
    for r in valid:
        fast_actions[r["fast"]["action"]] += 1
        adir_actions[r["adir"]["action"]] += 1

    print("\n" + "=" * 70)
    print("  A/B DEBATE COMPARISON REPORT")
    print("=" * 70)
    print(f"  Total comparisons: {n}  |  Errors: {len(errors)}")
    print(f"  Symbols per cycle: {n // max(1, len(set(r['cycle'] for r in valid if 'cycle' in r)))}")
    print()

    print(f"  {'Metric':<30} {'Fast':>15} {'ADIR':>15} {'Delta':>10}")
    print(f"  {'─' * 30} {'─' * 15} {'─' * 15} {'─' * 10}")
    print(f"  {'Action Agreement Rate':<30} {'':>15} {'':>15} {agree_rate:>9.0%}")
    print(f"  {'Avg Confidence':<30} {sum(fast_confs)/n:>14.1%} {sum(adir_confs)/n:>14.1%} "
          f"{'+' if sum(adir_confs)/n > sum(fast_confs)/n else ''}"
          f"{(sum(adir_confs)/n - sum(fast_confs)/n):>9.1%}")
    print(f"  {'Avg Bull Confidence':<30} "
          f"{sum(r['fast']['bull_confidence'] for r in valid)/n:>14.1%} "
          f"{sum(r['adir']['bull_confidence'] for r in valid)/n:>14.1%} "
          f"{'+' if sum(r['adir']['bull_confidence'] for r in valid)/n > sum(r['fast']['bull_confidence'] for r in valid)/n else ''}"
          f"{(sum(r['adir']['bull_confidence'] for r in valid)/n - sum(r['fast']['bull_confidence'] for r in valid)/n):>9.1%}")
    print(f"  {'Avg Bear Confidence':<30} "
          f"{sum(r['fast']['bear_confidence'] for r in valid)/n:>14.1%} "
          f"{sum(r['adir']['bear_confidence'] for r in valid)/n:>14.1%} "
          f"{'+' if sum(r['adir']['bear_confidence'] for r in valid)/n > sum(r['fast']['bear_confidence'] for r in valid)/n else ''}"
          f"{(sum(r['adir']['bear_confidence'] for r in valid)/n - sum(r['fast']['bear_confidence'] for r in valid)/n):>9.1%}")
    print(f"  {'Avg Bull/Bear Spread':<30} {sum(fast_spreads)/n:>14.1%} {sum(adir_spreads)/n:>14.1%} "
          f"{'+' if sum(adir_spreads)/n > sum(fast_spreads)/n else ''}"
          f"{(sum(adir_spreads)/n - sum(fast_spreads)/n):>9.1%}")
    print(f"  {'Avg Duration (ms)':<30} {sum(fast_times)/n:>14.0f} {sum(adir_times)/n:>14.0f} "
          f"{sum(adir_times)/sum(fast_times):>9.1f}x")
    print()

    print(f"  Action Distribution:")
    print(f"    Fast:  {dict(fast_actions)}")
    print(f"    ADIR:  {dict(adir_actions)}")
    print()

    # Spread analysis
    improved_spreads = sum(1 for r in valid if r["metrics"]["spread_improvement"] > 0)
    print(f"  Spread improved in {improved_spreads}/{n} ({improved_spreads/n:.0%}) comparisons")
    print(f"  Avg spread improvement: {sum(r['metrics']['spread_improvement'] for r in valid)/n:+.1%}")

    # Confidence distribution
    print(f"\n  Confidence Distribution (buckets):")
    print(f"    {'Bucket':<15} {'Fast Count':>12} {'ADIR Count':>12}")
    for lo, hi in [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]:
        f_count = sum(1 for c in fast_confs if lo <= c < hi)
        a_count = sum(1 for c in adir_confs if lo <= c < hi)
        label = f"{hi:.0%}" if hi <= 1.0 else "100%"
        print(f"    {lo:.0%}-{label:<15} {f_count:>12} {a_count:>12}")

    # Top disagreements
    disagreements = [r for r in valid if not r["metrics"]["action_agree"]]
    if disagreements:
        print(f"\n  Disagreements ({len(disagreements)}):")
        for r in disagreements[:10]:
            print(f"    Cycle {r['cycle']} {r['symbol']:10s}: "
                  f"Fast→{r['fast']['action']:4s}({r['fast']['confidence']:.0%}) "
                  f"vs ADIR→{r['adir']['action']:4s}({r['adir']['confidence']:.0%})")
        if len(disagreements) > 10:
            print(f"    ... and {len(disagreements) - 10} more")

    print("=" * 70)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="A/B test debate engines on historical cycles")
    parser.add_argument("--cycles", type=int, default=20,
                        help="Number of historical cycles to replay (default: 20)")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT",
                        help="Comma-separated symbols (default: BTC/USDT,ETH/USDT,SOL/USDT)")
    parser.add_argument("--host", type=str, default=LLAMA_HOST,
                        help=f"llama-server host (default: {LLAMA_HOST})")
    parser.add_argument("--model", type=str, default="qwythos-9b-mtp",
                        help="Model name (default: qwythos-9b-mtp)")
    parser.add_argument("--gate-threshold", type=float, default=0.75,
                        help="ADIR confidence gate threshold (default: 0.75)")
    parser.add_argument("--json-out", type=str, default=None,
                        help="Write full results to JSON file")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]

    print(f"\n═══ A/B DEBATE TEST ═══")
    print(f"  Cycles: {args.cycles}  |  Symbols: {args.symbols}")
    print(f"  Host: {args.host}  |  Model: {args.model}")
    print(f"  ADIR gate threshold: {args.gate_threshold}")
    print()

    # Load cycles
    print("Loading cycles...")
    cycles = load_cycles(args.cycles)
    print(f"  Loaded {len(cycles)} cycles [{cycles[0].get('cycle', '?')} → {cycles[-1].get('cycle', '?')}]")

    # Initialize engines
    print(f"\nInitializing engines...")
    fast_engine = DebateEngine(
        llama_host=args.host,
        bull_model=args.model,
        bear_model=args.model,
        risk_model=args.model,
    )

    adir_config = AdirConfig(
        confidence_gate_threshold=args.gate_threshold,
        enable_confidence_gate=True,
        enable_toulmin_parsing=True,
    )
    adir_engine = AdirDebateEngine(
        llama_host=args.host,
        bull_model=args.model,
        bear_model=args.model,
        risk_model=args.model,
        config=adir_config,
    )
    adir_engine.set_parent_engine(fast_engine)  # reuse context builder + finetuned backend

    # Run A/B on each cycle
    all_results = []
    print(f"\nRunning A/B comparison on {len(cycles)} cycles × {len(symbols)} symbols...\n")

    for i, cycle in enumerate(cycles):
        cycle_num = cycle.get("cycle", 0)
        print(f"Cycle {cycle_num} ({i+1}/{len(cycles)}):")
        results = run_ab_on_cycle(cycle, fast_engine, adir_engine, symbols)
        all_results.extend(results)

    # Print summary
    print_summary(all_results)

    # Save JSON if requested
    if args.json_out:
        output = {
            "config": {
                "cycles": args.cycles,
                "symbols": symbols,
                "host": args.host,
                "model": args.model,
                "gate_threshold": args.gate_threshold,
            },
            "results": all_results,
            "summary": {
                "total_comparisons": len(all_results),
                "action_agreement_rate": sum(1 for r in all_results if r.get("metrics", {}).get("action_agree")) / max(1, len([r for r in all_results if "metrics" in r])),
            },
        }
        with open(args.json_out, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nFull results saved to {args.json_out}")


if __name__ == "__main__":
    main()
