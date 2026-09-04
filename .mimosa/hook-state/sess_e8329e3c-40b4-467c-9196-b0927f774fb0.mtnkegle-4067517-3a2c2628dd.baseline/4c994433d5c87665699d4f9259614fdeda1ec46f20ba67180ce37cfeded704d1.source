#!/usr/bin/env python3
"""OpenTrader Evaluation Framework — TraderBench-style scoring.

Evaluates trading agents across multiple difficulty transforms:
  - Baseline: clean historical data
  - Noisy: Gaussian price noise + volume spikes
  - Meta: false breakouts, support/resistance violations
  - Adversarial: coordinated false signals (fake MA crosses, RSI divergence)

Score computation is purely realized-portfolio-based (no LLM judge).
Generates custom evaluation scenarios as a built-in feature.

Port of ATLANTIS traderbench.py concepts.
"""
import importlib.util
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.training.traderbench")


@dataclass
class ScoreConfig:
    """Scoring configuration per transform."""
    return_cap: float = 2.0       # 200% return = 1.0
    sharpe_floor: float = -1.0
    sharpe_cap: float = 3.0
    drawdown_cap: float = 0.5     # 50% DD = 0.0
    win_rate_floor: float = 0.0
    win_rate_cap: float = 1.0

    # Weights for final score
    weight_return: float = 0.35
    weight_sharpe: float = 0.30
    weight_drawdown: float = 0.15
    weight_win_rate: float = 0.20


@dataclass
class TransformConfig:
    """Configuration for a market transform."""
    name: str = "baseline"
    noise_sigma: float = 0.0
    spike_prob: float = 0.0
    spike_multiplier: float = 3.0
    false_breakout_rate: float = 0.0
    adversarial_injection_rate: float = 0.0


@dataclass
class SimulatorResult:
    """Result of running an agent through a simulator."""
    total_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    equity_curve: List[float] = field(default_factory=list)
    drawdowns: List[float] = field(default_factory=list)
    trade_log: List[dict] = field(default_factory=list)


@dataclass
class EvalResult:
    """Complete evaluation result across all transforms."""
    overall_score: float = 0.0
    grade: str = "F"
    transforms: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, SimulatorResult] = field(default_factory=dict)
    total_trades: int = 0
    total_wins: int = 0
    confidence_intervals: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pass_criteria: Dict[str, bool] = field(default_factory=dict)


# ── Simulator ────────────────────────────────────────────────

class Simulator:
    """Lightweight trading simulator for agent evaluation.

    Runs an agent over OHLCV data with configurable leverage, fees, and slippage.
    Decision interval: every N bars (default 3).
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        max_leverage: float = 3.0,
        fee_rate: float = 0.0004,       # 4bps
        slippage: float = 0.0005,       # 5bps
        decision_interval: int = 3,      # decide every N bars
    ):
        self.initial_capital = initial_capital
        self.max_leverage = max_leverage
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.decision_interval = decision_interval

    def run(self, bars: List[dict], agent_fn: Callable) -> SimulatorResult:
        """Run agent over bars. agent_fn(bars, position, cash) -> (action, confidence).

        Action: "BUY", "SELL", "CLOSE", or "HOLD"
        """
        cash = self.initial_capital
        position = 0.0  # units of asset held
        entry_price = 0.0
        trades = []
        equity_curve = [self.initial_capital]
        peak = self.initial_capital

        n = len(bars)
        for i in range(0, n, self.decision_interval):
            if i + self.decision_interval >= n:
                break

            # Current bar slice
            slice_bars = bars[:i + self.decision_interval]
            current_bar = bars[min(i, n - 1)]
            price = current_bar["close"]

            # Agent decides
            start = time.time()
            action, confidence = agent_fn(slice_bars, position, cash)
            latency = (time.time() - start) * 1000

            if action == "BUY" and cash > 0 and self.max_leverage > 0:
                # Use up to (confidence * max_leverage) of capital
                leverage = min(confidence * self.max_leverage, self.max_leverage)
                invest = cash * leverage * 0.5  # half-Kelly sizing
                qty = invest / price
                fee = qty * price * self.fee_rate
                slippage_cost = qty * price * self.slippage
                total_cost = qty * price + fee + slippage_cost

                if total_cost <= cash:
                    cash -= total_cost
                    entry_price = price
                    position += qty
                    trades.append({
                        "bar": i, "action": "BUY", "price": price,
                        "qty": qty, "confidence": confidence,
                        "latency_ms": round(latency, 0),
                    })

            elif action in ("SELL", "CLOSE") and position > 0:
                # Sell entire position
                fee = position * price * self.fee_rate
                slippage_cost = position * price * self.slippage
                proceeds = position * price - fee - slippage_cost
                pnl = proceeds - (position * entry_price) if entry_price > 0 else 0
                cash += proceeds
                trades.append({
                    "bar": i, "action": action, "price": price,
                    "qty": position, "pnl": round(pnl, 2),
                    "confidence": confidence,
                    "latency_ms": round(latency, 0),
                })
                position = 0.0
                entry_price = 0.0

            # Track equity
            portfolio_value = cash + position * price
            equity_curve.append(portfolio_value)
            if portfolio_value > peak:
                peak = portfolio_value

        # Final close
        if position > 0 and bars:
            final_price = bars[-1]["close"]
            fee = position * final_price * self.fee_rate
            slippage_cost = position * final_price * self.slippage
            proceeds = position * final_price - fee - slippage_cost
            pnl = proceeds - (position * entry_price) if entry_price > 0 else 0
            cash += proceeds
            trades.append({
                "bar": n - 1, "action": "CLOSE", "price": final_price,
                "qty": position, "pnl": round(pnl, 2), "reason": "end_of_data",
            })
            position = 0.0

        # Compute metrics
        total_return = (cash - self.initial_capital) / self.initial_capital
        final_value = cash

        # Sharpe (from equity curve returns)
        returns = []
        for j in range(1, len(equity_curve)):
            prev = equity_curve[j - 1]
            if prev > 0:
                returns.append((equity_curve[j] - prev) / prev)
        sharpe = 0.0
        if len(returns) > 1:
            avg_ret = sum(returns) / len(returns)
            std_ret = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / (len(returns) - 1))
            if std_ret > 0:
                sharpe = (avg_ret / std_ret) * math.sqrt(252)  # annualized

        # Max drawdown
        drawdowns = []
        running_peak = equity_curve[0]
        for v in equity_curve:
            if v > running_peak:
                running_peak = v
            dd = (running_peak - v) / running_peak if running_peak > 0 else 0
            drawdowns.append(dd)
        max_dd = max(drawdowns) if drawdowns else 0

        # Win rate
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        losses = sum(1 for t in trades if t.get("pnl", 0) < 0)
        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0

        return SimulatorResult(
            total_return=total_return,
            sharpe=sharpe,
            max_drawdown=max_dd,
            win_rate=win_rate,
            total_trades=total_trades,
            wins=wins,
            losses=losses,
            equity_curve=equity_curve,
            drawdowns=drawdowns,
            trade_log=trades,
        )


# ── Market Transforms ────────────────────────────────────────

def apply_noise(bars: List[dict], sigma: float = 0.02, spike_prob: float = 0.1,
                spike_mult: float = 3.0) -> List[dict]:
    """Apply Gaussian noise + occasional volume spikes."""
    result = []
    for bar in bars:
        noise = random.gauss(0, sigma)
        vol_mult = 1.0
        if random.random() < spike_prob:
            vol_mult = spike_mult
        result.append({
            "open": bar["open"] * (1.0 + noise * random.uniform(-1, 1)),
            "high": bar["high"] * (1.0 + abs(noise * random.uniform(0.5, 1.5))),
            "low": bar["low"] * (1.0 - abs(noise * random.uniform(0.5, 1.5))),
            "close": bar["close"] * (1.0 + noise),
            "volume": bar["volume"] * vol_mult,
        })
    return result


def apply_meta_manipulation(bars: List[dict], breakout_rate: float = 0.05) -> List[dict]:
    """Apply false breakouts and S/R violations."""
    result = list(bars)
    n = len(result)
    for i in range(n):
        if random.random() < breakout_rate and i > 10:
            # Create false breakout: push price above recent high then revert
            recent_high = max(b["high"] for b in result[max(0, i - 10):i])
            # Spike above resistance
            spike = recent_high * (1.0 + random.uniform(0.01, 0.03))
            result[i]["high"] = spike
            result[i]["close"] = spike * 0.995
            # Next bar reverts
            if i + 1 < n:
                result[i + 1]["open"] = spike * 0.99
                result[i + 1]["close"] = recent_high * 0.995
        # Mini-trend reversals (every ~30 bars)
        if random.random() < 0.03 and i > 5 and i + 3 < n:
            for j in range(3):
                if i + j < n:
                    result[i + j]["close"] = result[i + j - 1]["close"] * (
                        1.0 + random.uniform(-0.015, 0.015))
    return result


def apply_adversarial(bars: List[dict], injection_rate: float = 0.05) -> List[dict]:
    """Inject false technical signals (fake MA cross, RSI divergence, MACD)."""
    result = list(bars)
    n = len(result)
    for i in range(n):
        if random.random() < injection_rate and i > 10:
            signal_type = random.choice(["ma_cross", "rsi_div", "macd"])
            if signal_type == "ma_cross":
                # Push price to create fake moving average cross
                direction = 1 if random.random() > 0.5 else -1
                for j in range(3):
                    if i + j < n:
                        result[i + j]["close"] *= (1.0 + direction * 0.025)
                        result[i + j]["high"] *= (1.0 + direction * 0.03)
                        result[i + j]["low"] *= 0.99
            elif signal_type == "rsi_div" and i > 5:
                # Create divergence: price pushes one way, but velocity suggests reversal
                result[i]["close"] *= (1.0 + random.uniform(-0.03, 0.03))
            else:
                # Fake MACD cross: directional push
                direction = 1 if random.random() > 0.5 else -1
                result[i]["close"] *= (1.0 + direction * 0.02)
    return result


def apply_transform(bars: List[dict], config: TransformConfig) -> List[dict]:
    """Apply all transforms according to config."""
    result = list(bars)
    if config.noise_sigma > 0 or config.spike_prob > 0:
        result = apply_noise(result, config.noise_sigma, config.spike_prob)
    if config.false_breakout_rate > 0:
        result = apply_meta_manipulation(result, config.false_breakout_rate)
    if config.adversarial_injection_rate > 0:
        result = apply_adversarial(result, config.adversarial_injection_rate)
    return result


# ── Scoring ──────────────────────────────────────────────────

TRANSFORM_CONFIGS = {
    "baseline": TransformConfig(name="baseline"),
    "noisy": TransformConfig(
        name="noisy", noise_sigma=0.02, spike_prob=0.1, spike_multiplier=3.0,
    ),
    "meta": TransformConfig(
        name="meta", false_breakout_rate=0.05,
    ),
    "adversarial": TransformConfig(
        name="adversarial", adversarial_injection_rate=0.05,
    ),
}


def _scale(value: float, floor: float, cap: float) -> float:
    """Scale a value to [0, 1] with linear clamping."""
    if cap <= floor:
        return 0.5
    scaled = (value - floor) / (cap - floor)
    return max(0.0, min(1.0, scaled))


def score_sim_result(result: SimulatorResult, config: ScoreConfig = None) -> float:
    """Compute a single weighted score from simulator results."""
    if config is None:
        config = ScoreConfig()

    ret_score = _scale(result.total_return, -config.return_cap, config.return_cap)
    sharpe_score = _scale(result.sharpe, config.sharpe_floor, config.sharpe_cap)
    dd_score = 1.0 - _scale(result.max_drawdown, 0.0, config.drawdown_cap)
    wr_score = _scale(result.win_rate, config.win_rate_floor, config.win_rate_cap)

    score = (
        config.weight_return * ret_score +
        config.weight_sharpe * sharpe_score +
        config.weight_drawdown * dd_score +
        config.weight_win_rate * wr_score
    )
    return round(max(0.0, min(100.0, score * 100.0)), 2)


TRANSFORM_WEIGHTS = {
    "baseline": 0.40,
    "noisy": 0.30,
    "meta": 0.10,
    "adversarial": 0.20,
}


def compute_grade(score: float) -> str:
    if score >= 90: return "S"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"


# ── TraderBench ──────────────────────────────────────────────

class TraderBench:
    """OpenTrader Evaluation Framework.

    Evaluates trading agents across multiple difficulty transforms.
    Generate custom evaluation scenarios as a built-in feature.

    Usage:
        bench = TraderBench()
        result = bench.evaluate(agent_fn, bars)
        print(f"Score: {result.overall_score} ({result.grade})")
    """

    def __init__(
        self,
        transform_configs: Dict[str, TransformConfig] = None,
        transform_weights: Dict[str, float] = None,
        score_config: ScoreConfig = None,
        sim: Simulator = None,
        extra_transforms_dir: str = None,
    ):
        self.transform_configs = transform_configs or dict(TRANSFORM_CONFIGS)
        self.transform_weights = transform_weights or dict(TRANSFORM_WEIGHTS)
        self.score_config = score_config or ScoreConfig()
        self.sim = sim or Simulator()
        if extra_transforms_dir:
            self._load_extra_transforms(extra_transforms_dir)

    @staticmethod
    def _load_transform_from_file(filepath: str) -> tuple:
        """Load a single external transform from a Python file.

        Returns (name, callable) or raises on failure.
        """
        name = os.path.splitext(os.path.basename(filepath))[0]
        spec = importlib.util.spec_from_file_location(f"eval_transform_{name}", filepath)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load transform: {filepath}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "transform"):
            raise AttributeError(f"Transform {filepath} must export a 'transform(bars, config)' function")
        return name, module.transform

    def _load_extra_transforms(self, transforms_dir: str):
        """Load external eval transforms from a directory of .py files.

        Each file must export a function:
            transform(bars: List[dict], config: dict = None) -> List[dict]

        Loaded transforms get a default weight of 0.05 each.
        """
        tdir = Path(transforms_dir)
        if not tdir.exists():
            logger.warning("Extra transforms dir not found: %s", transforms_dir)
            return

        if not hasattr(self, "_external_transforms"):
            self._external_transforms = {}
        loaded = 0
        for fp in sorted(tdir.glob("*.py")):
            try:
                name, func = self._load_transform_from_file(str(fp))
                if name in self.transform_configs:
                    logger.debug("Skipping duplicate transform: %s", name)
                    continue
                self.transform_configs[name] = TransformConfig(name=name)
                self.transform_weights[name] = 0.05
                self._external_transforms[name] = func
                loaded += 1
            except (ImportError, AttributeError, Exception) as e:
                logger.warning("Failed to load transform %s: %s", fp.name, e)

        if loaded:
            logger.info("Loaded %d external eval transforms from %s", loaded, transforms_dir)

    def evaluate(self, agent_fn: Callable, bars: List[dict],
                 bootstrap_runs: int = 0) -> EvalResult:
        """Run full evaluation across all transforms.

        agent_fn(slice_bars, position, cash) -> (action, confidence)

        If bootstrap_runs > 0, runs each transform multiple times and computes
        90% confidence intervals via bootstrap percentile method on scores.
        """
        details = {}
        transform_scores = {}

        externals = getattr(self, "_external_transforms", {})

        for name, config in self.transform_configs.items():
            # Apply transform (built-in or external)
            if name in externals:
                transformed = externals[name](bars, {"name": name})
            else:
                transformed = apply_transform(bars, config)
            # Run simulator
            result = self.sim.run(transformed, agent_fn)
            # Score
            score = score_sim_result(result, self.score_config)
            transform_scores[name] = score
            details[name] = result
            logger.info(f"Transform '{name}': score={score:.1f}, "
                         f"return={result.total_return:.2%}, "
                         f"sharpe={result.sharpe:.2f}, "
                         f"trades={result.total_trades}")

        # Weighted overall score
        total_weight = sum(self.transform_weights.get(n, 0) for n in transform_scores)
        if total_weight > 0:
            overall = sum(
                score * self.transform_weights.get(name, 0)
                for name, score in transform_scores.items()
            ) / total_weight
        else:
            overall = 0.0

        total_trades = sum(d.total_trades for d in details.values())
        total_wins = sum(d.wins for d in details.values())

        ci = {}
        pass_criteria = {}
        if bootstrap_runs > 1:
            for name in self.transform_configs:
                scores = []
                for _ in range(bootstrap_runs):
                    externals = getattr(self, "_external_transforms", {})
                    if name in externals:
                        transformed = externals[name](bars, {"name": name})
                    else:
                        transformed = apply_transform(bars, self.transform_configs[name])
                    r = self.sim.run(transformed, agent_fn)
                    scores.append(score_sim_result(r, self.score_config))
                scores.sort()
                n = len(scores)
                lo_idx = int(n * 0.05)
                hi_idx = int(n * 0.95) - 1
                ci[name] = {
                    "mean": round(sum(scores) / n, 2),
                    "ci_lower": round(scores[max(0, lo_idx)], 2),
                    "ci_upper": round(scores[min(n - 1, max(0, hi_idx))], 2),
                }
                pass_criteria[f"{name}_ci_width"] = (
                    ci[name]["ci_upper"] - ci[name]["ci_lower"]) < 20

        return EvalResult(
            overall_score=round(overall, 2),
            grade=compute_grade(overall),
            transforms=transform_scores,
            details=details,
            total_trades=total_trades,
            total_wins=total_wins,
            confidence_intervals=ci,
            pass_criteria=pass_criteria,
        )

    def evaluate_on_scenario(self, agent_fn: Callable, bars: List[dict],
                              name: str = "custom") -> EvalResult:
        """Evaluate on a single custom scenario (no transforms)."""
        result = self.sim.run(bars, agent_fn)
        score = score_sim_result(result, self.score_config)
        return EvalResult(
            overall_score=score,
            grade=compute_grade(score),
            transforms={name: score},
            details={name: result},
            total_trades=result.total_trades,
            total_wins=result.wins,
        )

    def print_report(self, result: EvalResult) -> str:
        """Generate a human-readable evaluation report."""
        lines = [
            "=" * 60,
            "OPENTRADER — Evaluation Report",
            "=" * 60,
            f"Overall Score: {result.overall_score:.1f} / 100  ({result.grade})",
            f"Total Trades:  {result.total_trades}",
            f"Total Wins:    {result.total_wins}",
            "",
            "Transform Scores:",
        ]
        for name, score in result.transforms.items():
            detail = result.details.get(name)
            if detail:
                lines.append(
                    f"  {name:15s}: {score:6.1f}  "
                    f"ret={detail.total_return:+.2%}  "
                    f"sharpe={detail.sharpe:.2f}  "
                    f"dd={detail.max_drawdown:.2%}  "
                    f"wr={detail.win_rate:.0%}"
                )
            else:
                lines.append(f"  {name:15s}: {score:6.1f}")
        lines.append("=" * 60)
        return "\n".join(lines)
