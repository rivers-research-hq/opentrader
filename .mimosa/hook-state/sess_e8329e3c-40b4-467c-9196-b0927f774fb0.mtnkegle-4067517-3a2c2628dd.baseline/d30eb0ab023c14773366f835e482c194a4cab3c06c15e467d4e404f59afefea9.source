#!/usr/bin/env python3
"""OpenTrader Training Controller — orchestrates teacher/student training.

Integrates:
  - ProgrammaticTeacher (deterministic scenarios)
  - TeacherStudentFramework (scoring + pattern bank)
  - TraderBench (evaluation across transforms)
  - Model-driven student (via llama-swap)
  - Dashboard state persistence

Modes:
  --teacher-only:  Generate N scenarios + save for inspection
  --train:         Run teacher/student training for N epochs
  --evaluate:      Run TraderBench evaluation on the student
  --controller:    Autonomous loop (train → evaluate → report)
"""
import argparse
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Ensure project root is on path
PROJECT = str(Path(__file__).resolve().parent.parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from agent.base import Signal, AgentContext
from agent.mcp_client import MCPClient
from agent.trading_agent import TradingAgent
from training.teacher_student import (
    TeacherStudentFramework, ProgrammaticTeacher, PatternBank,
    Scenario, StudentResponse, ScoredEpisode,
)
from training.traderbench import TraderBench, Simulator, EvalResult
from state.manager import StateManager

logger = logging.getLogger("opentrader.training.controller")


def default_student_fn(scenario: Scenario, agent: TradingAgent = None) -> StudentResponse:
    """Default student: uses TradingAgent heuristic to analyze a scenario."""
    from agent.base import AgentContext, Signal

    if agent is None:
        agent = TradingAgent(name="student", config={
            "use_model": False,
            "model": "opentrader-student",
            "llama_host": "http://127.0.0.1:5802",
        })

    # Build a minimal AgentContext from scenario bars
    bars = scenario.bars[-50:] if len(scenario.bars) > 50 else scenario.bars
    current_price = bars[-1]["close"] if bars else 100.0

    ctx = AgentContext(
        symbol="SCENARIO",
        timeframe="1h",
        cycle=0,
        ohlcv_json=json.dumps({
            "symbol": "SCENARIO",
            "timeframe": "1h",
            "count": len(bars),
            "bars": bars,
            "current_price": current_price,
        }),
        portfolio_json=json.dumps({
            "cash": 100000.0,
            "total_value": 100000.0,
            "positions": {},
            "position_count": 0,
        }),
        regime_json=json.dumps({"regime": scenario.scenario_type, "confidence": 0.5}),
        economics_json=json.dumps({"source": "simulated"}),
    )

    signal = agent.analyze(ctx)
    return StudentResponse(
        decision=signal.action,
        confidence=signal.confidence,
        reasoning=signal.reason,
        position_pct=signal.position_pct,
    )


def model_student_fn(scenario: Scenario, llama_host: str = "http://127.0.0.1:5802",
                      model: str = "opentrader-agent") -> StudentResponse:
    """Model-based student: uses llama-swap to analyze the scenario."""
    bars = scenario.bars[-50:]
    current_price = bars[-1]["close"] if bars else 100.0

    prompt = f"""You are a trading student analyzing a {scenario.scenario_type} scenario.

Scenario: {scenario.description}

Recent price data (last {len(bars)} bars):
Current price: ${current_price:.2f}
Price range: ${min(b['low'] for b in bars):.2f} - ${max(b['high'] for b in bars):.2f}

Analyze the chart and respond with:
SIGNAL: {{"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "reasoning": "...", "position_pct": 0.0-1.0}}
"""

    try:
        import urllib.request
        data = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 256,
        }).encode()
        req = urllib.request.Request(
            f"{llama_host}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        import re
        sig_match = re.search(r'SIGNAL:\s*(\{.*\})', content, re.DOTALL)
        if sig_match:
            sig = json.loads(sig_match.group(1))
            return StudentResponse(
                decision=sig.get("action", "HOLD"),
                confidence=min(1.0, max(0.0, sig.get("confidence", 0.5))),
                reasoning=sig.get("reasoning", ""),
                position_pct=sig.get("position_pct", 0.0),
            )
    except Exception as e:
        logger.warning(f"Model student failed: {e}")

    # Fallback
    return StudentResponse(decision="HOLD", confidence=0.5, reasoning="Model unavailable, HOLD")


def make_agent_fn(agent: TradingAgent) -> Callable:
    """Create a TraderBench-compatible agent function from a TradingAgent."""
    def agent_fn(slice_bars: List[dict], position: float, cash: float) -> tuple:
        nonlocal agent

        if not slice_bars:
            return "HOLD", 0.0

        current_price = slice_bars[-1]["close"]
        ctx = AgentContext(
            symbol="EVAL",
            timeframe="1h",
            cycle=0,
            ohlcv_json=json.dumps({
                "symbol": "EVAL",
                "timeframe": "1h",
                "count": len(slice_bars),
                "bars": slice_bars[-50:] if len(slice_bars) > 50 else slice_bars,
                "current_price": current_price,
            }),
            portfolio_json=json.dumps({
                "cash": cash,
                "total_value": cash + position * current_price,
                "positions": {"EVAL": position} if position > 0 else {},
                "position_count": 1 if position > 0 else 0,
            }),
            regime_json=json.dumps({"regime": "evaluation", "confidence": 0.5}),
            economics_json=json.dumps({"source": "simulated"}),
        )
        signal = agent.analyze(ctx)
        return signal.action, signal.confidence

    return agent_fn


class TrainingController:
    """Orchestrates the full training workflow.

    Modes:
      train:  Teacher/Student epochs
      eval:   TraderBench evaluation
      auto:   Autonomous loop (train → eval → compare → report)
    """

    def __init__(
        self,
        state_dir: str = None,
        bank: PatternBank = None,
        ts_framework: TeacherStudentFramework = None,
        bench: TraderBench = None,
        state_mgr: StateManager = None,
    ):
        if state_dir is None:
            state_dir = str(Path(PROJECT) / "data")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.bank = bank or PatternBank()
        self.ts = ts_framework or TeacherStudentFramework(bank=self.bank)
        self.bench = bench or TraderBench()
        self.state_mgr = state_mgr or StateManager(str(self.state_dir))

        # Running state
        self.running = True
        self._eval_history: List[dict] = []

    def set_student(self, fn: Callable) -> None:
        """Set the student function on the TS framework."""
        self.ts.set_student(fn)

    def run_train(self, epochs: int = 10, scenarios_per_epoch: int = 5) -> dict:
        """Run teacher/student training."""
        logger.info(f"Starting training: {epochs} epochs x {scenarios_per_epoch} scenarios")
        start = time.time()

        for ep in range(epochs):
            if not self.running:
                break
            stats = self.ts.run_epoch(scenarios_per_epoch)
            self._save_training_state(stats)

        elapsed = time.time() - start
        progress = self.ts.get_progress()
        logger.info(f"Training complete: {elapsed:.0f}s, "
                     f"{progress['total_episodes']} episodes, "
                     f"{progress['pattern_bank']['count']} patterns")
        return progress

    def run_evaluate(self, agent_fn: Callable, bars: List[dict] = None) -> EvalResult:
        """Run TraderBench evaluation on an agent."""
        logger.info("Starting TraderBench evaluation...")

        if bars is None:
            # Generate evaluation data from a range scenario
            from .programmatic_teacher import generate_range_accumulation
            scenario = generate_range_accumulation(seed=42)
            bars = scenario.bars

        result = self.bench.evaluate(agent_fn, bars)
        self._eval_history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": result.overall_score,
            "grade": result.grade,
            "transforms": result.transforms,
        })
        self._save_eval_state(result)
        return result

    def run_auto(self, epochs: int = 10, eval_interval: int = 5) -> None:
        """Autonomous training loop: train → evaluate → report."""
        logger.info(f"Starting autonomous loop: {epochs} epochs, eval every {eval_interval}")
        for ep in range(1, epochs + 1):
            if not self.running:
                break
            stats = self.ts.run_epoch(scenarios_per_epoch=5)

            if ep % eval_interval == 0 or ep == epochs:
                logger.info(f"Running evaluation at epoch {ep}...")
                try:
                    from .programmatic_teacher import generate_range_accumulation
                    scenario = generate_range_accumulation(seed=42)
                    agent_fn = lambda sb, pos, cash: ("HOLD", 0.5)
                    result = self.run_evaluate(agent_fn, scenario.bars)
                    logger.info(f"Epoch {ep} eval score: {result.overall_score:.1f} ({result.grade})")
                except Exception as e:
                    logger.warning(f"Eval failed at epoch {ep}: {e}")

            self._save_training_state(stats)

        progress = self.ts.get_progress()
        logger.info(f"Auto training complete: {progress}")

    def get_status(self) -> dict:
        """Get full controller status for dashboard."""
        progress = self.ts.get_progress()
        return {
            "status": "running" if self.running else "idle",
            "training": progress,
            "evaluation_history": self._eval_history[-10:] if self._eval_history else [],
            "last_eval": self._eval_history[-1] if self._eval_history else None,
        }

    def _save_training_state(self, stats: dict) -> None:
        """Write training state for dashboard."""
        try:
            progress = self.ts.get_progress()
            training_dir = self.state_dir / "training"
            training_dir.mkdir(parents=True, exist_ok=True)
            path = training_dir / "training_state.json"
            with open(path, "w") as f:
                json.dump(progress, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Could not save training state: {e}")

    def _save_eval_state(self, result: EvalResult) -> None:
        """Write evaluation state for dashboard."""
        try:
            state = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "overall_score": result.overall_score,
                "grade": result.grade,
                "transforms": result.transforms,
                "total_trades": result.total_trades,
                "total_wins": result.total_wins,
            }
            training_dir = self.state_dir / "training"
            training_dir.mkdir(parents=True, exist_ok=True)
            path = training_dir / "eval_state.json"
            with open(path, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Could not save eval state: {e}")

    def shutdown(self) -> None:
        self.running = False
        self.ts.save_progress()


def main():
    parser = argparse.ArgumentParser(description="OpenTrader Training Controller")
    parser.add_argument("--mode", default="train",
                        choices=["train", "evaluate", "auto", "teacher-only"],
                        help="Controller mode")
    parser.add_argument("--epochs", type=int, default=10, help="Number of epochs")
    parser.add_argument("--scenarios", type=int, default=5, help="Scenarios per epoch")
    parser.add_argument("--eval-interval", type=int, default=5, help="Eval every N epochs")
    parser.add_argument("--student", default="heuristic",
                        choices=["heuristic", "model"],
                        help="Student type")
    parser.add_argument("--model", default="opentrader-agent", help="Model for student")
    parser.add_argument("--llama-host", default="http://127.0.0.1:8080", help="llama-swap URL")
    parser.add_argument("--state-dir", default=None, help="State directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    random.seed(args.seed)

    # Build components
    teacher = ProgrammaticTeacher(seed=args.seed)
    bank = PatternBank()
    ts = TeacherStudentFramework(teacher=teacher, bank=bank)

    if args.student == "heuristic":
        agent = TradingAgent(name="student", config={
            "use_model": False,
            "model": args.model,
            "llama_host": args.llama_host,
        })
        student_fn = lambda s: default_student_fn(s, agent)
    else:
        student_fn = lambda s: model_student_fn(s, args.llama_host, args.model)

    ts.set_student(student_fn)

    # Create controller
    ctrl = TrainingController(state_dir=args.state_dir, bank=bank, ts_framework=ts)

    # Register signal handlers
    def _shutdown(*_):
        logger.info("Shutting down...")
        ctrl.shutdown()
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if args.mode == "teacher-only":
        logger.info("Teacher-only mode: generating scenarios...")
        for i in range(args.scenarios):
            s = teacher.generate()
            print(f"\n--- Scenario {i+1}: {s.scenario_type} [{s.difficulty}] ---")
            print(f"  Description: {s.description[:100]}...")
            print(f"  Ground Truth: {s.ground_truth}")
            print(f"  Bars: {len(s.bars)}")
            print(f"  Confidence: {s.confidence}")

    elif args.mode == "train":
        ctrl.run_train(args.epochs, args.scenarios)
        progress = ts.get_progress()
        print(f"\nTraining complete:")
        print(f"  Episodes: {progress['total_episodes']}")
        print(f"  Patterns: {progress['pattern_bank']['count']}")
        print(f"  Avg Score: {progress['pattern_bank']['avg_score']:.3f}")

    elif args.mode == "evaluate":
        from .programmatic_teacher import generate_range_accumulation
        scenario = generate_range_accumulation(seed=args.seed)
        agent_fn = make_agent_fn(agent)
        result = ctrl.run_evaluate(agent_fn, scenario.bars)
        print(ctrl.bench.print_report(result))

    elif args.mode == "auto":
        ctrl.run_auto(args.epochs, args.eval_interval)
        progress = ts.get_progress()
        print(f"\nAuto training complete:")
        print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
