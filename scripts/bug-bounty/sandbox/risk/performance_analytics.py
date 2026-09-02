#!/usr/bin/env python3
"""Performance Analytics Engine — Sharpe, Sortino, win rate, rolling metrics.

Computes key risk-adjusted performance statistics from trade journal
and equity curve data. Feeds the dashboard Performance tab.

Metrics computed:
  - Sharpe ratio (annualized, assuming daily equity values)
  - Sortino ratio (downside-only)
  - Win rate (% of profitable trades)
  - Profit factor (gross profit / gross loss)
  - Max drawdown & duration
  - Rolling Sharpe (windowed)
  - Average winner vs average loser
  - Expectancy (avg PnL per trade)
  - Calmar ratio (annualized return / max DD)
"""
import math
from typing import Any, Dict, List, Optional


def compute_all(
    equity_curve: List[float],
    trades: List[dict],
    rolling_window: int = 20,
    risk_free_rate: float = 0.04,  # 4% annual
    periods_per_year: int = 365,
) -> dict:
    """Compute all performance metrics from equity curve and trade journal.

    Args:
        equity_curve: List of portfolio values over time (one per cycle)
        trades: List of completed trade dicts (symbol, pnl_pct, pnl_dollar, ...)
        rolling_window: Window for rolling metrics
        risk_free_rate: Annual risk-free rate
        periods_per_year: Number of periods per year (365 for daily, 8760 for hourly)

    Returns:
        dict with all metrics, ready for dashboard display
    """
    metrics: Dict[str, Any] = {}

    # ── Basic return stats ──
    if len(equity_curve) >= 2:
        total_return = (equity_curve[-1] / equity_curve[0] - 1)
        returns = [
            (equity_curve[i] / equity_curve[i-1] - 1)
            for i in range(1, len(equity_curve))
            if equity_curve[i-1] > 0
        ]
        metrics["total_return_pct"] = round(total_return * 100, 2)
        metrics["num_periods"] = len(equity_curve)
    else:
        returns = []
        metrics["total_return_pct"] = 0
        metrics["num_periods"] = 0

    # ── Sharpe ratio ──
    if returns and len(returns) >= 2:
        avg_ret = sum(returns) / len(returns)
        variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(variance)
        if std_ret > 0:
            sharpe_num = (avg_ret * periods_per_year - risk_free_rate) / (std_ret * math.sqrt(periods_per_year))
            metrics["sharpe_ratio"] = round(sharpe_num, 3)
        else:
            metrics["sharpe_ratio"] = 0.0
    else:
        metrics["sharpe_ratio"] = 0.0

    # ── Sortino ratio ──
    if returns:
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            down_avg = sum(downside_returns) / len(downside_returns)
            down_var = sum((r - down_avg) ** 2 for r in downside_returns) / len(downside_returns)
            down_std = math.sqrt(down_var)
            if down_std > 0:
                metrics["sortino_ratio"] = round(
                    (avg_ret * periods_per_year - risk_free_rate) / (down_std * math.sqrt(periods_per_year)), 3
                )
            else:
                metrics["sortino_ratio"] = 0.0
        else:
            metrics["sortino_ratio"] = 99.0  # no downside
    else:
        metrics["sortino_ratio"] = 0.0

    # ── Max drawdown ──
    if len(equity_curve) >= 2:
        peak = equity_curve[0]
        max_dd = 0.0
        max_dd_duration = 0
        current_duration = 0
        for val in equity_curve:
            if val > peak:
                peak = val
                current_duration = 0
            dd = (peak - val) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if dd > 0:
                current_duration += 1
                max_dd_duration = max(max_dd_duration, current_duration)
            else:
                current_duration = 0
        metrics["max_drawdown_pct"] = round(max_dd * 100, 2)
        metrics["max_drawdown_duration"] = max_dd_duration
    else:
        metrics["max_drawdown_pct"] = 0
        metrics["max_drawdown_duration"] = 0

    # ── Trade metrics ──
    if trades:
        wins = [t for t in trades if t.get("pnl_dollar", 0) > 0]
        losses = [t for t in trades if t.get("pnl_dollar", 0) < 0]
        breakevens = [t for t in trades if t.get("pnl_dollar", 0) == 0]

        metrics["total_trades"] = len(trades)
        metrics["win_count"] = len(wins)
        metrics["loss_count"] = len(losses)
        metrics["break_even_count"] = len(breakevens)
        # Win rate: exclude break-evens (no-skill trades) from denominator
        decisive = len(wins) + len(losses)
        metrics["win_rate_pct"] = round(len(wins) / decisive * 100, 1) if decisive > 0 else 0

        if wins:
            metrics["avg_winner_pct"] = round(sum(t.get("pnl_pct", 0) for t in wins) / len(wins) * 100, 2)
            metrics["avg_winner_dollar"] = round(sum(t.get("pnl_dollar", 0) for t in wins) / len(wins), 2)
        else:
            metrics["avg_winner_pct"] = 0
            metrics["avg_winner_dollar"] = 0

        if losses:
            metrics["avg_loser_pct"] = round(sum(t.get("pnl_pct", 0) for t in losses) / len(losses) * 100, 2)
            metrics["avg_loser_dollar"] = round(sum(t.get("pnl_dollar", 0) for t in losses) / len(losses), 2)
        else:
            metrics["avg_loser_pct"] = 0
            metrics["avg_loser_dollar"] = 0

        # Profit factor (real losses only, break-evens don't contribute)
        gross_profit = sum(t.get("pnl_dollar", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl_dollar", 0) for t in losses))
        metrics["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 1.0)

        # Expectancy
        metrics["expectancy_dollar"] = round(
            sum(t.get("pnl_dollar", 0) for t in trades) / len(trades), 2
        ) if trades else 0

        # Average trade duration
        durations = [t.get("duration_cycles", 0) for t in trades if t.get("duration_cycles", 0) > 0]
        metrics["avg_duration_cycles"] = round(sum(durations) / len(durations), 1) if durations else 0

        # Win/loss ratio
        if wins and losses:
            metrics["win_loss_size_ratio"] = round(
                (sum(t.get("pnl_dollar", 0) for t in wins) / len(wins)) /
                max(abs(sum(t.get("pnl_dollar", 0) for t in losses) / len(losses)), 0.01), 2
            )
        else:
            metrics["win_loss_size_ratio"] = 0

        # Recent streak
        recent = list(reversed(trades))
        streak = 0
        streak_type = "win" if recent and recent[0].get("pnl_dollar", 0) > 0 else "loss"
        for t in recent:
            if (streak_type == "win" and t.get("pnl_dollar", 0) > 0) or \
               (streak_type == "loss" and t.get("pnl_dollar", 0) <= 0):
                streak += 1
            else:
                break
        metrics["current_streak"] = f"{streak} {streak_type}s"
    else:
        metrics["total_trades"] = 0
        metrics["win_count"] = 0
        metrics["loss_count"] = 0
        metrics["win_rate_pct"] = 0
        metrics["avg_winner_pct"] = 0
        metrics["avg_loser_pct"] = 0
        metrics["profit_factor"] = 0
        metrics["expectancy_dollar"] = 0
        metrics["avg_duration_cycles"] = 0
        metrics["win_loss_size_ratio"] = 0
        metrics["current_streak"] = "—"

    # ── Rolling metrics ──
    if len(returns) >= rolling_window:
        rolling_sharpe = []
        for i in range(len(returns) - rolling_window + 1):
            window = returns[i:i+rolling_window]
            if len(window) >= 2:
                avg = sum(window) / len(window)
                var = sum((r - avg) ** 2 for r in window) / len(window)
                std = math.sqrt(var)
                if std > 0:
                    rolling_sharpe.append(round(avg / std, 3))
                else:
                    rolling_sharpe.append(0)
        metrics["rolling_sharpe"] = rolling_sharpe[-50:]  # last 50 rolling values
        metrics["rolling_sharpe_latest"] = rolling_sharpe[-1] if rolling_sharpe else 0
    else:
        metrics["rolling_sharpe"] = []
        metrics["rolling_sharpe_latest"] = 0

    # ── Calmar ratio (annualized return / max DD) ──
    if metrics.get("max_drawdown_pct", 0) > 0 and len(equity_curve) >= 2:
        ann_return = (equity_curve[-1] / equity_curve[0]) * (periods_per_year / len(equity_curve))
        metrics["calmar_ratio"] = round((ann_return - 1) * 100 / metrics["max_drawdown_pct"], 2)
    else:
        metrics["calmar_ratio"] = 0

    # ── Summary grade ──
    sharpe = metrics.get("sharpe_ratio", 0)
    if sharpe >= 2.0:
        grade = "A+"
    elif sharpe >= 1.5:
        grade = "A"
    elif sharpe >= 1.0:
        grade = "B"
    elif sharpe >= 0.5:
        grade = "C"
    elif sharpe >= 0:
        grade = "D"
    else:
        grade = "F"
    metrics["grade"] = grade

    return metrics


def compute_goal_probability(
    equity_curve: List[float],
    target: float = 270.0,
    ruin_threshold: float = 50.0,
    cycles_per_day: int = 5760,
    max_days: int = 30,
    n_bootstrap: int = 1000,
) -> dict:
    """Probability of reaching a capital target given historical return dynamics.

    Uses two approaches:
      1. Analytic: drift-diffusion model (Brownian motion with drift)
         P(reach U before L) for an Ito process with estimated μ, σ
      2. Bootstrap: Monte Carlo from historical cycle returns
         Resample daily returns, project forward, count successes

    Args:
        equity_curve: Portfolio values over time (per cycle)
        target: Goal capital to reach
        ruin_threshold: Capital level considered "ruined" (lower barrier)
        cycles_per_day: Cycles per day (for time horizon estimation)
        max_days: Maximum trading days to consider
        n_bootstrap: Monte Carlo simulation paths

    Returns:
        dict with probability, expected days, confidence, method details
    """
    result: Dict[str, Any] = {
        "target": target,
        "current_capital": equity_curve[-1] if equity_curve else 0,
        "ruin_threshold": ruin_threshold,
        "probability": 0.0,
        "expected_days": None,
        "confidence": "low",
        "method": "none",
    }

    if len(equity_curve) < 30:
        result["reason"] = "insufficient history (< 30 cycles)"
        return result

    pv = equity_curve[-1]
    if pv <= 0:
        result["reason"] = "zero or negative portfolio value"
        return result
    if pv >= target:
        result["probability"] = 100.0
        result["expected_days"] = 0
        result["confidence"] = "certain"
        result["reason"] = "already reached"
        return result

    # ── Cycle-level log returns ──
    log_returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i-1] > 0 and equity_curve[i] > 0:
            log_returns.append(math.log(equity_curve[i] / equity_curve[i-1]))

    if not log_returns:
        result["reason"] = "no valid returns"
        return result

    mean_log_ret = sum(log_returns) / len(log_returns)
    var_log_ret = sum((r - mean_log_ret) ** 2 for r in log_returns) / len(log_returns)
    std_log_ret = math.sqrt(var_log_ret) if var_log_ret > 0 else 1e-10

    # ── Analytic: drift-diffusion first-passage probability ──
    # For log-normal process with drift μ and variance σ²:
    #   P(reach U before L) = (1 - (pv/L)^(1 - 2μ/σ²)) / (1 - (U/L)^(1 - 2μ/σ²))
    # where μ = mean_log_ret, σ² = var_log_ret
    drift = mean_log_ret
    var = var_log_ret

    if var > 1e-15:
        exponent = 1.0 - 2.0 * drift / var
        # Clamp to avoid overflow
        exponent = max(-20.0, min(20.0, exponent))

        if abs(exponent) < 1e-6:
            # Edge case: exponent ≈ 0 → log-linear interpolation
            pv_log = math.log(pv)
            L_log = math.log(ruin_threshold)
            U_log = math.log(target)
            analytic_p = max(0.0, min(1.0, (pv_log - L_log) / (U_log - L_log)))
        else:
            L_factor = (pv / ruin_threshold) ** exponent
            U_factor = (target / ruin_threshold) ** exponent
            denom = 1.0 - U_factor
            if abs(denom) < 1e-10:
                analytic_p = 0.5
            else:
                analytic_p = max(0.0, min(1.0, (1.0 - L_factor) / denom))
    else:
        analytic_p = 1.0 if drift > 0 else 0.0

    # Expected days: expected first-passage time (rough)
    if drift > 1e-10:
        expected_cycles = math.log(target / pv) / drift
        expected_days = expected_cycles / max(cycles_per_day, 1)
    elif drift < -1e-10:
        expected_cycles = math.log(pv / ruin_threshold) / abs(drift)
        expected_days = -(expected_cycles / max(cycles_per_day, 1))
    else:
        # Flat drift: expected time from diffusion alone
        expected_days = None

    # ── Bootstrap: Monte Carlo from historical returns ──
    # Group returns into daily returns, bootstrap daily paths
    daily_returns: List[float] = []
    chunk = max(1, len(log_returns) // max(1, len(log_returns) // cycles_per_day))
    if chunk > 0:
        for i in range(0, len(log_returns) - chunk + 1, chunk):
            daily_returns.append(sum(log_returns[i:i+chunk]))

    if not daily_returns:
        daily_returns = log_returns[:]

    import random
    successes = 0
    ruin_count = 0
    paths: List[float] = []  # terminal values

    for _ in range(n_bootstrap):
        capital = pv
        for day in range(max_days):
            day_return = random.choice(daily_returns)
            capital *= math.exp(day_return)
            capital = max(0.0, capital)
            if capital >= target:
                successes += 1
                break
            if capital <= ruin_threshold:
                ruin_count += 1
                break
        paths.append(capital)

    bootstrap_p = successes / n_bootstrap * 100.0 if n_bootstrap > 0 else 0.0
    avg_terminal = sum(paths) / len(paths)

    # ── Combine: weighted by confidence ──
    # Use bootstrap when available, fall back to analytic
    prob = bootstrap_p
    method = "bootstrap"
    confidence = "medium" if n_bootstrap >= 500 else "low"

    # Adjust confidence based on history length
    if len(equity_curve) < 200:
        confidence = "low"
    elif len(equity_curve) >= 1000:
        confidence = "high"

    # If drift is negative, probability should be near zero
    if drift < 0 and prob > 30:
        prob = max(analytic_p * 100, 1.0)

    result.update({
        "probability": round(prob, 1),
        "analytic_pct": round(analytic_p * 100, 1),
        "bootstrap_pct": round(bootstrap_p, 1),
        "expected_days": round(expected_days, 1) if expected_days is not None else None,
        "expected_terminal": round(avg_terminal, 2),
        "confidence": confidence,
        "method": method,
        "drift_per_cycle": round(mean_log_ret, 8),
        "vol_per_cycle": round(std_log_ret, 8),
        "bootstrap_paths": n_bootstrap,
        "successful_paths": successes,
        "ruined_paths": ruin_count,
        "horizon_days": max_days,
    })

    return result
