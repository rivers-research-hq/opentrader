#!/usr/bin/env python3
"""Reward functions for RL fine-tuning of OpenTrader trading agents.

Provides reward signals for GRPO and other RL algorithms:
  - realized_pnl_reward: actual PnL minus fees per trade (normalized to portfolio %)
  - sharpe_windowed_reward: rolling Sharpe ratio over portfolio history
  - composite_reward: weighted combination for final RL signal
"""
import json
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("opentrader.reward_builder")

DEFAULT_FEE_RATE = 0.001
PERIODS_PER_YEAR = 365 * 24 * 60  # minute-level periods for 24/7 crypto markets


def realized_pnl_reward(
    trade_journal: List[dict],
    portfolio_value: float = 100_000.0,
    fee_schedule: Optional[dict] = None,
    default_fee: float = DEFAULT_FEE_RATE,
) -> float:
    """Compute total realized PnL net of fees, normalized to portfolio fraction.

    reward = sum((pnl_dollar - fee_cost) / portfolio_value) per trade.
    fee_cost = quantity * price * fee_rate * 2 (round-trip).

    Returns a float in [-inf, inf] but typically [-0.5, 0.5] per trade.
    """
    if not trade_journal:
        return 0.0

    pv = max(portfolio_value, 1.0)
    total = 0.0
    for t in trade_journal:
        pnl = t.get("pnl_dollar", 0)
        qty = t.get("quantity", 0)
        entry_price = abs(t.get("entry_price", 0))
        exit_price = abs(t.get("exit_price", 0))

        symbol = t.get("symbol", "")
        fee_rate = default_fee
        if fee_schedule and symbol:
            sym_fee = fee_schedule.get(symbol, {})
            fee_rate = sym_fee.get("fee_rate", default_fee)

        entry_fee = (qty * entry_price * fee_rate) if entry_price > 1e-10 else 0
        exit_fee = (qty * exit_price * fee_rate) if exit_price > 1e-10 else 0
        total += (pnl - entry_fee - exit_fee) / pv

    return round(float(total), 6)


def sharpe_windowed_reward(
    returns: List[float],
    risk_free_rate: float = 0.0,
) -> float:
    """Compute annualized Sharpe ratio from a list of per-period returns.

    Formula: (mean(returns) - rfr_per_period) / std(returns) * sqrt(periods_per_year).

    Returns 0.0 when insufficient data (< 2 returns) or zero volatility.
    """
    if len(returns) < 2:
        return 0.0

    arr = np.array(returns)
    mean_ret = np.mean(arr) - risk_free_rate / PERIODS_PER_YEAR
    std_ret = np.std(arr, ddof=1)

    if std_ret < 1e-10:
        return 0.0

    sharpe = mean_ret / std_ret * math.sqrt(PERIODS_PER_YEAR)
    clamped = max(-3.0, min(3.0, sharpe))
    return round(float(clamped), 4)


def win_rate_reward(trade_journal: List[dict]) -> float:
    """Fraction of closed trades that were profitable.

    Returns a value in [0.0, 1.0]. Returns 0.5 if no trades (neutral).
    """
    if not trade_journal:
        return 0.5

    wins = sum(1 for t in trade_journal if t.get("pnl_pct", 0) > 0.001)
    return round(wins / len(trade_journal), 4)


def drawdown_penalty(
    portfolio_values: List[float],
    peak_value: float,
) -> float:
    """Penalty term based on current drawdown from peak.

    Returns a penalty in [0.0, 1.0] where 0 = no drawdown, 1 = 100% drawdown.
    """
    if not portfolio_values or peak_value <= 0:
        return 0.0

    current = portfolio_values[-1]
    dd = max(0.0, (peak_value - current) / peak_value)
    return round(min(dd, 1.0), 4)


def composite_reward(
    trade_journal: List[dict],
    portfolio_values: List[float],
    peak_value: float,
    portfolio_value_current: float = 100_000.0,
    fee_schedule: Optional[dict] = None,
    w_pnl: float = 0.5,
    w_sharpe: float = 0.3,
    w_win: float = 0.15,
    w_dd: float = -0.5,
    default_fee: float = DEFAULT_FEE_RATE,
) -> float:
    """Weighted composite reward combining PnL, Sharpe, win rate, and drawdown.

    All components are naturally bounded or normalized:
      - PnL: fraction of portfolio (typically [-0.5, 0.5])
      - Sharpe: annualized (typically [-2, 2])
      - Win rate: [0, 1]
      - Drawdown: [0, 1]

    Args:
        trade_journal: List of closed trade dicts.
        portfolio_values: List of historical portfolio values.
        peak_value: All-time high watermark.
        portfolio_value_current: Current portfolio value for PnL normalization.
        fee_schedule: Optional per-symbol fee rates.
        w_pnl, w_sharpe, w_win: Positive weights for reward components.
        w_dd: Negative weight (drawdown penalty).
        default_fee: Default fee rate when fee_schedule is unavailable.

    Returns:
        Single scalar reward value.
    """
    pnl_rew = realized_pnl_reward(
        trade_journal, portfolio_value_current, fee_schedule, default_fee,
    )
    sharpe_rew = portfolio_to_sharpe(portfolio_values)
    win_rew = win_rate_reward(trade_journal)
    dd_pen = drawdown_penalty(portfolio_values, peak_value)

    composite = (
        w_pnl * pnl_rew
        + w_sharpe * sharpe_rew
        + w_win * win_rew
        + w_dd * dd_pen
    )
    return round(float(composite), 4)


def portfolio_to_sharpe(portfolio_values: List[float]) -> float:
    """Compute Sharpe ratio from a sequence of portfolio value snapshots."""
    if len(portfolio_values) < 2:
        return 0.0

    returns = [
        (portfolio_values[i] - portfolio_values[i - 1]) / portfolio_values[i - 1]
        for i in range(1, len(portfolio_values))
        if portfolio_values[i - 1] > 1e-10
    ]
    return sharpe_windowed_reward(returns)


def reward_from_state(
    state_dir: str,
    window: int = 20,
    **composite_kwargs,
) -> float:
    """Convenience: load state files and compute composite reward.

    Reads:
      - agent_state.json -> _trade_journal
      - paper_state.json -> portfolio_value, peak_value
      - data/history/cycle_*.json -> historical portfolio values for Sharpe

    Returns the composite reward value.
    """
    state_path = Path(state_dir)
    agent_path = state_path / "agent_state.json"
    paper_path = state_path / "paper_state.json"

    trade_journal = []
    portfolio_values = []
    peak_value = 0.0
    portfolio_value_current = 100_000.0

    if agent_path.exists():
        with open(agent_path) as f:
            agent = json.load(f)
        trade_journal = agent.get("_trade_journal", [])

    if paper_path.exists():
        with open(paper_path) as f:
            paper = json.load(f)
        portfolio_value_current = paper.get("portfolio_value", portfolio_value_current) or portfolio_value_current
        peak_value = paper.get("metrics", {}).get("peak_value", 0) or 0

    portfolio_values = _extract_portfolio_history(state_path)

    return composite_reward(
        trade_journal, portfolio_values, peak_value, portfolio_value_current,
        **composite_kwargs,
    )


def _extract_portfolio_history(state_path: Path) -> List[float]:
    """Extract portfolio value history from data/history/cycle_*.json files.

    Reads up to 200 most recent cycle files for a meaningful time series.
    Falls back to empty list if no history directory exists.
    """
    history_dir = state_path / "history"
    if not history_dir.is_dir():
        return []

    cycle_files = sorted(history_dir.glob("cycle_*.json"))
    values = []
    for cf in cycle_files[-200:]:
        try:
            data = json.loads(cf.read_text())
            pv = data.get("portfolio_value", 0)
            if pv and pv > 0:
                values.append(pv)
        except Exception:
            continue
    return values


def reward_consistency(
    trade_journal: List[dict],
    window: int = 10,
) -> float:
    """Measure reward consistency -- low variance in per-trade PnL.

    Returns a score in [0, 1] where 1 = perfectly consistent.
    Uses coefficient of variation (CV) inverted so higher = better.
    """
    if len(trade_journal) < window:
        return 0.0

    recent = trade_journal[-window:]
    pnls = [t.get("pnl_pct", 0) for t in recent]

    mean_pnl = np.mean(pnls)
    std_pnl = np.std(pnls, ddof=1)

    if abs(mean_pnl) < 1e-10 or std_pnl < 1e-10:
        return 0.5

    cv = std_pnl / abs(mean_pnl)
    consistency = 1.0 / (1.0 + cv)
    return round(float(consistency), 4)


# ═══════════════════════════════════════════════════════════════
# Behavioral rewards: detect and penalize agent looping,
# reward exploration and novelty.
# ═══════════════════════════════════════════════════════════════


def detect_behavioral_loop(
    signal_history: List[dict],
    window: int = 20,
    action_ratio_threshold: float = 0.80,
) -> Tuple[bool, dict]:
    """Detect if the agent is stuck in a behavioral loop.

    A behavioral loop is defined as producing the same action (e.g. all HOLD)
    for >80% of the last N cycles despite market conditions changing.
    This is the canonical "stuck agent" problem.

    Args:
        signal_history: List of signal dicts with 'action' and 'symbol' keys.
        window: Lookback window in signals.
        action_ratio_threshold: Fraction of identical actions that triggers loop detection.

    Returns:
        (is_stuck, diagnostics) — is_stuck is True when a loop is detected.
        diagnostics contains: dominant_action, action_ratio, unique_actions,
        symbol_count, window_size, loop_type.
    """
    if len(signal_history) < window:
        return False, {"reason": "insufficient_data", "count": len(signal_history)}

    recent = signal_history[-window:]
    actions = [s.get("action", "HOLD") for s in recent]
    symbols = list(set(s.get("symbol", "?") for s in recent))

    # Count action frequencies
    action_counts = Counter(actions)
    dominant_action, dominant_count = action_counts.most_common(1)[0]
    dominant_ratio = dominant_count / len(actions)

    is_stuck = dominant_ratio >= action_ratio_threshold
    unique_actions = len(action_counts)

    diagnostics = {
        "dominant_action": dominant_action,
        "dominant_ratio": round(dominant_ratio, 2),
        "action_counts": dict(action_counts),
        "unique_actions": unique_actions,
        "window_size": window,
        "symbol_count": len(symbols),
    }

    if is_stuck:
        if dominant_action == "HOLD":
            diagnostics["loop_type"] = "paralysis"  # won't act
        elif dominant_action == "BUY":
            diagnostics["loop_type"] = "overbuy"    # buying too much
        elif dominant_action == "SELL":
            diagnostics["loop_type"] = "oversell"   # panic selling
        else:
            diagnostics["loop_type"] = "unknown"
    else:
        diagnostics["loop_type"] = "none"

    return is_stuck, diagnostics


def novelty_bonus(
    signal_history: List[dict],
    window: int = 20,
) -> float:
    """Reward for action diversity — penalizes repetitive behavior.

    Uses entropy of the action distribution: high entropy = diverse actions = good.
    Returns a value in [0, 1] where 1 = maximum diversity, 0 = completely repetitive.
    """
    if len(signal_history) < window:
        return 0.5

    recent = signal_history[-window:]
    actions = [s.get("action", "HOLD") for s in recent]
    counts = Counter(actions)
    total = len(actions)

    # Normalized Shannon entropy
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log(p)

    # Max entropy for 3 actions (HOLD, BUY, SELL) = log(3) ≈ 1.099
    max_entropy = math.log(3)
    return round(min(1.0, entropy / max_entropy), 4)


def anti_loop_penalty(
    signal_history: List[dict],
    window: int = 20,
    max_penalty: float = 0.5,
) -> float:
    """Penalty term that increases as behavior becomes more repetitive.

    Returns a value in [0, max_penalty] where 0 = diverse behavior, max_penalty = stuck.

    This is the inverse of novelty_bonus: 1 - novelty maps to [0, 1], scaled by max_penalty.
    """
    if len(signal_history) < window:
        return 0.0

    novelty = novelty_bonus(signal_history, window)
    # Invert: high novelty = low penalty
    penalty = (1.0 - novelty) * max_penalty
    return round(penalty, 4)


def coach_guided_reward(
    signal_history: List[dict],
    coach_report: Optional[dict] = None,
    window: int = 20,
) -> Tuple[float, dict]:
    """Integrate coach analysis into reward shaping.

    If the coach identified specific failure patterns, the reward
    penalizes actions matching those patterns. If the coach identified
    winning patterns, the reward boosts actions matching those.

    Args:
        signal_history: Recent signal records.
        coach_report: Coach analysis dict (from coach_report.json).
        window: Lookback window for analysis.

    Returns:
        (adjusted_reward, meta) — adjusted_reward is the overall
        coach-informed behavioral adjustment (-1.0 to 1.0), and meta
        contains detailed breakdown.
    """
    is_stuck, diag = detect_behavioral_loop(signal_history, window)
    novelty = novelty_bonus(signal_history, window)
    anti_loop = anti_loop_penalty(signal_history, window)

    # Start from novelty baseline (positive term)
    behavioral_reward = novelty

    # Stuck penalty: if loop detected, apply stronger penalty
    if is_stuck:
        loop_type = diag.get("loop_type", "unknown")
        if loop_type == "paralysis":
            # Paralysis (all HOLD) is the most dangerous — no signal = no learning
            behavioral_reward -= 0.4
        elif loop_type in ("overbuy", "oversell"):
            behavioral_reward -= 0.2
        behavioral_reward -= anti_loop  # additional proportional penalty

    # Coach-guided shaping
    coach_boost = 0.0
    coach_penalty = 0.0
    failure_patterns = []

    if coach_report:
        failure_patterns = coach_report.get("failure_patterns", [])
        winning_patterns = coach_report.get("winning_patterns", [])
        coach_grade = coach_report.get("grade", "N/A")

        # Grade-based baseline adjustment
        grade_map = {"A": 0.15, "B": 0.1, "C": 0.05, "D": -0.1, "F": -0.2}
        grade_bonus = grade_map.get(coach_grade, 0.0)
        behavioral_reward += grade_bonus

        # Pattern matching: if recent signals look like failure patterns, penalize
        if failure_patterns:
            recent_texts = [
                s.get("reason", "") for s in signal_history[-window:]
            ]
            pattern_matches = sum(
                1
                for fp in failure_patterns
                for rt in recent_texts
                if fp[:20].lower() in rt.lower()
            )
            if pattern_matches > 0:
                coach_penalty = min(0.3, pattern_matches * 0.05)
                behavioral_reward -= coach_penalty

        # Boost if matching winning patterns
        if winning_patterns:
            recent_texts = [
                s.get("reason", "") for s in signal_history[-window:]
            ]
            win_matches = sum(
                1
                for wp in winning_patterns
                for rt in recent_texts
                if wp[:20].lower() in rt.lower()
            )
            if win_matches > 0:
                coach_boost = min(0.3, win_matches * 0.05)
                behavioral_reward += coach_boost

    # Clamp
    behavioral_reward = max(-1.0, min(1.0, behavioral_reward))

    meta = {
        "is_stuck": is_stuck,
        "loop_diagnostics": diag,
        "novelty": novelty,
        "anti_loop_penalty": anti_loop,
        "coach_boost": round(coach_boost, 4),
        "coach_penalty": round(coach_penalty, 4),
        "failure_patterns_matched": failure_patterns,
        "behavioral_reward": round(behavioral_reward, 4),
    }

    return round(behavioral_reward, 4), meta


def behavioral_composite_reward(
    trade_journal: List[dict],
    signal_history: List[dict],
    portfolio_values: List[float],
    peak_value: float,
    portfolio_value_current: float = 100_000.0,
    coach_report: Optional[dict] = None,
    fee_schedule: Optional[dict] = None,
    w_pnl: float = 0.40,
    w_sharpe: float = 0.20,
    w_behavior: float = 0.30,
    w_dd: float = -0.10,
    default_fee: float = DEFAULT_FEE_RATE,
) -> Tuple[float, dict]:
    """Composite reward that includes behavioral anti-looping terms.

    PnL and Sharpe measure what the agent DID. Behavioral terms (novelty,
    anti-loop, coach guidance) measure whether the agent is LEARNING.

    Returns:
        (total_reward, meta) where meta contains individual components.
    """
    pnl_rew = realized_pnl_reward(
        trade_journal, portfolio_value_current, fee_schedule, default_fee,
    )
    sharpe_rew = portfolio_to_sharpe(portfolio_values)
    dd_pen = drawdown_penalty(portfolio_values, peak_value)

    behav, behav_meta = coach_guided_reward(
        signal_history, coach_report, window=20,
    )

    total = (
        w_pnl * pnl_rew
        + w_sharpe * sharpe_rew
        + w_behavior * behav
        + w_dd * dd_pen
    )

    meta = {
        "pnl_reward": round(pnl_rew, 4),
        "sharpe_reward": round(sharpe_rew, 4),
        "drawdown_penalty": round(dd_pen, 4),
        "behavioral_reward": round(behav, 4),
        "behavioral_meta": behav_meta,
        "total": round(float(total), 4),
    }

    return round(float(total), 4), meta


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compute RL rewards from state")
    parser.add_argument("--state-dir", default="data", help="State directory")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

    reward = reward_from_state(args.state_dir)
    print(f"composite_reward={reward}")

    state_path = Path(args.state_dir)
    agent_path = state_path / "agent_state.json"
    if agent_path.exists():
        with open(agent_path) as f:
            agent = json.load(f)
        journal = agent.get("_trade_journal", [])
        print(f"trades={len(journal)} win_rate={win_rate_reward(journal)}")
