#!/usr/bin/env python3
"""Per-symbol parameter optimization from closed trade history.

Reads the trade journal from paper_state, computes optimal stop-loss,
take-profit, position hold time, trailing stop, and Kelly fraction for
each symbol based on actual win/loss distributions.

Triggers every N cycles when enough trades have closed. Writes
data/optimal_params.json which RiskManager picks up automatically.
"""

import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("opentrader.param_opt")

MIN_TRADES = 5  # Per symbol to trigger optimization


@dataclass
class OptimalParams:
    """Per-symbol optimized risk parameters."""
    symbol: str
    stop_loss_pct: float       # Optimal SL based on losing trade exits
    take_profit_pct: float     # Optimal TP based on winning trade exits
    max_position_cycles: int    # Based on average trade duration × 3
    kelly_fraction: float       # Adjusted by actual win rate
    trailing_stop_pct: float    # 0.5 × average retrace from high
    trailing_stop_activation: float  # 0.5 × average profitable move
    position_stop_pct: float    # 1.5 × worst drawdown survived
    win_rate: float = 0.5       # Historical win rate
    sample_size: int = 0        # Number of trades analyzed
    avg_hold_cycles: float = 50 # Average trade duration


def analyze_trades(trades: List[dict]) -> Optional[OptimalParams]:
    """Compute optimal parameters from a symbol's trade history."""
    if len(trades) < MIN_TRADES:
        return None

    wins = [t for t in trades if t.get("pnl_pct", 0) > 0.0001]
    losses = [t for t in trades if t.get("pnl_pct", 0) < -0.0001]
    be = [t for t in trades if abs(t.get("pnl_pct", 0)) <= 0.0001]
    valid = wins + losses

    if len(wins) < 2 or len(losses) < 1 or len(valid) < MIN_TRADES:
        return None

    symbol = trades[0].get("symbol", "?")

    # Win/loss stats
    win_rate = len(wins) / max(len(valid), 1)
    avg_win = sum(abs(t.get("pnl_pct", 0)) for t in wins) / len(wins)
    avg_loss = sum(abs(t.get("pnl_pct", 0)) for t in losses) / len(losses)
    wl_ratio = avg_win / max(avg_loss, 0.0001)

    # Optimal SL: 75th percentile of losses, capped at 2× average loss
    loss_pcts = sorted(abs(t.get("pnl_pct", 0)) for t in losses)
    sl_pct = loss_pcts[int(len(loss_pcts) * 0.75)] if loss_pcts else avg_loss
    sl_pct = min(sl_pct, avg_loss * 2.0)
    sl_pct = max(sl_pct, 0.01)   # Floor: 1%

    # Optimal TP: median of wins, scaled by win/loss ratio
    win_pcts = sorted(t.get("pnl_pct", 0) for t in wins)
    tp_pct = win_pcts[len(win_pcts) // 2] if win_pcts else avg_win
    tp_pct = max(tp_pct, sl_pct * 1.5)    # At least 1.5× SL
    tp_pct = min(tp_pct, sl_pct * 4.0)    # Cap at 4× SL

    # Hold time: average duration × 3, capped
    durations = [t.get("duration_cycles", 50) for t in trades if t.get("duration_cycles")]
    avg_hold = sum(durations) / len(durations) if durations else 50
    max_cycles = min(int(avg_hold * 3), 2000)

    # Kelly fraction: adjusted by win rate
    base_kelly = 0.35
    if wl_ratio > 0:
        raw_kelly = win_rate - ((1 - win_rate) / wl_ratio)
    else:
        raw_kelly = 0.1
    klly = max(0.05, min(0.50, raw_kelly * 0.5))  # Half-Kelly, bounded

    # Trailing stop: 50% of average win
    trail_stop = max(0.01, avg_win * 0.5)
    trail_act = max(0.005, avg_win * 0.3)

    # Position drawdown: 2× average loss
    pos_dd = min(0.12, max(0.03, avg_loss * 2.0))

    return OptimalParams(
        symbol=symbol,
        stop_loss_pct=round(sl_pct, 4),
        take_profit_pct=round(tp_pct, 4),
        max_position_cycles=max_cycles,
        kelly_fraction=round(klly, 4),
        trailing_stop_pct=round(trail_stop, 4),
        trailing_stop_activation=round(trail_act, 4),
        position_stop_pct=round(pos_dd, 4),
        win_rate=round(win_rate, 4),
        sample_size=len(valid),
        avg_hold_cycles=round(avg_hold),
    )


def optimize_from_journal(state_dir: str) -> Dict[str, dict]:
    """Read trade journal from state, compute per-symbol optimal params.

    Returns dict of symbol → optimal_params_dict suitable for writing
    to optimal_params.json.
    """
    journal_path = Path(state_dir) / "agent_state.json"
    if not journal_path.exists():
        return {}

    try:
        with open(journal_path) as f:
            state = json.load(f)
    except Exception:
        return {}

    journal = state.get("_trade_journal", [])
    if len(journal) < MIN_TRADES:
        return {}

    by_sym = defaultdict(list)
    for t in journal:
        sym = t.get("symbol", "")
        if sym:
            by_sym[sym].append(t)

    results = {}
    for sym, trades in by_sym.items():
        params = analyze_trades(trades)
        if params:
            results[sym] = asdict(params)
            logger.info(
                f"  {sym}: n={params.sample_size} wr={params.win_rate:.0%} "
                f"sl={params.stop_loss_pct:.1%} tp={params.take_profit_pct:.1%} "
                f"klly={params.kelly_fraction:.3f} hold={params.max_position_cycles}c "
                f"trail={params.trailing_stop_pct:.1%}"
            )

    return results


def write_optimal_params(state_dir: str, params: Dict[str, dict]) -> bool:
    """Write optimized params to data/optimal_params.json."""
    if not params:
        return False

    out_path = Path(state_dir.replace("/paper_state", "")) / "optimal_params.json"
    try:
        payload = {
            "updated_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
            "updated_cycle": params.get("_cycle", 0),
            "symbols": params,
        }
        with open(out_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"  Wrote optimal params to {out_path} ({len(params)} symbols)")
        return True
    except Exception as e:
        logger.warning(f"  Failed to write optimal params: {e}")
        return False


def run_cycle(state_dir: str, current_cycle: int) -> Dict[str, dict]:
    """Main entry point: called every N cycles from harness.run_cycle().

    Returns per-symbol optimized params (empty if not enough data).
    """
    results = optimize_from_journal(state_dir)
    if results:
        results["_cycle"] = current_cycle
        write_optimal_params(state_dir, results)
    return results
