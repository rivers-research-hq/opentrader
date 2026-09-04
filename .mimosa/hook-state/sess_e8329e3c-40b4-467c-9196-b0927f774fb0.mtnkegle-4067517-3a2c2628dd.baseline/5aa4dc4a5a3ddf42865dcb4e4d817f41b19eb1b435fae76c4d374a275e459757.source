#!/usr/bin/env python3
"""DPO Training Data Builder — creates preference pairs from trade journal.

For each closed trade, constructs a (prompt, chosen, rejected) triplet:
  prompt  = market context + portfolio state at entry time
  chosen  = preferred response (profitable action or HOLD avoidance)
  rejected = dispreferred response (unprofitable action or missed opportunity)

Format: Unsloth/TRL DPO JSONL — {prompt, chosen, rejected} per line.
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.dpo_builder")

MIN_TRADES = 20


def _load_state(state_dir: Path) -> Optional[dict]:
    agent_path = state_dir / "agent_state.json"
    if not agent_path.exists():
        return None
    with open(agent_path) as f:
        return json.load(f)


def _build_market_prompt(state: dict, symbol: str) -> str:
    """Build a concise market-context prompt for a single symbol."""
    prices = state.get("prices", {})
    regime = state.get("regime", {})
    metrics = state.get("metrics", {})
    positions = state.get("positions", [])

    price_str = ", ".join(
        f"{s}: ${p:.2f}"
        for s, p in sorted(prices.items())
    ) if prices else "unknown"

    pos_str = "none"
    for p in positions:
        if isinstance(p, dict) and p.get("symbol") == symbol:
            qty = p.get("quantity", p.get("size", 0))
            ep = p.get("entry_price", 0)
            pos_str = f"{qty:.8f} {symbol} @ ${ep:.2f}"
            break

    lines = [
        f"Prices: {price_str}",
        f"Cycle: {state.get('cycle', '?')}",
        f"Portfolio: ${state.get('portfolio_value', 0):.2f} (cash: ${state.get('cash', 0):.2f})",
        f"Position: {pos_str}",
        f"Drawdown: {metrics.get('drawdown_pct', 0):.1f}%",
        f"Fear/Greed: {metrics.get('fear_greed', 'N/A')}",
    ]
    if regime:
        lines.append(f"Regime: {regime.get('regime', 'unknown')}")
    return "\n".join(lines)


def _format_response(symbol: str, action: str, confidence: float, reason: str) -> str:
    """Format an assistant response string."""
    lines = [
        f"SYMBOL: {symbol}",
        f"ACTION: {action.upper()}",
        f"CONFIDENCE: {confidence * 100:.0f}%",
        f"REASON: {reason}",
    ]
    return "\n".join(lines)


def _hold_response(symbol: str) -> str:
    return _format_response(
        symbol, "HOLD", 0.0,
        "No action — preserving capital in uncertain conditions."
    )


def _build_journal_prompt(trade: dict, paper_state: dict = None) -> str:
    """Build a minimal market prompt from journal entry data when cycle file is missing.

    Uses paper_state.json for current market context if available.
    """
    symbol = trade.get("symbol", "?")
    entry_price = trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    pnl_pct = trade.get("pnl_pct", 0)
    entry_cycle = trade.get("entry_cycle", 0)

    if paper_state:
        prices = paper_state.get("prices", {})
        portfolio = paper_state.get("portfolio_value", 0)
        cash = paper_state.get("cash", 0)
        regime = paper_state.get("regime", {})
        metrics = paper_state.get("metrics", {})
    else:
        prices = {}
        portfolio = 0
        cash = 0
        regime = {}
        metrics = {}

    price_str = ", ".join(
        f"{s}: ${p:.2f}"
        for s, p in sorted(prices.items())
    ) if prices else "unknown"

    lines = [
        f"Symbol: {symbol}",
        f"Entry Price: ${entry_price:.2f}",
        f"Exit Price: ${exit_price:.2f}",
        f"PnL: {pnl_pct:+.4%}",
        f"Entry Cycle: {entry_cycle}",
        f"Prices: {price_str}",
        f"Portfolio: ${portfolio:.2f} (cash: ${cash:.2f})",
        f"Drawdown: {metrics.get('drawdown_pct', 0):.1f}%",
        f"Regime: {regime.get('regime', 'unknown')}",
    ]
    return "\n".join(lines)


def build_dpo_dataset(
    state_dir: str,
    output_path: str = None,
    min_trades: int = MIN_TRADES,
) -> Tuple[str, int]:
    """Extract DPO preference pairs from trade journal + cycle history.

    Each pair comes from:
      - Prompt: market context at trade entry
      - Chosen: better decision (profitable action or HOLD avoidance)
      - Rejected: worse decision (unprofitable action or missed gain)

    Returns (output_path, num_pairs).
    """
    state_path = Path(state_dir)
    history_dir = state_path / "history"
    archive_dir = state_path / "history_archive_100k"
    agent_state = _load_state(state_path)
    paper_state = None
    paper_path = state_path / "paper_state.json"
    if paper_path.exists():
        try:
            paper_state = json.loads(paper_path.read_text())
        except Exception:
            pass

    if agent_state is None:
        logger.error("No agent_state.json found")
        return "", 0

    journal = agent_state.get("_trade_journal", [])
    if len(journal) < min_trades:
        logger.warning("Only %d trades in journal (need %d+)", len(journal), min_trades)
        return "", 0

    if output_path is None:
        output_dir = state_path / "training"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "dpo_training_data.jsonl")

    # Group trades by symbol for balanced sampling
    by_symbol: Dict[str, List[dict]] = {}
    for t in journal:
        sym = t.get("symbol", "?")
        if sym == "?":
            continue
        by_symbol.setdefault(sym, []).append(t)

    pairs = []
    cycle_cache: Dict[int, dict] = {}

    def _get_entry_state(entry_cycle: int) -> Optional[dict]:
        if entry_cycle is None:
            return None
        if entry_cycle in cycle_cache:
            return cycle_cache[entry_cycle]
        cycle_path = history_dir / f"cycle_{entry_cycle:04d}.json"
        if not cycle_path.exists():
            archive_path = archive_dir / f"cycle_{entry_cycle:04d}.json"
            if archive_path.exists():
                cycle_path = archive_path
            else:
                return None
        try:
            state = json.loads(cycle_path.read_text())
            cycle_cache[entry_cycle] = state
            return state
        except Exception:
            return None

    for sym, trades in by_symbol.items():
        profitable = [t for t in trades if t.get("pnl_pct", 0) > 0.001]
        unprofitable = [t for t in trades if t.get("pnl_pct", 0) < -0.001]

        # Limit per-symbol to keep dataset balanced
        max_per = 200
        profitable = profitable[-max_per:]
        unprofitable = unprofitable[-max_per:]

        for t in profitable:
            entry_cycle = t.get("entry_cycle")
            state = _get_entry_state(entry_cycle)
            if state is not None:
                prompt = _build_market_prompt(state, sym)
                action = "BUY"
                reason = t.get("exit_reason", "profitable trade")
                confidence = 0.5
                for sig in state.get("signals", []):
                    if sig.get("symbol") == sym and sig.get("action") in ("BUY", "SELL"):
                        confidence = sig.get("confidence", 0.5)
                        reason = sig.get("reason", reason)
                        break
            else:
                prompt = _build_journal_prompt(t, paper_state)
                action = "BUY"
                confidence = 0.5
                reason = t.get("exit_reason", "profitable trade")

            chosen = _format_response(sym, action, confidence, reason)
            rejected = _hold_response(sym)
            pairs.append({"prompt": prompt, "chosen": chosen, "rejected": rejected})

        for t in unprofitable:
            entry_cycle = t.get("entry_cycle")
            state = _get_entry_state(entry_cycle)
            if state is not None:
                prompt = _build_market_prompt(state, sym)
                action = "BUY"
                confidence = 0.5
                reason = t.get("exit_reason", "unprofitable trade")
                for sig in state.get("signals", []):
                    if sig.get("symbol") == sym and sig.get("action") in ("BUY", "SELL"):
                        confidence = sig.get("confidence", 0.5)
                        reason = sig.get("reason", reason)
                        break
            else:
                prompt = _build_journal_prompt(t, paper_state)
                action = "BUY"
                confidence = 0.5
                reason = t.get("exit_reason", "unprofitable trade")

            chosen = _hold_response(sym)
            rejected = _format_response(sym, action, confidence, reason)
            pairs.append({"prompt": prompt, "chosen": chosen, "rejected": rejected})

    pairs.sort(key=lambda p: p["prompt"])

    # Write JSONL
    with open(output_path, "w") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    logger.info(
        "DPO dataset: %d pairs (%d profitable, %d unprofitable) → %s",
        len(pairs),
        sum(1 for t in journal if t.get("pnl_pct", 0) > 0.001),
        sum(1 for t in journal if t.get("pnl_pct", 0) < -0.001),
        output_path,
    )
    return output_path, len(pairs)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build DPO preference pairs from trade journal")
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--output", default=None, help="Output JSONL path")
    parser.add_argument("--min-trades", type=int, default=MIN_TRADES, help="Minimum trades")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    state_dir = Path(args.state_dir)
    if not state_dir.is_absolute():
        state_dir = Path(__file__).resolve().parent.parent / args.state_dir

    out_path, count = build_dpo_dataset(
        str(state_dir),
        output_path=args.output,
        min_trades=args.min_trades,
    )
    if out_path:
        print(f"Wrote {count} DPO pairs to {out_path}")
    else:
        print("No DPO pairs generated.")
        sys.exit(1)


if __name__ == "__main__":
    main()
