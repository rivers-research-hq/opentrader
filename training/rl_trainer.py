#!/usr/bin/env python3
"""RL Trainer — local reward-weighted behavioral fine-tuning for OpenTrader.

Replaces the cloud-only GRPO stub with a local training loop that:
  1. Collects closed trades and signal history from state
  2. Scores each trade using behavioral_composite_reward
  3. Builds a reward-weighted training dataset
  4. Runs a short SFT pass (via train_rocm.py subprocess) during idle GPU cycles
  5. Checkpoints so training can resume across cycles
  6. Produces a new adapter that ATDL can evaluate and promote

Architecture:
  trading loop → accumulate trades → coach detects issues
       ↓
  ATDL PLAN → DEVELOP → BehavioralRLTrainer.run()
       ↓
  reward_builder scores trades + behavioral signals
       ↓
  reward-weighted SFT (train_rocm subprocess, <60s per step)
       ↓
  new adapter → ATDL TEST → ATDL DEPLOY

This is NOT full GRPO — it's reward-conditioned SFT, which is:
  - 10x simpler (no reward model, no PPO clipping, no KL penalty)
  - Runs fine on consumer GPUs (RX 7900 GRE, 16GB VRAM)
  - Effective when reward signal is well-structured (it is — we have
    PnL, Sharpe, win rate, novelty bonuses)
  - Proven in practice: "RLAIF" / "Best-of-N" are instances of this pattern

Usage (from ATDL or FlashTrainer):
    from training.rl_trainer import BehavioralRLTrainer

    trainer = BehavioralRLTrainer(
        state_dir="data",
        output_dir="models/finetune",
        rocm_python="/home/mrc/rocm_venv/bin/python3",
    )
    # Called during idle cycles — non-blocking, idempotent
    result = trainer.step()
    # → {"status": "trained", "adapter": "models/finetune/RL-V1/adapter", ...}
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from training.model_config import BASE_MODEL

logger = logging.getLogger("opentrader.rl_trainer")


@dataclass
class RLTrainingConfig:
    """Configuration for local reward-weighted behavioral training.

    All timeouts and limits are conservative for consumer GPUs (16GB VRAM).
    """

    # Training hyperparams
    learning_rate: float = 2e-4
    epochs: int = 1
    batch_size: int = 1
    grad_accum: int = 4
    max_seq_length: int = 1024
    lora_r: int = 8
    lora_alpha: int = 8

    # Behavioral
    min_examples: int = 5          # minimum closed trades to start training
    max_examples: int = 50         # cap examples per step (controls training time)
    reward_pos_threshold: float = 0.01  # trades above this get upweighted
    reward_neg_threshold: float = -0.01  # trades below this get downweighted
    weight_power: float = 2.0      # reward^weight_power = example weight

    # Checkpoint/resume
    checkpoint_interval_seconds: int = 300  # don't retrain within 5 min of last step
    max_step_seconds: int = 120     # hard timeout per training step (subprocess)

    # Paths
    state_dir: str = "data"
    output_dir: str = "models/finetune"
    rocm_python: str = "/home/mrc/rocm_venv/bin/python3"

    # Model
    base_model: str = BASE_MODEL

    # Adapter naming
    version_prefix: str = "RL"


@dataclass
class TrainingStep:
    """One step of behavioral RL training."""

    version: str = ""
    input_trades: int = 0
    examples_built: int = 0
    mean_reward: float = 0.0
    status: str = "pending"  # pending | running | completed | failed | skipped
    error: str = ""
    adapter_path: str = ""
    duration_s: float = 0.0
    timestamp: str = ""


class BehavioralRLTrainer:
    """Local reward-weighted behavioral fine-tuning loop.

    Designed to be called from:
      - ATDL lifecycle (DEVELOP phase)
      - FlashTrainer (during HOLD streaks)
      - Cron scheduler (background retraining)

    Each call to .step() is idempotent — it checks preconditions
    and skips if there isn't enough data or training was too recent.
    """

    def __init__(self, config: Optional[RLTrainingConfig] = None, **kwargs):
        self.cfg = config or RLTrainingConfig(**kwargs)
        self._state_path = Path(self.cfg.state_dir)
        self._checkpoint_path = self._state_path / "rl_trainer_checkpoint.json"
        self._rl_dataset_path = self._state_path / "rl_training_data.jsonl"

        self.steps: List[TrainingStep] = []
        self._load_checkpoint()

    # ══════════════════════════════════════════════════════════════
    # Public API
    # ══════════════════════════════════════════════════════════════

    def should_train(self) -> Tuple[bool, str]:
        """Check if conditions are right for a training step.

        Returns (should_train, reason).
        """
        # Check cooldown
        if self.steps:
            last = self.steps[-1]
            if last.timestamp:
                try:
                    last_dt = datetime.fromisoformat(last.timestamp)
                    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if elapsed < self.cfg.checkpoint_interval_seconds:
                        return False, f"cooldown: {elapsed:.0f}s < {self.cfg.checkpoint_interval_seconds}s"
                except Exception:
                    pass

        # Check training lock
        lock = self._state_path / "training.lock"
        if lock.exists():
            return False, "training.lock active"

        # Check minimum data
        trades = self._load_trade_journal()
        if len(trades) < self.cfg.min_examples:
            return False, f"insufficient trades: {len(trades)} < {self.cfg.min_examples}"

        return True, "ready"

    def step(self) -> dict:
        """Run one behavioral RL training step.

        Returns a status dict. Safe to call frequently — it checks
        preconditions and skips when not ready.
        """
        should, reason = self.should_train()
        if not should:
            logger.debug(f"RLTrainer step skipped: {reason}")
            step = TrainingStep(status="skipped", error=reason)
            self.steps.append(step)
            self._save_checkpoint()
            return {"status": "skipped", "reason": reason}

        t0 = time.time()
        version = self._next_version()
        step = TrainingStep(
            version=version, status="running",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # 1. Build reward-weighted training dataset
            examples, trades_used, mean_reward = self._build_training_data()
            step.input_trades = trades_used
            step.examples_built = examples
            step.mean_reward = round(mean_reward, 4)

            if examples == 0:
                step.status = "skipped"
                step.error = "no trainable examples after reward filtering"
                self.steps.append(step)
                self._save_checkpoint()
                return {"status": "skipped", "reason": step.error}

            logger.info(
                f"RLTrainer step: {trades_used} trades → {examples} examples "
                f"(mean_reward={mean_reward:.4f})"
            )

            # 2. Run reward-weighted SFT subprocess
            output_dir = Path(self.cfg.output_dir) / version
            output_dir.mkdir(parents=True, exist_ok=True)

            train_script = (
                Path(__file__).resolve().parent / "train_rocm.py"
            )

            if not train_script.exists():
                raise FileNotFoundError(f"train_rocm.py not found at {train_script}")

            # Build command
            cmd = [
                self.cfg.rocm_python,
                str(train_script),
                "--data", str(self._rl_dataset_path),
                "--output", str(output_dir),
                "--base", self.cfg.base_model,
                "--epochs", str(self.cfg.epochs),
                "--batch-size", str(self.cfg.batch_size),
                "--grad-accum", str(self.cfg.grad_accum),
                "--lr", str(self.cfg.learning_rate),
                "--max-seq-len", str(self.cfg.max_seq_length),
                "--lora-r", str(self.cfg.lora_r),
                "--lora-alpha", str(self.cfg.lora_alpha),
            ]
            # RX 7900 GRE has 16GB — can run 7B without 4-bit quantization
            if "7900" in self._gpu_name():
                cmd.append("--no-4bit")

            logger.info(f"RLTrainer: launching {version} training...")
            logger.debug(f"  cmd: {' '.join(cmd)}")

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.cfg.max_step_seconds,
                cwd=str(Path(__file__).resolve().parent.parent),
            )

            step.duration_s = round(time.time() - t0, 2)

            if proc.returncode == 0:
                adapter_path = str(output_dir / "adapter")
                step.status = "completed"
                step.adapter_path = adapter_path

                # Write training metadata
                meta = {
                    "version": version,
                    "training_type": "reward_weighted_sft",
                    "trades_used": trades_used,
                    "examples_built": examples,
                    "mean_reward": mean_reward,
                    "config": asdict(self.cfg),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "duration_s": step.duration_s,
                }
                with open(output_dir / "training_meta.json", "w") as f:
                    json.dump(meta, f, indent=2, default=str)

                logger.info(
                    f"RLTrainer: {version} completed in {step.duration_s:.1f}s "
                    f"→ {adapter_path}"
                )
            else:
                step.status = "failed"
                step.error = f"train_rocm exit {proc.returncode}: {proc.stderr[-300:]}"
                logger.warning(f"RLTrainer: {version} failed: {step.error}")

        except subprocess.TimeoutExpired:
            step.status = "failed"
            step.error = f"training timed out after {self.cfg.max_step_seconds}s"
            step.duration_s = round(time.time() - t0, 2)
            logger.warning(f"RLTrainer: {version} timed out")
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.duration_s = round(time.time() - t0, 2)
            logger.error(f"RLTrainer: {version} error: {e}", exc_info=True)

        self.steps.append(step)
        self._save_checkpoint()

        return {
            "status": step.status,
            "version": version,
            "adapter_path": step.adapter_path,
            "trades_used": step.input_trades,
            "examples": step.examples_built,
            "mean_reward": step.mean_reward,
            "duration_s": step.duration_s,
            "error": step.error if step.status == "failed" else None,
        }

    def latest_adapter(self) -> Optional[str]:
        """Return the path of the most recent completed adapter, or None."""
        for step in reversed(self.steps):
            if step.status == "completed" and step.adapter_path:
                return step.adapter_path
        return None

    def summary(self) -> dict:
        """Training progress summary for dashboard."""
        completed = [s for s in self.steps if s.status == "completed"]
        total = len(self.steps)
        return {
            "total_steps": total,
            "completed": len(completed),
            "latest_version": completed[-1].version if completed else None,
            "latest_adapter": completed[-1].adapter_path if completed else None,
            "best_mean_reward": max((s.mean_reward for s in completed), default=0.0),
            "last_step": self.steps[-1].timestamp if self.steps else None,
        }

    # ══════════════════════════════════════════════════════════════
    # Training data builder
    # ══════════════════════════════════════════════════════════════

    def _build_training_data(self) -> Tuple[int, int, float]:
        """Build reward-weighted training JSONL from trade journal.

        Returns (num_examples, num_trades_used, mean_reward).
        """
        trades = self._load_trade_journal()
        if not trades:
            return 0, 0, 0.0

        signal_history = self._load_signal_history()
        portfolio_values = self._load_portfolio_history()
        peak_value = self._load_peak_value()
        portfolio_value = portfolio_values[-1] if portfolio_values else 100_000.0
        coach_report = self._load_coach_report()

        from training.reward_builder import behavioral_composite_reward

        examples = []
        total_reward = 0.0
        trade_count = 0

        # Score each trade and build examples
        for trade in trades[-self.cfg.max_examples:]:
            # Compute composite reward for this point in the journal
            # Use a sliding window: trades from start to this trade's position
            idx = trades.index(trade)
            window_trades = trades[max(0, idx - 10): idx + 1]
            window_signals = signal_history[-min(len(signal_history), idx + 20):]

            reward, _ = behavioral_composite_reward(
                trade_journal=window_trades,
                signal_history=window_signals,
                portfolio_values=portfolio_values,
                peak_value=peak_value,
                portfolio_value_current=portfolio_value,
                coach_report=coach_report,
            )
            total_reward += reward
            trade_count += 1

            # Build a training example from this trade
            prompt = self._trade_to_prompt(trade)
            if not prompt:
                continue

            example = {
                "conversations": [
                    {
                        "from": "system",
                        "value": (
                            "You are a trading agent. You analyze market conditions "
                            "and output trading decisions as JSON: "
                            '{"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0-1.0, '
                            '"reasoning": "claim-evidence-warrant format"}'
                        ),
                    },
                    {
                        "from": "human",
                        "value": prompt.get("context", ""),
                    },
                    {
                        "from": "assistant",
                        "value": prompt.get("decision", ""),
                    },
                ],
                # Metadata: reward weight will be applied by the training script
                "_reward": round(reward, 4),
                "_symbol": trade.get("symbol", "?"),
                "_action": trade.get("action", trade.get("side", "?")),
                "_pnl_pct": trade.get("pnl_pct", trade.get("pnl_dollar", 0)),
            }
            examples.append(example)

        if not examples:
            return 0, trade_count, 0.0

        # Write to JSONL
        self._rl_dataset_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._rl_dataset_path, "w") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")

        mean_reward = total_reward / max(trade_count, 1)
        return len(examples), trade_count, mean_reward

    def _trade_to_prompt(self, trade: dict) -> Optional[dict]:
        """Convert a trade record into a prompt/response pair.

        Returns dict with 'context' and 'decision' keys, or None if unparseable.
        """
        symbol = trade.get("symbol", "?")
        action = trade.get("action", trade.get("side", ""))
        entry_price = trade.get("entry_price", 0)
        exit_price = trade.get("exit_price", 0)
        pnl_pct = trade.get("pnl_pct", 0)
        pnl_dollar = trade.get("pnl_dollar", 0)
        exit_reason = trade.get("exit_reason", "unknown")
        quantity = trade.get("quantity", 0)

        if not symbol or not action:
            return None

        # Build context describing the market conditions at decision time
        context = (
            f"Symbol: {symbol}\n"
            f"Current price: ${float(entry_price):.2f}\n"
            f"Available cash: viewing opportunity\n"
            f"Task: Decide whether to BUY, SELL, or HOLD {symbol}.\n"
        )

        # Build the decision that was made
        decision = (
            f'{{"action": "{action.upper()}", '
            f'"confidence": 0.65, '
            f'"reasoning": "Trade was {action.upper()} on {symbol} at ${float(entry_price):.2f}. '
            f'Outcome: {pnl_pct:+.2%} (${float(pnl_dollar):.2f}), exit: {exit_reason}"}}'
        )

        return {"context": context, "decision": decision}

    # ══════════════════════════════════════════════════════════════
    # State file readers
    # ══════════════════════════════════════════════════════════════

    def _load_trade_journal(self) -> List[dict]:
        trades = []
        # Try agent_state.json first (persisted every cycle)
        agent_path = self._state_path / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                trades = state.get("_trade_journal", [])
                if trades:
                    return trades
            except Exception:
                pass
        # Fallback: paper_state.json
        paper_path = self._state_path / "paper_state.json"
        if paper_path.exists():
            try:
                state = json.loads(paper_path.read_text()) or {}
                trades = state.get("trades", [])
                if trades:
                    return trades
                trades = state.get("analytics", {}).get("trades", [])
            except Exception:
                pass
        return trades

    def _load_signal_history(self) -> List[dict]:
        agent_path = self._state_path / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                return state.get("_signal_history", [])
            except Exception:
                pass
        # Try paper_state
        paper_path = self._state_path / "paper_state.json"
        if paper_path.exists():
            try:
                state = json.loads(paper_path.read_text()) or {}
                return state.get("signals", [])
            except Exception:
                pass
        return []

    def _load_portfolio_history(self) -> List[float]:
        """Extract portfolio value history from cycle files."""
        history_dir = self._state_path / "history"
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

    def _load_peak_value(self) -> float:
        agent_path = self._state_path / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                return state.get("_peak_value", 0.0) or 0.0
            except Exception:
                pass
        return 0.0

    def _load_coach_report(self) -> Optional[dict]:
        coach_path = self._state_path / "coach_report.json"
        if coach_path.exists():
            try:
                return json.loads(coach_path.read_text())
            except Exception:
                pass
        return None

    # ══════════════════════════════════════════════════════════════
    # Checkpoint persistence
    # ══════════════════════════════════════════════════════════════

    def _load_checkpoint(self) -> None:
        if self._checkpoint_path.exists():
            try:
                data = json.loads(self._checkpoint_path.read_text())
                for s in data.get("steps", []):
                    self.steps.append(TrainingStep(**s))
            except Exception:
                pass

    def _save_checkpoint(self) -> None:
        data = {
            "steps": [asdict(s) for s in self.steps[-20:]],  # keep last 20
        }
        tmp = self._checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, self._checkpoint_path)

    def _next_version(self) -> str:
        """Generate next version name: RL-V1, RL-V2, ..."""
        existing = [s.version for s in self.steps if s.status == "completed"]
        counter = len(existing) + 1
        return f"{self.cfg.version_prefix}-V{counter}"

    @staticmethod
    def _gpu_name() -> str:
        """Detect GPU name for training config adjustments."""
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.get_device_name(0) or "unknown"
        except Exception:
            pass
        return "unknown"


# ══════════════════════════════════════════════════════════════
# 

class CodingRLTrainer:
    """Local reward-weighted behavioral fine-tuning for coding agents.

    Mirrors BehavioralRLTrainer but consumes code-generation signals
    (code_diffs, signal_history) instead of trade signals.
    Uses coding_reward_builder for scoring.
    """

    def __init__(self, config=None, **kwargs):
        from pathlib import Path
        self.cfg = config or RLTrainingConfig(**kwargs)
        self._state_path = Path(self.cfg.state_dir)
        self._checkpoint_path = self._state_path / "coding_rl_checkpoint.json"
        self._rl_dataset_path = self._state_path / "coding_rl_training_data.jsonl"
        self.steps: list = []
        self._load_checkpoint()

    def should_train(self) -> tuple:
        """Check if conditions are right for a training step.

        Returns (should_train, reason).
        """
        # Check cooldown
        if self.steps:
            last = self.steps[-1]
            if last.timestamp:
                try:
                    last_dt = datetime.fromisoformat(last.timestamp)
                    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                    if elapsed < self.cfg.checkpoint_interval_seconds:
                        return False, f"cooldown: {elapsed:.0f}s < {self.cfg.checkpoint_interval_seconds}s"
                except Exception:
                    pass

        # Check training lock
        lock = self._state_path / "training.lock"
        if lock.exists():
            return False, "training.lock active"

        # Check minimum data
        code_diffs = self._load_code_diffs()
        if len(code_diffs) < self.cfg.min_examples:
            return False, f"insufficient code_diffs: {len(code_diffs)} < {self.cfg.min_examples}"

        return True, "ready"

    def step(self) -> dict:
        """Run one behavioral RL training step.

        Returns a status dict. Safe to call frequently -- it checks
        preconditions and skips when not ready.
        """
        should, reason = self.should_train()
        if not should:
            logger.debug(f"CodingRLTrainer step skipped: {reason}")
            step = TrainingStep(status="skipped", error=reason)
            self.steps.append(step)
            self._save_checkpoint()
            return {"status": "skipped", "reason": reason}

        t0 = time.time()
        version = self._next_version()
        step = TrainingStep(
            version=version, status="running",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # 1. Build reward-weighted training dataset
            examples, diffs_used, mean_reward = self._build_training_data()
            step.input_trades = diffs_used
            step.examples_built = examples
            step.mean_reward = round(mean_reward, 4)

            if examples == 0:
                step.status = "skipped"
                step.error = "no trainable examples after reward filtering"
                self.steps.append(step)
                self._save_checkpoint()
                return {"status": "skipped", "reason": step.error}

            logger.info(
                f"CodingRLTrainer step: {diffs_used} diffs -> {examples} examples "
                f"(mean_reward={mean_reward:.4f})"
            )

            # 2. Run reward-weighted SFT subprocess
            output_dir = Path(self.cfg.output_dir) / version
            output_dir.mkdir(parents=True, exist_ok=True)

            train_script = (
                Path(__file__).resolve().parent / "train_rocm.py"
            )

            if not train_script.exists():
                raise FileNotFoundError(f"train_rocm.py not found at {train_script}")

            # Build command
            cmd = [
                self.cfg.rocm_python,
                str(train_script),
                "--data", str(self._rl_dataset_path),
                "--output", str(output_dir),
                "--base", self.cfg.base_model,
                "--epochs", str(self.cfg.epochs),
                "--batch-size", str(self.cfg.batch_size),
                "--grad-accum", str(self.cfg.grad_accum),
                "--lr", str(self.cfg.learning_rate),
                "--max-seq-len", str(self.cfg.max_seq_length),
                "--lora-r", str(self.cfg.lora_r),
                "--lora-alpha", str(self.cfg.lora_alpha),
            ]
            # RX 7900 GRE has 16GB -- can run 7B without 4-bit quantization
            if "7900" in self._gpu_name():
                cmd.append("--no-4bit")

            logger.info(f"CodingRLTrainer: launching {version} training...")
            logger.debug(f"  cmd: {' '.join(cmd)}")

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.cfg.max_step_seconds,
                cwd=str(Path(__file__).resolve().parent.parent),
            )

            step.duration_s = round(time.time() - t0, 2)

            if proc.returncode == 0:
                adapter_path = str(output_dir / "adapter")
                step.status = "completed"
                step.adapter_path = adapter_path

                # Write training metadata
                meta = {
                    "version": version,
                    "training_type": "reward_weighted_sft",
                    "diffs_used": diffs_used,
                    "examples_built": examples,
                    "mean_reward": mean_reward,
                    "config": asdict(self.cfg),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "duration_s": step.duration_s,
                }
                with open(output_dir / "training_meta.json", "w") as f:
                    json.dump(meta, f, indent=2, default=str)

                logger.info(
                    f"CodingRLTrainer: {version} completed in {step.duration_s:.1f}s "
                    f"-> {adapter_path}"
                )
            else:
                step.status = "failed"
                step.error = f"train_rocm exit {proc.returncode}: {proc.stderr[-300:]}"
                logger.warning(f"CodingRLTrainer: {version} failed: {step.error}")

        except subprocess.TimeoutExpired:
            step.status = "failed"
            step.error = f"training timed out after {self.cfg.max_step_seconds}s"
            step.duration_s = round(time.time() - t0, 2)
            logger.warning(f"CodingRLTrainer: {version} timed out")
        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            step.duration_s = round(time.time() - t0, 2)
            logger.error(f"CodingRLTrainer: {version} error: {e}", exc_info=True)

        self.steps.append(step)
        self._save_checkpoint()

        return {
            "status": step.status,
            "version": version,
            "adapter_path": step.adapter_path,
            "trades_used": step.input_trades,
            "examples": step.examples_built,
            "mean_reward": step.mean_reward,
            "duration_s": step.duration_s,
            "error": step.error if step.status == "failed" else None,
        }

    def _build_training_data(self) -> tuple:
        """Build reward-weighted training JSONL from code_diffs and signal_history.

        Uses coding_reward_builder for scoring.

        Returns (num_examples, num_diffs_used, mean_reward).
        """
        code_diffs = self._load_code_diffs()
        if not code_diffs:
            return 0, 0, 0.0

        signal_history = self._load_signal_history()
        coach_report = self._load_coach_report()

        from training.coding_reward_builder import coding_composite_reward

        examples = []
        total_reward = 0.0
        diff_count = 0

        # Score each code diff and build examples
        for code_diff in code_diffs[-self.cfg.max_examples:]:
            # Compute composite reward for this diff using the reward builder
            reward, _ = coding_composite_reward(
                code_diffs=[code_diff],
                signal_history=signal_history,
                coach_report=coach_report,
            )
            total_reward += reward
            diff_count += 1

            # Build a training example from this diff
            example = self._diff_to_prompt(code_diff)
            if not example:
                continue

            # Attach reward metadata
            example["_reward"] = round(reward, 4)
            if "_file" not in example:
                example["_file"] = code_diff.get("file", "?")
            if "_action" not in example:
                example["_action"] = code_diff.get("action", "?")

            examples.append(example)

        if not examples:
            return 0, diff_count, 0.0

        # Write to JSONL
        self._rl_dataset_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._rl_dataset_path, "w") as f:
            for ex in examples:
                f.write(json.dumps(ex) + "\n")

        mean_reward = total_reward / max(diff_count, 1)
        return len(examples), diff_count, mean_reward

    def _diff_to_prompt(self, code_diff: dict) -> dict | None:
        """Convert a code diff into a prompt/response JSONL example.

        Returns dict with 'conversations' list (system/human/assistant format)
        plus '_reward' metadata, or None if unparseable.

        Example output:
        {
            "conversations": [
                {"from": "system", "value": "You are a coding agent..."},
                {"from": "human", "value": "File: src/utils.py\\nDiff: +3 lines..."},
                {"from": "assistant", "value": '{"action": "ACCEPT", "confidence": 0.9}'}
            ],
            "_reward": 0.75,
            "_file": "src/utils.py",
            "_action": "ACCEPT"
        }
        """
        file_path = code_diff.get("file", "?")
        action = code_diff.get("action", "UNKNOWN")
        reason = code_diff.get("reason", "unknown")
        changed_lines = code_diff.get("changed_lines", "")
        commit_msg = code_diff.get("commit_msg", "")

        if not file_path or not action:
            return None

        # Build context describing the diff
        context_lines = [
            f"File: {file_path}",
            f"Commit: {commit_msg}",
            f"Action: {action.upper()}",
            f"Changed lines:\n{changed_lines}",
            f"Task: Analyze this code change and output your assessment.",
        ]
        context = "\n".join(context_lines)

        # Build the decision that was made
        decision = (
            f'{{"action": "{action.upper()}", '
            f'"confidence": 0.65, '
            f'"reasoning": "{reason}"}}'
        )

        return {
            "conversations": [
                {
                    "from": "system",
                    "value": (
                        "You are a coding agent. You analyze code changes "
                        "and output your assessment as JSON: "
                        '{"action": "ACCEPT"|"REJECT"|"MODIFY", '
                        '"confidence": 0.0-1.0, '
                        '"reasoning": "brief explanation"}'
                    ),
                },
                {
                    "from": "human",
                    "value": context,
                },
                {
                    "from": "assistant",
                    "value": decision,
                },
            ],
        }

    def _load_code_diffs(self) -> list:
        """Load code_diffs from agent_state.json.
        Fallback: paper_state.json key 'commits'.
        """
        agent_path = self._state_path / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                code_diffs = state.get("code_diffs", [])
                if code_diffs:
                    return code_diffs
            except Exception:
                pass

        # Fallback: paper_state.json key "commits"
        paper_path = self._state_path / "paper_state.json"
        if paper_path.exists():
            try:
                state = json.loads(paper_path.read_text()) or {}
                commits = state.get("commits", [])
                if commits:
                    return commits
                commits = state.get("code_diffs", [])
                if commits:
                    return commits
            except Exception:
                pass

        return []

    def _load_signal_history(self) -> list:
        """Load signal_history from agent_state.json."""
        agent_path = self._state_path / "agent_state.json"
        if agent_path.exists():
            try:
                state = json.loads(agent_path.read_text()) or {}
                return state.get("_signal_history", [])
            except Exception:
                pass

        paper_path = self._state_path / "paper_state.json"
        if paper_path.exists():
            try:
                state = json.loads(paper_path.read_text()) or {}
                return state.get("signals", [])
            except Exception:
                pass

        return []

    def _load_coach_report(self) -> dict | None:
        """Load coach_report from coach_report.json."""
        coach_path = self._state_path / "coach_report.json"
        if coach_path.exists():
            try:
                return json.loads(coach_path.read_text())
            except Exception:
                pass
        return None

    def _load_checkpoint(self) -> None:
        """Load and restore self.steps from coding_rl_checkpoint.json."""
        if self._checkpoint_path.exists():
            try:
                data = json.loads(self._checkpoint_path.read_text())
                for s in data.get("steps", []):
                    self.steps.append(TrainingStep(**s))
            except Exception:
                pass

    def _save_checkpoint(self) -> None:
        """Save self.steps to coding_rl_checkpoint.json (last 20 entries)."""
        data = {
            "steps": [asdict(s) for s in self.steps[-20:]],  # keep last 20
        }
        tmp = self._checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, self._checkpoint_path)

    def _next_version(self) -> str:
        """Generate next version name: CODE-V1, CODE-V2, ..."""
        existing = [s.version for s in self.steps if s.status == "completed"]
        counter = len(existing) + 1
        prefix = self.cfg.version_prefix.replace("RL", "CODE") if self.cfg.version_prefix == "RL" else self.cfg.version_prefix
        return f"{prefix}-V{counter}"

    @staticmethod
    def _gpu_name() -> str:
        """Detect GPU name for training config adjustments."""
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.get_device_name(0) or "unknown"
        except Exception:
            pass
        return "unknown"

# ═══ Drop-in replacement for the cloud-only run_grpo


# ═══ Drop-in replacement for the cloud-only run_grpo
# ═════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════


class NotImplementedOnLocalGPU(RuntimeError):
    """Legacy stub — no longer raised. Kept for backward compat."""
    pass


# Backward-compat alias for code that imports GRPOConfig
GRPOConfig = RLTrainingConfig


def run_grpo(
    base_model: str = "",
    prompt_fn: Callable = None,
    reward_fn: Callable = None,
    cfg: Any = None,
    state_dir: str = "data",
    version: Optional[str] = None,
    mode: str = "trading",
) -> dict:
    """Drop-in replacement: delegates to BehavioralRLTrainer or CodingRLTrainer.

    This replaces the cloud-only GRPO stub with local reward-weighted SFT.
    Callers that previously received NotImplementedOnLocalGPU now get real training.

    Args:
        base_model: Base model for fine-tuning (unused but kept for compat).
        prompt_fn: Prompt function (unused but kept for compat).
        reward_fn: Reward function (unused but kept for compat).
        cfg: Training configuration.
        state_dir: Directory for state files.
        version: Version string (unused but kept for compat).
        mode: Training mode -- "trading" (default) or "coding".

    The prompt_fn and reward_fn args are accepted but ignored -- the behavioral
    RL trainer uses its own built-in prompt/reward from the trade journal.
    """
    if mode == "coding":
        from pathlib import Path
        output_dir = getattr(cfg, "output_dir", "models/finetune") if cfg else "models/finetune"
        trainer = CodingRLTrainer(
            state_dir=state_dir,
            output_dir=output_dir,
        )
        result = trainer.step()
        if result.get("status") == "completed":
            return {
                "status": "completed",
                "version": result.get("version", ""),
                "base_model": base_model,
                "reason": "CodingRL (reward-weighted SFT) completed locally",
                "adapter_path": result.get("adapter_path"),
            }
        return {
            "status": result.get("status", "skipped"),
            "reason": result.get("reason", result.get("error", "unknown")),
        }

    # Default: trading mode
    trainer = BehavioralRLTrainer(
        state_dir=state_dir,
        output_dir=getattr(cfg, "output_dir", "models/finetune") if cfg else "models/finetune",
    )
    result = trainer.step()
    if result.get("status") == "completed":
        return {
            "status": "completed",
            "version": result.get("version", ""),
            "base_model": base_model,
            "reason": "Behavioral RL (reward-weighted SFT) completed locally",
            "adapter_path": result.get("adapter_path"),
        }
    return {
        "status": result.get("status", "skipped"),
        "reason": result.get("reason", result.get("error", "unknown")),
    }
def run_grpo_from_objective(objective_path: str) -> dict:
    """Convenience: load training_objective.json and run behavioral RL.

    Reads mode from objective: "trading" or "coding".
    """
    with open(objective_path) as f:
        obj = json.load(f)

    mode = obj.get("mode", "trading")
    if mode == "coding":
        trainer = CodingRLTrainer(
            state_dir=obj.get("state_dir", "data"),
            output_dir=obj.get("output_dir", "models/finetune"),
        )
    else:
        trainer = BehavioralRLTrainer(
            state_dir=obj.get("state_dir", "data"),
            output_dir=obj.get("output_dir", "models/finetune"),
        )
    return trainer.step()

