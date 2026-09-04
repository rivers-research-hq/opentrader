#!/usr/bin/env python3
"""Deep Eval — 7-dimension evaluator for Ptolemy trading models.

Measures signal accuracy, reasoning coherence, confidence calibration,
adversarial robustness, debate quality, edge detection, and temporal
consistency. Each dimension produces a normalized 0-1 score.

Usage:
    python -m training.deep_eval <version> [--port 5805]
    python -m training.deep_eval run --all  # evaluate all candidates
"""
import json
import logging
import math
import os
import random
import re
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [deep_eval] %(levelname)s %(message)s")
logger = logging.getLogger("deep_eval")

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

LLAMA_BIN = Path("/home/mrc/src/modelai-llama.cpp/build-wmma/bin/llama-server")
EVAL_DIR = PROJECT / "data" / "eval"
REPORTS_DIR = EVAL_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

DIM_WEIGHTS = {
    "signal_accuracy": 0.25,
    "reasoning_coherence": 0.20,
    "confidence_calibration": 0.20,
    "adversarial_robustness": 0.15,
    "debate_quality": 0.10,
    "edge_detection": 0.05,
    "temporal_consistency": 0.05,
}

# Registry of ranging vs trending scenario types for edge detection
RANGING_TYPES = {"range_accumulation", "false_breakout", "mean_reversion"}
TRENDING_TYPES = {"breakout_entry", "trend_following", "flash_crash"}


@dataclass
class DeepEvalReport:
    version: str
    weighted_score: float
    per_dim_scores: Dict[str, float]
    breakdown: Dict[str, dict]
    flags: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "weighted_score": self.weighted_score,
            "per_dim_scores": self.per_dim_scores,
            "breakdown": self.breakdown,
            "flags": self.flags,
            "timestamp": self.timestamp,
        }


def load_registry() -> Dict:
    with open(PROJECT / "data" / "adapter_registry.json") as f:
        return json.load(f)


def save_registry(reg: Dict):
    with open(PROJECT / "data" / "adapter_registry.json", "w") as f:
        json.dump(reg, f, indent=2)


def _resolve_gguf_path(base_model_name: str) -> Path:
    """Resolve base model name (from registry) to absolute GGUF path."""
    candidates = [
        Path("/home/mrc/models") / base_model_name,
        Path("/home/mrc/models") / base_model_name / base_model_name,
        Path("/home/mrc/models/qwen2.5-7b-instruct") / base_model_name,
        Path("/home/mrc/models") / base_model_name / f"{base_model_name}.gguf",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Try a broader search
    matches = list(Path("/home/mrc/models").rglob(base_model_name))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Base model GGUF not found for: {base_model_name}")


class DeepEval:
    """Seven-dimension evaluator running a dedicated llama-server instance."""

    def __init__(self, version: str, base_gguf: str, lora_gguf: Optional[str] = None,
                 port: int = 5805, connect_only: bool = False):
        self.version = version
        self.base_gguf = Path(base_gguf).resolve()
        self.lora_gguf = Path(lora_gguf).resolve() if lora_gguf else None
        self.port = port
        self.connect_only = connect_only
        self._server_process: Optional[subprocess.Popen] = None

        if not connect_only:
            if not self.base_gguf.exists():
                raise FileNotFoundError(f"Base model not found: {self.base_gguf}")
            if self.lora_gguf and not self.lora_gguf.exists():
                logger.warning(f"LoRA GGUF not found: {self.lora_gguf} — running base only")
                self.lora_gguf = None

    def _spawn_llama_server(self):
        if self._server_process is not None:
            return

        cmd = [
            str(LLAMA_BIN),
            "--model", str(self.base_gguf),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--ctx-size", "8192",
            "--n-gpu-layers", "99",
            "--cache-type-k", "q8_0",
            "--cache-type-v", "q8_0",
            "--jinja",
            "--parallel", "1",
            "--cont-batching",
            "--threads", "8",
            "--batch-size", "4096",
            "--ubatch-size", "1024",
            "--temp", "0.3",
            "--top-p", "0.95",
            "--top-k", "64",
            "--repeat-penalty", "1.0",
            "--n-predict", "2048",
        ]
        if self.lora_gguf:
            cmd += ["--lora", str(self.lora_gguf), "--alias", self.version]

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = (
            f"{LLAMA_BIN.parent}:/opt/rocm/lib:/opt/rocm/hip/lib:"
            f"{env.get('LD_LIBRARY_PATH', '')}"
        )

        logger.info(f"Starting llama-server on :{self.port} for {self.version}...")
        self._server_process = subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_for_health(timeout=120)

    def _wait_for_health(self, timeout: int = 120):
        import urllib.error
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=5
                )
                if resp.status == 200:
                    logger.info(f"llama-server ready on :{self.port}")
                    return
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(2)
        raise TimeoutError(
            f"llama-server failed to start on :{self.port} within {timeout}s"
        )

    def _kill_server(self):
        if self._server_process is not None:
            logger.info("Stopping llama-server...")
            self._server_process.terminate()
            try:
                self._server_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._server_process.kill()
                self._server_process.wait()
            self._server_process = None
            time.sleep(2)

    def __enter__(self):
        if not self.connect_only:
            self._spawn_llama_server()
        return self

    def __exit__(self, *args):
        if not self.connect_only:
            self._kill_server()

    def _query_model(self, bars: List[dict], description: str,
                     temperature: float = 0.3, extra_ctx: str = ""
                     ) -> Optional[dict]:
        """Send scenario to model, parse SIGNAL JSON response.
        
        Returns parsed JSON dict or None on failure.
        """
        current_price = bars[-1]["close"] if bars else 100.0
        low = min(b["low"] for b in bars) if bars else 0
        high = max(b["high"] for b in bars) if bars else 0
        indicators = self._compute_indicators(bars)

        price_table = "\n".join(
            f"  [{i+1}] O:{b['open']:.2f} H:{b['high']:.2f} "
            f"L:{b['low']:.2f} C:{b['close']:.2f} V:{b.get('volume', 0):.0f}"
            for i, b in enumerate(bars)
        )

        prompt = (
            f"You are trading agent {self.version} analyzing a market scenario.\n\n"
            f"Scenario: {description}\n\n"
            f"Price data ({len(bars)} bars):\n{price_table}\n\n"
            f"Current price: ${current_price:.2f}\n"
            f"Range: ${low:.2f} - ${high:.2f}\n"
            f"{extra_ctx}\n"
            f"Computed indicators (from the price data above):\n"
            f"  RSI(14)={indicators['rsi_14']:.1f}, SMA(20)={indicators['sma_20']:.2f}, "
            f"MACD Line={indicators['macd_line']:.4f}, "
            f"MACD Signal={indicators['macd_signal']:.4f}, "
            f"Histogram={indicators['macd_histogram']:.4f}\n\n"
            f"Analyze the price action using these indicators. "
            f"Respond with EXACTLY this format:\n"
            f'SIGNAL: {{"action": "BUY|SELL|HOLD", "confidence": 0.0-1.0, '
            f'"reasoning": "Cite specific indicators with values", '
            f'"position_pct": 0.0-0.25}}\n'
        )

        try:
            data = json.dumps({
                "model": self.version,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 512,
            }).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/v1/chat/completions",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            sig_match = re.search(r'SIGNAL:\s*(\{.*\})', content, re.DOTALL)
            if sig_match:
                return json.loads(sig_match.group(1))

            json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))

            logger.warning(f"No SIGNAL JSON found in response: {content[:120]}")
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"Query error: {e}")
            return None

    @staticmethod
    def _compute_indicators(bars: List[dict]) -> Dict[str, float]:
        """Compute RSI(14), MACD(12,26,9), SMA(20) from bar data."""
        closes = [b["close"] for b in bars]
        result: Dict[str, float] = {}

        if len(closes) >= 20:
            result["sma_20"] = sum(closes[-20:]) / 20
        else:
            result["sma_20"] = sum(closes) / len(closes) if closes else 0.0

        if len(closes) >= 15:
            gains, losses = 0.0, 0.0
            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                if diff > 0:
                    gains += diff
                else:
                    losses -= diff
            avg_gain = gains / 14
            avg_loss = losses / 14
            result["rsi_14"] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
        else:
            result["rsi_14"] = 50.0

        if len(closes) >= 26:
            ema12 = DeepEval._ema(closes, 12)
            ema26 = DeepEval._ema(closes, 26)
            macd_line = ema12 - ema26
            result["macd_line"] = macd_line
            macd_values = []
            for i in range(len(closes) - 26, len(closes)):
                segment = closes[:i + 1]
                if len(segment) >= 26:
                    e12 = DeepEval._ema(segment, 12)
                    e26 = DeepEval._ema(segment, 26)
                    macd_values.append(e12 - e26)
            if len(macd_values) >= 9:
                result["macd_signal"] = DeepEval._ema(macd_values, 9)
            else:
                result["macd_signal"] = macd_line
            result["macd_histogram"] = macd_line - result["macd_signal"]
        else:
            result["macd_line"] = 0.0
            result["macd_signal"] = 0.0
            result["macd_histogram"] = 0.0

        return result

    @staticmethod
    def _ema(values: List[float], period: int) -> float:
        if len(values) < period:
            return sum(values) / len(values)
        k = 2.0 / (period + 1)
        ema = sum(values[:period]) / period
        for v in values[period:]:
            ema = v * k + ema * (1 - k)
        return ema

    @staticmethod
    def _extract_cited_indicators(reasoning: str) -> Dict[str, float]:
        """Extract indicator mentions with numeric values from reasoning text."""
        result: Dict[str, float] = {}

        # RSI: "RSI 65.2" or "RSI is 45" or "RSI=32.1"
        m = re.search(r'RSI[^0-9]*?(\d+\.?\d*)', reasoning, re.IGNORECASE)
        if m:
            result["rsi_14"] = float(m.group(1))

        # MACD: "MACD -2.5" or "MACD line 1.23"
        m = re.search(r'MACD[^-\d]*?(-?\d+\.?\d*)', reasoning, re.IGNORECASE)
        if m:
            result["macd_line"] = float(m.group(1))

        # SMA: "SMA20 142.5" or "SMA(20) 99.8" or "20 SMA at 500"
        m = re.search(
            r'(?:SMA|MA)\s*[( ]*20[) ]*\s*(?:is|at|of|:|=|≈|~)?\s*(\d+\.?\d*)',
            reasoning, re.IGNORECASE,
        )
        if not m:
            m = re.search(r'(?:20[-\s]*(?:period\s*)?SMA|20[-\s]*MA)\s*(?:is|at|of|:|=|≈|~)?\s*(\d+\.?\d*)',
                          reasoning, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 10 < val < 10000:
                result["sma_20"] = val

        # Price mentions: "price $104.46" or "current price 98.5"
        m = re.search(r'price\s*(?:\$)?(\d+\.?\d{1,2})', reasoning, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if val < 10000:
                result["last_price"] = val

        # ADX: "ADX 32.3"
        m = re.search(r'ADX[^0-9]*?(\d+\.?\d*)', reasoning, re.IGNORECASE)
        if m:
            result["adx"] = float(m.group(1))

        # Bollinger bandwidth: "BBw 0.026" or "BB width 0.04"
        m = re.search(r'BB[ w]*(?:width|band)?[^0-9]*?(\d+\.?\d*)', reasoning, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if val < 1.0:
                result["bb_width"] = val

        # Volume: "volume 12345" or "vol 5000"
        m = re.search(r'(?:volume|vol)[^0-9]*?(\d{3,}\.?\d*)', reasoning, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if val > 10:
                result["volume"] = val

        return result

    def dim1_signal_accuracy(self, scenarios: List) -> Tuple[float, dict]:
        """Direction-match via teacher_student.Scorer (weight: 0.25)."""
        from training.teacher_student import TeacherStudentFramework

        framework = TeacherStudentFramework()
        correct = 0
        total = 0
        scores = []

        for s in scenarios:
            raw = self._query_model(s.bars, s.description)
            if raw is None:
                continue
            from training.teacher_student import StudentResponse
            resp = StudentResponse(
                decision=raw.get("action", "HOLD").upper(),
                confidence=float(raw.get("confidence", 0.5)),
                reasoning=raw.get("reasoning", ""),
                position_pct=float(raw.get("position_pct", 0.0)),
            )
            score, is_correct, partial_credit, feedback = framework.score_decision(s, resp)
            scores.append(score)
            if is_correct:
                correct += 1
            total += 1

        if total == 0:
            return 0.0, {"error": "no valid responses", "total": 0}

        avg = sum(scores) / total
        return avg, {
            "correct": correct,
            "total": total,
            "accuracy": round(correct / total, 4),
            "avg_score": round(avg, 4),
        }

    def dim2_reasoning_coherence(self, scenarios: List) -> Tuple[float, dict]:
        """Check cited indicators vs actual computed values (weight: 0.20)."""
        scores = []
        cited_count = 0
        empty_count = 0

        for s in scenarios:
            raw = self._query_model(s.bars, s.description)
            if raw is None:
                continue
            reasoning = raw.get("reasoning", "")
            if not reasoning:
                scores.append(0.5)
                empty_count += 1
                continue

            computed = self._compute_indicators(s.bars)
            cited = self._extract_cited_indicators(reasoning)

            if not cited:
                # No numeric indicators cited — check for qualitative mentions
                qual_score = 0.35  # below the 0.5 neutral baseline
                reasoning_lower = reasoning.lower()
                mentions = 0
                for term in ("rsi", "macd", "sma", "adx", "bollinger", "volume"):
                    if term in reasoning_lower:
                        mentions += 1
                if mentions >= 2:
                    qual_score = 0.45  # at least they mentioned indicators
                scores.append(qual_score)
                empty_count += 1
                continue

            cited_count += 1
            matches = 0
            for ind, cited_val in cited.items():
                actual = computed.get(ind)
                if actual is not None:
                    denom = max(1.0, abs(actual))
                    if abs(cited_val - actual) / denom < 0.15:
                        matches += 1
            scores.append(matches / len(cited))

        if not scores:
            return 0.0, {"error": "no responses with reasoning", "total": 0}

        avg = sum(scores) / len(scores)
        return avg, {
            "scenarios": len(scores),
            "avg_coherence": round(avg, 4),
            "with_cited_values": cited_count,
            "without_cited_values": empty_count,
        }

    def dim3_confidence_calibration(self, scenarios: List) -> Tuple[float, dict]:
        """Expected Calibration Error across decile bins (weight: 0.20)."""
        predictions: List[Tuple[float, bool]] = []
        from training.teacher_student import TeacherStudentFramework

        framework = TeacherStudentFramework()

        for s in scenarios:
            raw = self._query_model(s.bars, s.description)
            if raw is None:
                continue
            confidence = float(raw.get("confidence", 0.5))
            decision = raw.get("action", "HOLD").upper()
            is_correct = decision == s.ground_truth
            predictions.append((confidence, is_correct))

        if len(predictions) < 10:
            return 0.0, {"error": f"too few predictions ({len(predictions)})", "total": len(predictions)}

        bins = [[] for _ in range(10)]
        for conf, correct in predictions:
            bin_idx = min(9, int(conf * 10))
            bins[bin_idx].append((conf, correct))

        ece = 0.0
        bin_stats = []
        for i, bin_data in enumerate(bins):
            if not bin_data:
                bin_stats.append({"bin": i, "count": 0, "avg_conf": 0, "accuracy": 0})
                continue
            avg_conf = sum(p[0] for p in bin_data) / len(bin_data)
            accuracy = sum(1 for p in bin_data if p[1]) / len(bin_data)
            bin_ece = abs(accuracy - avg_conf)
            ece += bin_ece * (len(bin_data) / len(predictions))
            bin_stats.append({
                "bin": i, "count": len(bin_data),
                "avg_conf": round(avg_conf, 4),
                "accuracy": round(accuracy, 4),
                "bin_ece": round(bin_ece, 4),
            })

        calibration_score = 1.0 - ece
        return max(0.0, calibration_score), {
            "ece": round(ece, 4),
            "calibration_score": round(calibration_score, 4),
            "total_predictions": len(predictions),
            "bins": bin_stats,
        }

    def dim4_adversarial_robustness(self, scenarios: List) -> Tuple[float, dict]:
        """Apply ±5% noise + 3-bar contradiction; measure flip_rate (weight: 0.15)."""
        from training.teacher_student import TeacherStudentFramework, StudentResponse
        import copy

        framework = TeacherStudentFramework()
        base_decisions: List[Optional[str]] = []
        base_scores: List[float] = []

        for s in scenarios:
            raw = self._query_model(s.bars, s.description)
            if raw is None:
                base_decisions.append(None)
                base_scores.append(0.0)
            else:
                base_decisions.append(raw.get("action", "HOLD").upper())
                resp = StudentResponse(
                    decision=base_decisions[-1],
                    confidence=float(raw.get("confidence", 0.5)),
                )
                score, _, _, _ = framework.score_decision(s, resp)
                base_scores.append(score)

        adv_scores: List[float] = []
        flips = 0
        total_compared = 0

        for i, s in enumerate(scenarios):
            if base_decisions[i] is None:
                continue
            adv_bars = copy.deepcopy(s.bars)

            for b in adv_bars:
                b["open"] *= random.uniform(0.95, 1.05)
                b["high"] *= random.uniform(0.95, 1.05)
                b["low"] *= random.uniform(0.95, 1.05)
                b["close"] *= random.uniform(0.95, 1.05)

            gt_dir = s.ground_truth
            last_close = adv_bars[-1]["close"]
            if gt_dir == "BUY":
                for j in range(1, 4):
                    idx = max(0, len(adv_bars) - 1 - j)
                    adv_bars[idx]["close"] = last_close * 0.97
                    adv_bars[idx]["high"] = last_close * 0.98
                    adv_bars[idx]["low"] = last_close * 0.96
            elif gt_dir == "SELL":
                for j in range(1, 4):
                    idx = max(0, len(adv_bars) - 1 - j)
                    adv_bars[idx]["close"] = last_close * 1.03
                    adv_bars[idx]["high"] = last_close * 1.04
                    adv_bars[idx]["low"] = last_close * 1.02
            else:
                move = last_close * 0.03
                for j in range(1, 4):
                    idx = max(0, len(adv_bars) - 1 - j)
                    adv_bars[idx]["close"] = last_close + move * (-1 if j % 2 else 1)
                    adv_bars[idx]["high"] = max(adv_bars[idx]["close"], adv_bars[idx]["high"])
                    adv_bars[idx]["low"] = min(adv_bars[idx]["close"], adv_bars[idx]["low"])

            adv_ctx = "WARNING: Recent price action contradicts the established trend."
            raw_adv = self._query_model(adv_bars, s.description, extra_ctx=adv_ctx)
            if raw_adv is None:
                continue
            adv_dec = raw_adv.get("action", "HOLD").upper()
            resp = StudentResponse(decision=adv_dec, confidence=float(raw_adv.get("confidence", 0.5)))
            score, _, _, _ = framework.score_decision(s, resp)
            adv_scores.append(score)

            if adv_dec != base_decisions[i]:
                flips += 1
            total_compared += 1

        flip_rate = flips / max(1, total_compared)
        avg_adv_score = sum(adv_scores) / max(1, len(adv_scores))
        robustness = (1.0 - flip_rate) * 0.5 + avg_adv_score * 0.5

        return robustness, {
            "flip_rate": round(flip_rate, 4),
            "flips": flips,
            "total_compared": total_compared,
            "avg_adv_score": round(avg_adv_score, 4),
            "robustness": round(robustness, 4),
        }

    def dim5_debate_quality(self, scenarios: List) -> Tuple[float, dict]:
        """Run AdirDebateEngine per scenario; Bull↔BUY/Bear↔SELL alignment (weight: 0.10)."""
        try:
            from mot.agents.adir_debate import AdirDebateEngine, AdirConfig
        except ImportError:
            logger.warning("ADIR debate engine not available — skipping dim5")
            return 0.0, {"error": "ADIR unavailable", "flag": "ADIR_FAILED"}

        config = AdirConfig(
            enable_confidence_gate=True,
            enable_toulmin_parsing=False,
        )
        host = f"http://127.0.0.1:{self.port}"
        engine = AdirDebateEngine(
            llama_host=host,
            bull_model=self.version,
            bear_model=self.version,
            risk_model=self.version,
            config=config,
        )

        total_bull_align = 0
        total_bear_align = 0
        total = 0
        flags = []

        for s in scenarios:
            try:
                ohlcv_json = json.dumps({
                    "symbol": "SCENARIO",
                    "timeframe": "1h",
                    "bars": s.bars,
                    "current_price": s.bars[-1]["close"] if s.bars else 100.0,
                })
                portfolio_json = json.dumps({
                    "cash": 100000.0,
                    "total_value": 100000.0,
                    "positions": {},
                    "position_count": 0,
                })
                regime_data = {
                    "regime": s.scenario_type,
                    "confidence": 0.5,
                    "description": s.description,
                }
                regime_json = json.dumps(regime_data)
                economics_json = json.dumps({"source": "simulated", "volatility": 0.15})

                result = engine.independent_debate(
                    ohlcv_json=ohlcv_json,
                    portfolio_json=portfolio_json,
                    regime_json=regime_json,
                    economics_json=economics_json,
                )

                bull_act = result.bull_vote.action
                bear_act = result.bear_vote.action
                bull_conf = getattr(result.bull_vote, "confidence", 0.5)
                bear_conf = getattr(result.bear_vote, "confidence", 0.5)

                # Non-trivial alignment: action matches AND confidence sorted correctly
                bull_full = bull_act == "BUY" and bull_conf > bear_conf + 0.1
                bear_full = bear_act in ("SELL", "HOLD") and bear_conf > bull_conf + 0.1
                bull_weak = bull_act == "BUY" and not bull_full  # correct action, wrong confidence
                bear_weak = bear_act in ("SELL", "HOLD") and not bear_full

                if bull_full:
                    total_bull_align += 1.0
                elif bull_weak:
                    total_bull_align += 0.5

                if bear_full:
                    total_bear_align += 1.0
                elif bear_weak:
                    total_bear_align += 0.5

                total += 1

            except Exception as e:
                logger.warning(f"ADIR debate failed for scenario: {e}")
                flags.append(f"ADIR_FAILED_{total}")

        if total == 0:
            return 0.0, {"error": "all ADIR debates failed", "flag": "ADIR_FAILED"}

        bull_rate = total_bull_align / total
        bear_rate = total_bear_align / total
        score = (bull_rate + bear_rate) / 2
        score = min(score, 0.95)  # cap — never claim perfection

        return score, {
            "bull_alignment": round(bull_rate, 4),
            "bear_alignment": round(bear_rate, 4),
            "bull_ok": total_bull_align,
            "bear_ok": total_bear_align,
            "total": total,
            "flags": flags,
        }

    def dim6_edge_detection(self, scenarios: List) -> Tuple[float, dict]:
        """true_HOLD_rate(ranging) + true_ACTIVE_rate(trending) (weight: 0.05)."""
        from training.teacher_student import StudentResponse

        ranging_holds = 0
        ranging_total = 0
        trending_active = 0
        trending_total = 0

        for s in scenarios:
            raw = self._query_model(s.bars, s.description)
            if raw is None:
                continue
            dec = raw.get("action", "HOLD").upper()

            if s.scenario_type in RANGING_TYPES:
                ranging_total += 1
                if dec == "HOLD":
                    ranging_holds += 1
            elif s.scenario_type in TRENDING_TYPES:
                trending_total += 1
                if dec in ("BUY", "SELL"):
                    trending_active += 1

        hold_rate = ranging_holds / max(1, ranging_total)
        active_rate = trending_active / max(1, trending_total)
        score = (hold_rate + active_rate) / 2

        return score, {
            "true_HOLD_rate": round(hold_rate, 4),
            "true_ACTIVE_rate": round(active_rate, 4),
            "ranging_holds": ranging_holds,
            "ranging_total": ranging_total,
            "trending_active": trending_active,
            "trending_total": trending_total,
        }

    def dim7_temporal_consistency(self, scenarios: List) -> Tuple[float, dict]:
        """Query twice at temp=0.1; measure agreement rate (weight: 0.05)."""
        import copy

        agreements = 0
        total = 0

        for s in scenarios:
            raw1 = self._query_model(s.bars, s.description, temperature=0.1)
            if raw1 is None:
                continue
            raw2 = self._query_model(s.bars, s.description, temperature=0.1)
            if raw2 is None:
                continue

            dec1 = raw1.get("action", "HOLD").upper()
            dec2 = raw2.get("action", "HOLD").upper()
            conf1 = float(raw1.get("confidence", 0.5))
            conf2 = float(raw2.get("confidence", 0.5))

            decision_match = dec1 == dec2
            conf_spread = abs(conf1 - conf2)
            conf_match = conf_spread <= 0.2

            if decision_match and conf_match:
                agreements += 1
            elif decision_match:
                agreements += 0.6
            elif conf_match:
                agreements += 0.3

            total += 1

        if total == 0:
            return 0.0, {"error": "no valid responses", "total": 0}

        score = agreements / total
        return score, {
            "agreement_rate": round(score, 4),
            "total_compared": total,
        }

    def run(self) -> DeepEvalReport:
        """Run all 7 dimensions and produce a DeepEvalReport."""
        from training.programmatic_teacher import ProgrammaticTeacher

        logger.info(f"Running DeepEval for {self.version}...")
        start = time.time()

        teacher = ProgrammaticTeacher(seed=42)

        dim_fns = {
            "signal_accuracy": (self.dim1_signal_accuracy, teacher.generate_batch(200)),
            "reasoning_coherence": (self.dim2_reasoning_coherence, teacher.generate_batch(200)),
            "confidence_calibration": (self.dim3_confidence_calibration, teacher.generate_batch(200)),
            "adversarial_robustness": (self.dim4_adversarial_robustness, teacher.generate_batch(50)),
            "debate_quality": (self.dim5_debate_quality, teacher.generate_batch(30)),
            "edge_detection": (self.dim6_edge_detection, teacher.generate_batch(100)),
            "temporal_consistency": (self.dim7_temporal_consistency, teacher.generate_batch(30)),
        }

        per_dim_scores: Dict[str, float] = {}
        breakdown: Dict[str, dict] = {}
        flags: List[str] = []

        for dim_name in [
            "signal_accuracy", "reasoning_coherence", "confidence_calibration",
            "adversarial_robustness", "debate_quality", "edge_detection",
            "temporal_consistency",
        ]:
            fn, scens = dim_fns[dim_name]
            logger.info(f"  Dimension: {dim_name} ({len(scens)} scenarios)...")
            dim_start = time.time()
            score, detail = fn(scens)
            elapsed = time.time() - dim_start
            per_dim_scores[dim_name] = round(score, 4)
            detail["elapsed_s"] = round(elapsed, 1)
            breakdown[dim_name] = detail

            dim_flag = detail.get("flag") or detail.get("flags")
            if dim_flag:
                if isinstance(dim_flag, list):
                    flags.extend(dim_flag)
                else:
                    flags.append(dim_flag)

            logger.info(f"    → {dim_name}: {score:.4f} ({elapsed:.1f}s)")

        weighted = sum(
            per_dim_scores.get(d, 0.0) * DIM_WEIGHTS.get(d, 0.0)
            for d in DIM_WEIGHTS
        )

        report = DeepEvalReport(
            version=self.version,
            weighted_score=round(weighted, 4),
            per_dim_scores=per_dim_scores,
            breakdown=breakdown,
            flags=flags,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        elapsed = time.time() - start
        logger.info(f"DeepEval complete: {self.version} weighted={weighted:.4f} ({elapsed:.0f}s)")
        return report


def evaluate_version(version: str, port: int = 5805, save: bool = True) -> DeepEvalReport:
    """Evaluate a single version by looking up registry paths and running DeepEval."""
    reg = load_registry()
    if version not in reg:
        raise ValueError(f"Version {version} not found in registry")

    entry = reg[version]
    base_name = entry.get("base_model", "")
    gguf_rel = entry.get("gguf_path", "")

    base_gguf = _resolve_gguf_path(base_name)
    lora_gguf = str(PROJECT / gguf_rel) if gguf_rel else None

    evaluator = DeepEval(version=version, base_gguf=str(base_gguf),
                          lora_gguf=lora_gguf, port=port)

    with evaluator:
        report = evaluator.run()

    if save:
        save_report(report)

    return report


def save_report(report: DeepEvalReport):
    """Save DeepEval report to disk."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{report.version}_deep_{ts}.json"
    with open(path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f"Report saved: {path}")


def load_report(version: str) -> Optional[dict]:
    """Load the latest deep_eval report for a version."""
    reports = sorted(
        REPORTS_DIR.glob(f"{version}_deep_*.json"),
        key=os.path.getmtime, reverse=True,
    )
    if not reports:
        return None
    with open(reports[0]) as f:
        return json.load(f)


def cli():
    import argparse
    parser = argparse.ArgumentParser(description="Deep Eval — 7-dimension model evaluator")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["evaluate", "status", "list", "run"])
    parser.add_argument("version", nargs="?", help="Model version to evaluate")
    parser.add_argument("--port", type=int, default=5805, help="llama-server port")
    parser.add_argument("--all", action="store_true", help="Evaluate all non-active candidates")
    args = parser.parse_args()

    if args.action == "status":
        reg = load_registry()
        for v, e in reg.items():
            report = load_report(v)
            score = report["weighted_score"] if report else "N/A"
            print(f"  {v}: {e['status']} deep_eval={score}")
        return

    if args.action == "list":
        for p in sorted(REPORTS_DIR.glob("*_deep_*.json")):
            print(p.name)
        return

    if args.action == "evaluate":
        if args.version:
            report = evaluate_version(args.version, port=args.port)
            print(f"DeepEval {report.version}: weighted_score={report.weighted_score}")
            for d, s in report.per_dim_scores.items():
                print(f"  {d}: {s}")
            return
        elif args.all:
            reg = load_registry()
            candidates = {v: e for v, e in reg.items() if e.get("status") != "active"}
            for v in candidates:
                print(f"\nEvaluating {v}...")
                report = evaluate_version(v, port=args.port)
                print(f"  → {report.version}: {report.weighted_score}")
            return
        else:
            print("Specify a version or --all")
            sys.exit(1)

    if args.action == "run":
        reg = load_registry()
        active_version = next((v for v, e in reg.items() if e.get("status") == "active"), None)
        best_version = None
        best_score = -1

        for v in [k for k in reg.keys() if k != active_version]:
            print(f"\nEvaluating {v}...")
            report = evaluate_version(v, port=args.port)
            print(f"  → {report.version}: {report.weighted_score}")
            if report.weighted_score > best_score:
                best_score = report.weighted_score
                best_version = v

        if best_version and active_version:
            active_report = load_report(active_version)
            active_deep = active_report["weighted_score"] if active_report else 0.0
            if best_score >= active_deep + 3.0:
                print(f"\n{best_version} ({best_score}) beats {active_version} ({active_deep}) by ≥3.0 — promotion candidate")
            else:
                print(f"\n{best_version} ({best_score}) does not beat {active_version} ({active_deep}) by ≥3.0 — no promotion")
        return


if __name__ == "__main__":
    import random  # needed by dim4
    cli()
