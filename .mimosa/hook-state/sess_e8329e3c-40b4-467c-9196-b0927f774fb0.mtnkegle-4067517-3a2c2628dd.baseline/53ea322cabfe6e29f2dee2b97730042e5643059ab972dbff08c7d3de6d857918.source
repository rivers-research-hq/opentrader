#!/usr/bin/env python3
"""ADIR Training Data Builder — re-runs ADIR on historical market context
to generate training data aligned with the current debate engine.

Architecture:
  reflection_log.json  ─┐
  cycle_*.json history ─┤→ adir_data_builder → ADIR → training_data_adir.jsonl
  llama-server :5809   ─┘

Each example calls ADIR's independent debate (Bull + Bear + Risk agents)
on the original market data, producing fresh training signals that match
the current debate mode rather than stale fast_debate answers.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mot.agents.adir_debate import AdirDebateEngine, AdirConfig
from mot.agents.debate import DebateResult

logger = logging.getLogger("opentrader.adir_data_builder")

MAX_EXAMPLES = 200  # sample from all available cycle data
MIN_EXAMPLES = 32


def build_adir_training_data(
    state_dir: str,
    llama_host: str = "http://127.0.0.1:5802",
    output_path: str = None,
    max_examples: int = MAX_EXAMPLES,
    model: str = "ptolemy-s0",
) -> Tuple[str, int]:
    """Build training data by running ADIR on sampled historical cycle data."""
    state_path = Path(state_dir)
    history_dir = state_path / "history"

    if not history_dir.exists():
        logger.error("No history directory found at %s", history_dir)
        return "", 0

    # Load all cycle files, sorted numerically
    def _cycle_num(f):
        try: return int(f.stem.split('_')[1])
        except: return 0
    all_cycles = sorted(history_dir.glob("cycle_*.json"), key=_cycle_num)

    if len(all_cycles) < MIN_EXAMPLES:
        logger.warning(f"Only {len(all_cycles)} cycles, need {MIN_EXAMPLES}+")
        return "", 0

    # Sample evenly across the full date range for diverse market conditions
    stride = max(1, len(all_cycles) // max_examples)
    sampled = all_cycles[::stride][:max_examples]
    logger.info(f"Sampled {len(sampled)} cycles from {len(all_cycles)} total (stride={stride})")

    # Init ADIR engine
    print(f"Connecting to llama-server at {llama_host}...")
    engine = AdirDebateEngine(
        llama_host=llama_host,
        bull_model=model,
        bear_model=model,
        risk_model=model,
    )

    examples = []
    success = 0
    skipped = 0

    for i, fp in enumerate(sampled):
        try:
            cycle_data = json.loads(fp.read_text())
        except Exception:
            skipped += 1
            continue

        # Build context from cycle data directly
        ohlcv = _build_ohlcv_summary(cycle_data)
        portfolio = _build_portfolio_summary(cycle_data)
        regime = cycle_data.get("regime", "unknown")
        fear_greed = _extract_fear_greed(cycle_data)
        symbol_regimes = cycle_data.get("symbol_regimes", {})

        user_prompt = f"""Market Analysis Request:
OHLCV Data: {ohlcv}
Portfolio State: {portfolio}
Regime: {regime}
Fear & Greed Index: {fear_greed}
Symbol Regimes: {json.dumps(symbol_regimes) if symbol_regimes else "none"}"""

        print(f"[{i+1}/{len(sampled)}] cycle #{cycle_data.get('cycle','?')} "
              f"(ts={cycle_data.get('timestamp','')[:16]})...", end=" ")

        try:
            result = engine.independent_debate(
                ohlcv_json=ohlcv,
                portfolio_json=portfolio,
                regime_json=regime,
                news_json=fear_greed,
                extra_context=f"Symbol regimes: {json.dumps(symbol_regimes)}" if symbol_regimes else "",
            )

            conv = _build_sharegpt(
                result=result,
                user_prompt=user_prompt,
                entry=cycle_data,
                ohlcv=ohlcv,
                portfolio=portfolio,
                regime=fear_greed,  # pass F&G as regime string
            )

            examples.append({"conversations": conv})
            success += 1
            print(f"→ {result.action} (conf={result.confidence:.2f})")

        except Exception as e:
            print(f"✗ FAILED: {e}")
            skipped += 1
            continue

        time.sleep(0.3)  # rate limit

    if not examples:
        logger.warning("No training examples could be built.")
        return "", 0

    # Write output
    if output_path is None:
        train_dir = state_path / "training"
        train_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(train_dir / "training_data_adir.jsonl")
    else:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\n✓ Built {len(examples)} ADIR training examples ({success} success, {skipped} skipped)")
    print(f"  Output: {output_path}")
    return output_path, len(examples)


def _find_cycle(timestamp: str, history_map: Dict[str, dict]) -> Optional[dict]:
    """Find cycle data matching a reflection timestamp (fuzzy match)."""
    if timestamp in history_map:
        return history_map[timestamp]
    # Try prefix match
    prefix = timestamp[:16] if len(timestamp) >= 16 else timestamp
    for ts, data in sorted(history_map.items()):
        if ts.startswith(prefix):
            return data
    # Nearest match
    best = None
    best_diff = float("inf")
    for ts, data in history_map.items():
        try:
            diff = abs(
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
                .replace(tzinfo=timezone.utc)
                .timestamp()
                - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            if diff < best_diff:
                best_diff = diff
                best = data
        except Exception:
            continue
    return best if best_diff < 300 else None  # within 5 minutes


def _build_ohlcv_summary(cycle_data: dict) -> str:
    """Build OHLCV summary from cycle data."""
    prices = cycle_data.get("prices", {})
    metrics = cycle_data.get("metrics", {})
    portfolio_val = cycle_data.get("portfolio_value", 0)
    cycle_num = cycle_data.get("cycle", 0)

    parts = [f"Cycle #{cycle_num} | Portfolio: ${portfolio_val:,.2f}"]
    for sym, price in sorted(prices.items()):
        parts.append(f"{sym}: ${price:,.2f}")
    if metrics.get("fear_greed"):
        fg = metrics["fear_greed"]
        parts.append(f"F&G: {fg.get('value', '?')} ({fg.get('classification', '?')})")
    return " | ".join(parts)


def _build_portfolio_summary(cycle_data: dict) -> str:
    """Build portfolio summary from cycle data."""
    positions = cycle_data.get("positions", [])
    cash = cycle_data.get("cash", 0)
    val = cycle_data.get("portfolio_value", 0)

    if not positions:
        return f"Cash: ${cash:,.2f} | Total: ${val:,.2f} | No positions"

    pos_parts = []
    for p in positions:
        sym = p.get("symbol", "?")
        qty = p.get("quantity", 0)
        entry = p.get("entry_price") or 0
        current = p.get("current_price", entry)
        if isinstance(entry, (int, float)) and entry > 0:
            pnl_pct = ((current - entry) / entry * 100) if current else 0
        else:
            pnl_pct = 0
        pos_parts.append(f"{sym}: {qty:.6f} @ ${entry:.2f} (now ${current:.2f}, {pnl_pct:+.1f}%)")

    return f"Cash: ${cash:,.2f} | Total: ${val:,.2f} | {', '.join(pos_parts)}"


def _extract_fear_greed(cycle_data: dict) -> str:
    """Extract fear & greed from cycle metrics."""
    fg = cycle_data.get("metrics", {}).get("fear_greed", {})
    if fg:
        return f"{fg.get('value', '?')} ({fg.get('classification', '?')})"
    return "N/A"


def _build_sharegpt(
    result: DebateResult,
    user_prompt: str,
    entry: dict,
    ohlcv: str,
    portfolio: str,
    regime: str,
) -> List[dict]:
    """Build a ShareGPT conversation from ADIR output."""
    system = (
        "You are a trading agent operating an adversarial debate engine (ADIR). "
        "You analyze market data through independent Bull and Bear perspectives, "
        "then synthesize a final trading decision with Bayesian evidence scoring. "
        "Output format: Action: BUY/SELL/HOLD. Confidence: X.XX. Reason: explanation."
    )

    # Build rich assistant response from ADIR output
    bull_vote = getattr(result, 'bull_vote', None)
    bear_vote = getattr(result, 'bear_vote', None)
    risk = getattr(result, 'risk_verdict', {}) or {}
    evq_data = risk.get("evidence_quality", {}) or {}
    evq_bull = evq_data.get("bull", 0.0) or 0.0
    evq_bear = evq_data.get("bear", 0.0) or 0.0

    if bull_vote and bear_vote:
        assistant = (
            f"Action: {result.action}. Confidence: {result.confidence:.2f}. "
            f"Bull: {bull_vote.action} ({bull_vote.confidence:.0%}, evq={evq_bull:.2f}) | "
            f"Bear: {bear_vote.action} ({bear_vote.confidence:.0%}, evq={evq_bear:.2f}). "
            f"Risk: {risk.get('verdict',result.action)} ({risk.get('confidence',result.confidence):.0%}). "
            f"Reason: {result.reason}"
        )
    else:
        assistant = f"Action: {result.action}. Confidence: {result.confidence:.2f}. Reason: {result.reason}"

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
        {"role": "assistant", "content": assistant},
    ]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="/home/mrc/opentrader/data")
    ap.add_argument("--llama-host", default="http://127.0.0.1:5802")
    ap.add_argument("--output")
    ap.add_argument("--max-examples", type=int, default=200, help="Number of cycles to sample (default: 200)")
    ap.add_argument("--model", default="ptolemy-s0", help="Model alias for llama-server")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    build_adir_training_data(
        state_dir=args.state_dir,
        llama_host=args.llama_host,
        output_path=args.output,
        max_examples=args.max_examples,
        model=args.model,
    )
