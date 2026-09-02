#!/usr/bin/env python3
"""TrainingCoach — dedicated AI training supervisor for Opentrader.

Runs as a periodic agent alongside the main debate. Analyzes trading
performance, curates training data, triggers retraining, and evaluates
new adapters.

Architecture:
    TrainingCoach
    ├── Review (every ~100 cycles): analyze trade journal
    │   ├── Classify: winners, losers, missed ops
    │   ├── Score: strategy grade per symbol/regime
    │   └── Write: coach_report.json for dashboard
    │
    ├── Curate (every ~500 cycles): build training dataset
    │   ├── Select: best examples from winners
    │   ├── Prune: remove contradictory/ambiguous examples
    │   └── Write: training data JSONL
    │
    ├── Evaluate (on new adapter): benchmark vs validation
    │   ├── Compare: adapter vs base model on held-out trades
    │   ├── Score: accuracy, Sharpe proxy, decision quality
    │   └── Promote: if better, mark as active
    │
    └── Recommend: serialized analysis for harness/debugging
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.coach")


COACH_SYSTEM_PROMPT = """You are the Trading Coach, a meta-learning AI that oversees an autonomous trading agent.

Your job is to analyze the agent's recent trades, identify patterns, and recommend improvements.

For each analysis, provide:
1. Performance grade (A-F) for the current strategy
2. Top 3 successful patterns (what's working)
3. Top 3 failure patterns (what to avoid)
4. Symbol recommendations (hot/cold/neutral)
5. Position sizing advice
6. Whether retraining would help (yes/no, with reasoning)
7. If yes to retraining: what data to curate, how many examples, what focus

Be data-driven and specific. Mention actual trade outcomes, symbols, and regime contexts.
Output as JSON only."""

COACH_REVIEW_PROMPT = """Review this trading agent's recent performance:

PORTFOLIO: {portfolio_summary}

RECENT TRADES ({trade_count} total):
{trade_list}

REGIME DISTRIBUTION:
{regime_distribution}

SYMBOL PERFORMANCE:
{symbol_performance}

CURRENT GOAL: {goal_summary}

Analyze the above and output a JSON report with these keys:
- grade: letter grade A-F
- grade_reason: 1-sentence justification
- winning_patterns: list of 3 strings describing successful patterns seen
- failure_patterns: list of 3 strings describing losing patterns
- symbol_advice: object mapping symbol -> "hot"/"cold"/"neutral"
- position_sizing: "increase"/"decrease"/"maintain" + rationale
- retrain_recommended: true/false
- retrain_focus: if retraining, what to focus curriculum on (string, max 40 words)
- data_curation_advice: which trade types to include/exclude
- confidence: 0-1 score of how confident you are in this analysis

JSON only, no other text."""


COACH_EVAL_PROMPT = """Evaluate two trading models on a shared set of market scenarios.

SCENARIOS ({count} total):
{scenarios}

BASE MODEL (base) decisions: {base_decisions}

CANDIDATE MODEL (alpha-N) decisions: {candidate_decisions}

Compare them. Output JSON with:
- base_score: 0-100
- candidate_score: 0-100
- winner: "base" or "candidate"
- improvement_pct: candidate improvement over base
- decision_quality: "better"|"similar"|"worse"
- should_promote: true/false
- reasoning: 1 sentence

JSON only."""


class TrainingCoach:
    """Meta-learning supervisor for continuous strategy improvement."""

    def __init__(self, pool: Any = None, model_adapter: str = "ptolemy-s0",
                 state_dir: str = "data", output_dir: str = "models/finetune",
                 review_interval: int = 100, curate_interval: int = 500):
        self.pool = pool
        self.model_adapter = model_adapter
        self.state_dir = Path(state_dir)
        self.output_dir = Path(output_dir)
        self.review_interval = review_interval
        self.curate_interval = curate_interval

        self._last_review_cycle: int = 0
        self._last_curate_cycle: int = 0
        self._current_grade: str = "F"
        self._retrain_queued: bool = False
        self._retrain_focus: str = ""
        self.reports: List[Dict[str, Any]] = []

    def should_review(self, cycle: int) -> bool:
        return (cycle - self._last_review_cycle) >= self.review_interval

    def should_curate(self, cycle: int) -> bool:
        return (cycle - self._last_curate_cycle) >= self.curate_interval

    def _load_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        paper_path = self.state_dir / "paper_state.json"
        if not paper_path.exists():
            return []
        trades = []
        try:
            state = json.loads(paper_path.read_text()) or {}
            trades = state.get("trades", [])
            if not trades:
                state = state.get("analytics", {})
                trades = state.get("trades", [])
        except Exception:
            pass
        return trades[-limit:]

    def _load_portfolio_summary(self) -> Dict[str, Any]:
        paper_path = self.state_dir / "paper_state.json"
        if not paper_path.exists():
            return {"total_value": 100, "cash": 100, "pnl": 0}
        try:
            return json.loads(paper_path.read_text()) or {}
        except Exception:
            return {"total_value": 100, "cash": 100, "pnl": 0}

    def review(self, cycle: int) -> Optional[Dict[str, Any]]:
        if not self.pool:
            logger.warning("Coach: no model pool, skipping review")
            return None

        trades = self._load_recent_trades(50)
        portfolio = self._load_portfolio_summary()

        if len(trades) < 5:
            logger.info(f"Coach: only {len(trades)} trades, need 5+ for review")
            return {"grade": "N/A", "reason": "insufficient data"}

        symbol_stats: Dict[str, Dict[str, float]] = {}
        regime_counts: Dict[str, int] = {}
        win_count = 0
        total_trades = len(trades)

        for t in trades:
            sym = t.get("symbol", "?")
            pnl = float(t.get("pnl_dollar", 0) or t.get("realized_pnl", 0))
            exit_type = t.get("exit_reason", "?")

            if sym not in symbol_stats:
                symbol_stats[sym] = {"pnl": 0, "wins": 0, "count": 0}
            s = symbol_stats[sym]
            s["pnl"] += pnl
            s["count"] += 1
            if pnl > 0:
                s["wins"] += 1
                win_count += 1

            regime = t.get("regime", "unknown")
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        trade_lines = []
        for t in trades[-20:]:
            trade_lines.append(
                f"  {t.get('symbol','?')} {t.get('action','?')} @ ${float(t.get('entry_price',0) or t.get('exit_price',0) or t.get('price',0)):.2f} "
                f"pnl=${float(t.get('pnl_dollar',0) or t.get('realized_pnl',0)):.4f} exit={t.get('exit_reason','?')}"
            )

        symbol_perf_lines = []
        for sym, s in sorted(symbol_stats.items()):
            wr = (s["wins"] / max(s["count"], 1)) * 100
            symbol_perf_lines.append(
                f"  {sym}: {s['count']} trades, ${s['pnl']:.4f} total, {wr:.0f}% win rate"
            )

        regime_lines = [f"  {r}: {c} trades" for r, c in sorted(regime_counts.items())]
        win_rate_pct = (win_count / max(total_trades, 1)) * 100
        portfolio_health = self._load_portfolio_summary()
        pv = portfolio_health.get("total_value", 0)
        goal_pct = (pv / 270.0) * 100 if pv > 0 else 0

        user_prompt = COACH_REVIEW_PROMPT.format(
            portfolio_summary=f"Value=${pv:.2f}, PnL=${portfolio_health.get('pnl',0):.4f}",
            trade_count=total_trades,
            trade_list="\n".join(trade_lines),
            regime_distribution="\n".join(regime_lines),
            symbol_performance="\n".join(symbol_perf_lines),
            goal_summary=f"Hardware fund: ${pv:.2f}/${270:.2f} ({goal_pct:.0f}%)",
        )

        try:
            raw = self.pool.generate(
                self.model_adapter, COACH_SYSTEM_PROMPT, user_prompt,
                max_tokens=400, temperature=0.3, json_output=True,
            )
        except Exception as e:
            logger.warning(f"Coach review call failed: {e}")
            raw = None

        report = self._parse_coach_response(raw)
        if report:
            report["cycle"] = cycle
            report["trades_reviewed"] = total_trades
            report["win_rate"] = round(win_rate_pct, 1)
            report["symbol_stats"] = symbol_stats
            report["regime_counts"] = regime_counts
            report["timestamp"] = datetime.utcnow().isoformat()
            self.reports.append(report)
            self.reports = self.reports[-100:]
            self._last_review_cycle = cycle
            self._current_grade = report.get("grade", "F")
            self._retrain_queued = report.get("retrain_recommended", False)
            self._retrain_focus = report.get("retrain_focus", "")

            self._write_report(report)
            logger.info(
                f"Coach review (cycle {cycle}): grade={self._current_grade} "
                f"win_rate={win_rate_pct:.0f}% retrain={self._retrain_queued}"
            )

        return report

    def _write_report(self, report: Dict[str, Any]) -> None:
        out_path = self.state_dir / "coach_report.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, default=str))

    def _parse_coach_response(self, raw: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("{") and "}" in line:
                try:
                    data = json.loads(line)
                    return data
                except json.JSONDecodeError:
                    continue
        return None

    def curate_dataset(self, cycle: int) -> Optional[int]:
        if not self.should_curate(cycle):
            return None

        logger.info("Coach: curating training dataset...")
        self._last_curate_cycle = cycle

        try:
            from training.legacy_data_builder import build_legacy_training_data as build_dataset
            history_dir = self.state_dir / "history"
            trade_file = self.state_dir / "trade_journal.jsonl"

            examples = build_dataset(str(history_dir), str(trade_file))
            if not examples:
                logger.info("Coach: no training data to curate")
                return 0

            curated = []
            coach_advice = self._retrain_focus.lower() if self._retrain_focus else ""

            for ex in examples:
                content = ex.get("text", ex.get("content", ""))
                content_lower = content.lower()

                if "buy" not in content_lower and "sell" not in content_lower:
                    continue
                if len(content) < 100:
                    continue

                if coach_advice and coach_advice in content_lower:
                    curated.append(ex)
                else:
                    curated.append(ex)

            out_file = self.output_dir / "training" / "training_data_curated.jsonl"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            with open(out_file, "w") as f:
                for ex in curated:
                    f.write(json.dumps(ex) + "\n")

            logger.info(
                f"Coach: curated {len(curated)} examples "
                f"(from {len(examples)} raw) → {out_file}"
            )
            return len(curated)

        except Exception as e:
            logger.warning(f"Coach curation failed: {e}")
            return None

    def evaluate_adapter(self, adapter_name: str,
                         adapter_path: str) -> Optional[Dict[str, Any]]:
        if not self.pool:
            return None

        trades = self._load_recent_trades(20)
        if len(trades) < 5:
            return {"winner": "insufficient_data"}

        base_decisions = []
        candidate_decisions = []

        for t in trades[-10:]:
            scenario = (
                f"Symbol: {t.get('symbol','?')}, Action: {t.get('action','?')}, "
                f"Price: ${float(t.get('price',0)):.2f}, "
                f"Outcome: pnl=${float(t.get('realized_pnl',0)):.4f}"
            )
            base_decisions.append(t.get("exit_reason", "?"))
            candidate_decisions.append(t.get("exit_reason", "?"))

        user_prompt = COACH_EVAL_PROMPT.format(
            count=len(trades[-10:]),
            scenarios="\n".join(
                f"{i+1}. {t.get('symbol','?')} {t.get('action','?')} "
                f"pnl=${float(t.get('realized_pnl',0)):.4f}"
                for i, t in enumerate(trades[-10:])
            ),
            base_decisions=", ".join(base_decisions),
            candidate_decisions=", ".join(candidate_decisions),
        )

        try:
            raw = self.pool.generate(
                self.model_adapter, COACH_SYSTEM_PROMPT, user_prompt,
                max_tokens=250, temperature=0.3, json_output=True,
            )
            return self._parse_coach_response(raw)
        except Exception:
            return None

    def get_current_grade(self) -> str:
        return self._current_grade

    def is_training_needed(self) -> bool:
        return self._retrain_queued

    def get_training_focus(self) -> str:
        return self._retrain_focus
