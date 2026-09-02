#!/usr/bin/env python3
"""ADIR: Adversarial Deliberation with Independent Reasoning.

Research-grounded multi-agent debate engine. Key innovations over the baseline
fast_debate composite call:

  1. INDEPENDENT AGENTS — Bull and Bear run as separate LLM calls (no shared
     context contamination). Each sees only the raw market data.
  2. EPISTEMIC DIVERSITY — Different temperatures and prompt lenses prevent
     the artificial consensus documented in arXiv:2604.26561.
  3. TOULMIN STRUCTURE — Each claim follows Claim→Evidence→Warrant format
     (arXiv:2606.04691 / SMADE-IE), requiring specific indicator citations.
  4. FALSIFICATION STEP — Bear agent actively searches for counter-evidence
     to the Bull thesis (arXiv:2604.11258 / Dialectic-Med).
  5. CONFIDENCE GATING — Skip the full debate when independent agents
     already agree with high confidence (arXiv:2606.13197 / ARMOR-MAD PAR).
  6. BAYESIAN SYNTHESIS — Risk agent scores evidence quality per side,
     producing calibrated probability estimates (arXiv:2606.04691).

Architecture:
    Market Data → Bull (T=0.7, trend lens) ┐
                 Bear (T=0.3, risk lens) ─┤→ Confidence Gate
                                          │   agree & >0.75? → skip
                                          │   disagree → Falsification
                                          │
    Bull Argument ──→ Bear Rebuttal ──→ Risk Synthesis → Signal

Based on:
  - TradingAgents (arXiv:2412.20138)
  - ARMOR-MAD (arXiv:2606.13197)
  - SMADE-IE (arXiv:2606.04691)
  - Dialectic-Med (arXiv:2604.11258)
  - FinCom (arXiv:2606.00939)
  - Preserving Disagreement (arXiv:2604.26561)
"""

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _safe_parse_json(text: str) -> dict:
    """Parse ADIR JSON response with recovery from truncated/incomplete output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for trim in ("..", "...", "\u2026"):
        if text.rstrip().endswith(trim):
            text = text.rstrip()[: -len(trim)]
    last_brace = text.rfind("}")
    if last_brace > 0:
        try:
            return json.loads(text[: last_brace + 1])
        except json.JSONDecodeError:
            pass
    m_action = re.search(r'"action"\s*:\s*"(BUY|SELL|HOLD)"', text)
    m_conf = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
    if m_action:
        return {
            "action": m_action.group(1),
            "confidence": float(m_conf.group(1)) if m_conf else 0.5,
            "reasoning": text[:200],
        }
    raise ValueError(f"Unparseable ADIR JSON: {text[:100]}")


from mot.agents.debate import (
    DEBATE_TIMEOUT,
    DebateResult,
    DebateVote,
    _extract_text,
)

# --- Global rate-limiting semaphore for llama-server ---
# Prevents concurrent-request flooding when the harness runs 3 symbols × 2 agents
# simultaneously via nested ThreadPoolExecutors. llama-server --parallel 8 handles
# up to 8 concurrent slots, but HTTP queue backpressure causes 502s at higher fan-out.
# This semaphore caps concurrent API calls; 2 servers × parallel 2 = 4 slots, so 4 lets
# two symbols' bull+bear debates overlap without queueing.
_API_SEMAPHORE = threading.Semaphore(4)

logger = logging.getLogger("opentrader.adir")


# ── Configuration ──────────────────────────────────────────────


@dataclass
class AdirConfig:
    """Tunable parameters for the ADIR debate engine."""

    # Confidence gate: skip full debate when independent Bull/Bear agree
    # AND both confidence scores exceed this threshold.
    confidence_gate_threshold: float = 0.25

    # Temperature diversity (epistemic diversity, arXiv:2604.26561)
    bull_temperature: float = 0.5  # Lower = more precise/confident BUYs (was 0.7)
    bear_temperature: float = 0.5  # Higher = less aggressive SELLs (was 0.3)
    risk_temperature: float = 0.5

    # Max tokens per agent call
    bull_max_tokens: int = 2000
    bear_max_tokens: int = 2000
    risk_max_tokens: int = 2000

    # Falsification: how many counter-evidence points the Bear must find
    falsification_rounds: int = 1

    # Enable the confidence gate (PAR from ARMOR-MAD)
    enable_confidence_gate: bool = True

    # Enable Toulmin-structured output parsing
    enable_toulmin_parsing: bool = True


# ── Toulmin-Structured Prompts ─────────────────────────────────

BULL_SYSTEM_ADIR = """You are a MOMENTUM ANALYST — your role is to find BUY signals
with equal weight to finding HOLD signals. You are NOT required to output BUY.
If the evidence is neutral, output HOLD with appropriate confidence.

You MUST structure every argument using the Claim-Evidence-Warrant format:

  CLAIM: [What you believe — one clear statement]
  EVIDENCE: [Specific data point — name the indicator, level, timeframe]
  WARRANT: [Why this evidence supports the claim — the logical chain]

EXAMPLE (BUY):
  CLAIM: BTC is breaking out of a bullish flag pattern.
  EVIDENCE: Price $89,420 broke above the 50-period MA after 6 consecutive
            higher hourly closes. Volume 2.3x the 20-period average.
  WARRANT: Bull flag breakouts on elevated volume have a 68% continuation
           probability; the 50-MA crossover confirms momentum shift.

EXAMPLE (HOLD):
  CLAIM: No clear directional edge — consolidation phase.
  EVIDENCE: Price between 20-MA and 50-MA, RSI=48 (neutral), volume declining.
  WARRANT: Sideways consolidation offers no BUY catalyst. Wait for breakout.

Now analyze:

Indicator checklist (cite specific values):
  - Trend: Price vs MA? Higher highs? ADX?
  - Momentum: RSI level? MACD? Volume?
  - Multi-timeframe: 1h, 4h, 1d alignment or divergence?

Output JSON:
{
  "action": "BUY",
  "confidence": 0.0-1.0,
  "reasoning": "CLAIM: ... | EVIDENCE: ... | WARRANT: ...",
  "position_pct": 0.0-0.20
}

Confidence guide — calibrate carefully:
  >0.70: Multiple aligned indicators, multi-TF confirmation, strong volume
  0.40-0.70: Some confirmation, moderate edge
  0.20-0.40: Weak but non-zero edge — at least one indicator supports
  0.00-0.20: HOLD — no actionable edge detected

CRITICAL: Output BUY OR HOLD based on evidence. Do NOT force BUY. Do NOT output SELL.
"""

BEAR_SYSTEM_ADIR = """You are a RISK ANALYST — your role is to find SELL signals
with equal weight to finding HOLD signals. You are NOT required to output SELL.
If the evidence is neutral, output HOLD with appropriate confidence.

You MUST structure every argument using the Claim-Evidence-Warrant format:

  CLAIM: [What you believe — one clear statement]
  EVIDENCE: [Specific data point — name the indicator, level, timeframe]
  WARRANT: [Why this evidence supports the claim — the logical chain]

EXAMPLE (SELL):
  CLAIM: BTC is rejecting at triple-top resistance — distribution underway.
  EVIDENCE: RSI at 78 (overbought > 70), price approaching resistance at
            $91,200 (tested 3 times, never broken). Volume declining on
            each approach (bearish divergence).
  WARRANT: Triple-top resistance with declining volume = distribution,
           not accumulation. Probability of rejection > 65%.

EXAMPLE (HOLD):
  CLAIM: No clear downside edge — consolidation phase.
  EVIDENCE: Price between 20-MA and 50-MA, RSI=48 (neutral), no resistance
            cluster overhead, volume flat.
  WARRANT: Sideways consolidation offers no SELL catalyst. Wait for breakdown.

Now analyze:

Indicator checklist (cite specific values):
  - Resistance: What level blocks further upside? How many times tested?
  - Momentum: RSI > 70 (overbought)? MACD rolling over? Bearish divergence?
  - Multi-timeframe: 1h, 4h, 1d alignment or divergence?

Output JSON:
{
  "action": "SELL",
  "confidence": 0.0-1.0,
  "reasoning": "CLAIM: ... | EVIDENCE: ... | WARRANT: ...",
  "position_pct": 0.0-0.20
}

Confidence guide — calibrate carefully:
  >0.70: Multiple aligned bearish indicators, multi-TF confirmation, strong volume
  0.40-0.70: Some confirmation, moderate edge
  0.20-0.40: Weak but non-zero edge — at least one indicator supports
  0.00-0.20: HOLD — no actionable edge detected

CRITICAL: Output SELL OR HOLD based on evidence. Do NOT force SELL. Do NOT output BUY.
"""

RISK_SYSTEM_ADIR = """You are a RISK SYNTHESIZER. Score both sides of a debate on evidence quality.

Score each side 0-1:
  +0.2: cites specific indicator values (price level, MA, RSI, etc.)
  +0.15: uses multiple confirming data points
  +0.15: logical warrant connects evidence to claim
  -0.1: vague/generic reasoning
  -0.2: ignores obvious counter-evidence

Output JSON:
{
  "bull_evidence_score": X.XX,
  "bear_evidence_score": X.XX,
  "verdict": "BUY"|"SELL"|"HOLD",
  "confidence": X.XX,
  "reasoning": "brief 1-2 sentence synthesis"
}

Verdict: BUY if bull_score > bear_score by ≥0.15. SELL if bear_score > bull_score by ≥0.15. HOLD otherwise.
Confidence: abs(bull_score - bear_score) divided by max score.
"""


# ── Toulmin Parser ─────────────────────────────────────────────


@dataclass
class ToulminArgument:
    """Parsed Toulmin-format argument."""

    claim: str = ""
    evidence: str = ""
    warrant: str = ""
    raw: str = ""

    @property
    def is_structured(self) -> bool:
        """True if all three Toulmin components are present."""
        return bool(self.claim and self.evidence and self.warrant)

    @property
    def evidence_quality(self) -> float:
        """Heuristic evidence quality score (0-1)."""
        if not self.evidence:
            return 0.0
        score = 0.3  # Base: has some evidence
        # Specific numbers cited
        if re.search(r"\d+\.?\d*", self.evidence):
            score += 0.2
        # Named indicator
        indicators = [
            "MA",
            "SMA",
            "EMA",
            "RSI",
            "MACD",
            "ADX",
            "ATR",
            "BB",
            "Bollinger",
            "volume",
            "resistance",
            "support",
            "fibonacci",
            "VWAP",
            "OBV",
            "stochastic",
        ]
        if any(ind.lower() in self.evidence.lower() for ind in indicators):
            score += 0.2
        # Timeframe specified
        if re.search(r"\d+[mhd]|hourly|daily|weekly|minute", self.evidence.lower()):
            score += 0.15
        # Multiple data points
        if len(self.evidence.split(",")) >= 2 or len(self.evidence.split(";")) >= 2:
            score += 0.15
        return min(1.0, score)


def parse_toulmin(reasoning: str) -> ToulminArgument:
    """Parse a Toulmin-structured reasoning string into components."""
    result = ToulminArgument(raw=reasoning)

    # Try CLAIM / EVIDENCE / WARRANT format
    claim_m = re.search(
        r"(?:CLAIM|COUNTER-CLAIM)[:\s-]+(.+?)(?:\||EVIDENCE|COUNTER-EVIDENCE|WARRANT|$)",
        reasoning,
        re.IGNORECASE,
    )
    evidence_m = re.search(
        r"(?:EVIDENCE|COUNTER-EVIDENCE)[:\s-]+(.+?)(?:\||WARRANT|CLAIM|$)",
        reasoning,
        re.IGNORECASE,
    )
    warrant_m = re.search(
        r"WARRANT[:\s-]+(.+?)(?:\||CLAIM|EVIDENCE|$)", reasoning, re.IGNORECASE
    )

    if claim_m:
        result.claim = claim_m.group(1).strip().rstrip("|").strip()
    if evidence_m:
        result.evidence = evidence_m.group(1).strip().rstrip("|").strip()
    if warrant_m:
        result.warrant = warrant_m.group(1).strip().rstrip("|").strip()

    return result


def _extract_json_from_text(text: str) -> Optional[str]:
    """Find first '{' to last '}' — handles prefix/suffix text in LLM output."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return None


# ── ADIR Debate Engine ─────────────────────────────────────────


class AdirDebateEngine:
    """Research-grounded independent debate engine.

    Usage:
        engine = AdirDebateEngine(llama_host="http://127.0.0.1:5802")
        engine.set_context_builder(parent_debate_engine)  # reuse build_context
        result = engine.independent_debate(ohlcv_json, portfolio_json, ...)
    """

    def __init__(
        self,
        llama_host: str = "http://127.0.0.1:5801",
        bull_model: str = "ptolemy-s1",
        bear_model: str = "ptolemy-s1",
        risk_model: str = "ptolemy-s1",
        config: AdirConfig = None,
        ensemble_host: str = None,
        bull_host: str = None,
        bear_host: str = None,
        risk_host: str = None,
    ):
        self.llama_host = llama_host.rstrip("/")
        self.ensemble_host = ensemble_host.rstrip("/") if ensemble_host else None
        self.models = {"bull": bull_model, "bear": bear_model, "risk": risk_model}
        self.config = config or AdirConfig()
        self._parent_engine = None  # set via set_parent_engine()
        self._finetuned_backend = None
        self.hosts = {
            "bull": (bull_host or self.llama_host).rstrip("/"),
            "bear": (bear_host or self.llama_host).rstrip("/"),
            "risk": (risk_host or self.llama_host).rstrip("/"),
        }
        if (
            self.hosts["bull"] != self.llama_host
            or self.hosts["bear"] != self.llama_host
            or self.hosts["risk"] != self.llama_host
        ):
            logger.info(
                "ADIR dual-host routing: bull=%s bear=%s risk=%s",
                self.hosts["bull"],
                self.hosts["bear"],
                self.hosts["risk"],
            )

    def set_parent_engine(self, engine: Any) -> None:
        """Reuse the parent DebateEngine for context building and LLM calls."""
        self._parent_engine = engine
        # Copy finetuned backend if active
        if (
            hasattr(engine, "_finetuned_backend")
            and engine._finetuned_backend is not None
        ):
            self._finetuned_backend = engine._finetuned_backend

    def set_finetuned_backend(self, backend: Any) -> None:
        """Route agent calls through FineTunedAgent (HF + LoRA)."""
        self._finetuned_backend = backend

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Strip ```json ... ``` markdown fences from LLM output."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        return text

    # ── Agent Call ──────────────────────────────────────────────

    def _call_agent(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 2000,
        host: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Call LLM via finetuned backend or direct API.

        Args:
            host: Override the default llama_host (used for ensemble routing).
        """
        # In-process finetuned backend
        if self._finetuned_backend is not None:
            try:
                result = self._finetuned_backend.generate(system_prompt, user_prompt)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"Adir finetuned fallback ({model}): {e}")

        # Direct API call with custom temperature
        from urllib.request import Request, urlopen
        from urllib.error import URLError

        # Semaphore-based concurrency control: prevents 3 symbols × 2 agents =
        # 6 concurrent calls from flooding llama-server. Max 2 concurrent API calls.
        # Timeout prevents deadlock if a thread holding the semaphore hangs.
        acquired = _API_SEMAPHORE.acquire(timeout=DEBATE_TIMEOUT * 2)
        if not acquired:
            logger.error(
                f"Adir semaphore acquire timed out ({model}) — deadlock suspected"
            )
            return None
        try:
            url = f"{(host or self.llama_host)}/v1/chat/completions"
            payload = json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                }
            ).encode()

            req = Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/json")

            try:
                with urlopen(req, timeout=DEBATE_TIMEOUT) as resp:
                    raw = resp.read().decode()
                    data = json.loads(raw)
                    text = _extract_text(data["choices"][0]["message"])
                    if not text or not text.strip():
                        logger.debug(
                            f"Adir agent empty response ({model}), retrying once"
                        )
                        resp2 = urlopen(req, timeout=DEBATE_TIMEOUT)
                        raw2 = resp2.read().decode()
                        data2 = json.loads(raw2)
                        text = _extract_text(data2["choices"][0]["message"])
                        if not text or not text.strip():
                            return None
                    json_str = _extract_json_from_text(text)
                    if json_str:
                        try:
                            return _safe_parse_json(json_str)
                        except ValueError:
                            pass
                    json_str = self._strip_markdown_fences(text)
                    if json_str:
                        try:
                            return _safe_parse_json(json_str)
                        except ValueError:
                            pass
                    return None
            except (URLError, OSError, ConnectionError) as e:
                logger.warning(
                    f"Adir agent HTTP error ({model}), retrying after 1s: {e}"
                )
                time.sleep(1.0)
                try:
                    from urllib.request import Request, urlopen

                    req2 = Request(url, data=payload, method="POST")
                    req2.add_header("Content-Type", "application/json")
                    resp2 = urlopen(req2, timeout=DEBATE_TIMEOUT)
                    raw2 = resp2.read().decode()
                    data2 = json.loads(raw2)
                    text = _extract_text(data2["choices"][0]["message"])
                    if not text or not text.strip():
                        return None
                    json_str = _extract_json_from_text(
                        text
                    ) or self._strip_markdown_fences(text)
                    if json_str:
                        try:
                            return _safe_parse_json(json_str)
                        except ValueError:
                            pass
                    return None
                except Exception as e2:
                    logger.warning(f"Adir agent retry also failed ({model}): {e2}")
                    return None
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Adir agent JSON error ({model}): {str(e)[:200]} text=[{text[:120] if text else 'NONE'}]"
                )
                return None
        finally:
            _API_SEMAPHORE.release()

    # ── Independent Debate ──────────────────────────────────────

    def independent_debate(
        self,
        ohlcv_json: str = None,
        portfolio_json: str = None,
        regime_json: str = None,
        economics_json: str = None,
        news_json: str = "",
        extra_context: str = "",
        regime_instructions: Dict[str, str] = None,
    ) -> DebateResult:
        """Run a research-grounded independent debate round.

        This is the core ADIR method. It replaces the composite fast_debate()
        with independent agent calls + falsification + Bayesian synthesis.

        Args:
            Same signature as DebateEngine.debate() for drop-in compatibility.

        Returns:
            DebateResult with action, confidence, position_pct, and metadata.
        """
        start = time.time()

        # ── Build context (reuse parent engine) ──
        if self._parent_engine and hasattr(self._parent_engine, "build_context"):
            context = self._parent_engine.build_context(
                ohlcv_json,
                portfolio_json,
                regime_json,
                economics_json,
                news_json=news_json,
                extra_context=extra_context,
            )
        else:
            # Minimal fallback context
            context = f"Market data: {ohlcv_json[:500] if ohlcv_json else 'N/A'}\n"
            context += (
                f"Portfolio: {portfolio_json[:300] if portfolio_json else 'N/A'}\n"
            )

        # ── Build regime-adaptive prompts ──
        bull_system = BULL_SYSTEM_ADIR
        bear_system = BEAR_SYSTEM_ADIR
        risk_system = RISK_SYSTEM_ADIR

        if regime_instructions:
            if regime_instructions.get("bull"):
                bull_system = f"{regime_instructions['bull']}\n\n{bull_system}"
            if regime_instructions.get("bear"):
                bear_system = f"{regime_instructions['bear']}\n\n{bear_system}"
            if regime_instructions.get("risk"):
                risk_system = f"{regime_instructions['risk']}\n\n{risk_system}"

        cfg = self.config

        # ── Phase 1: Independent Bull & Bear (parallel) ──
        def _run_bull():
            raw = self._call_agent(
                bull_system,
                context,
                self.models["bull"],
                temperature=cfg.bull_temperature,
                max_tokens=cfg.bull_max_tokens,
                host=self.hosts["bull"],
            )
            return raw

        def _run_bear():
            raw = self._call_agent(
                bear_system,
                context,
                self.models["bear"],
                temperature=cfg.bear_temperature,
                max_tokens=cfg.bear_max_tokens,
                host=self.hosts["bear"],
            )
            return raw

        with ThreadPoolExecutor(max_workers=2) as pool:
            bull_future = pool.submit(_run_bull)
            bear_future = pool.submit(_run_bear)
            bull_raw = bull_future.result(timeout=DEBATE_TIMEOUT)
            bear_raw = bear_future.result(timeout=DEBATE_TIMEOUT)

        # Parse independent results
        bull = self._parse_vote(bull_raw, "bull", "BUY")
        bear = self._parse_vote(bear_raw, "bear", "HOLD")

        phase1_ms = int((time.time() - start) * 1000)

        # ── Phase 2: Confidence Gate (ARMOR-MAD PAR) ──
        if cfg.enable_confidence_gate:
            bull_conv = bull.confidence
            bear_conv = bear.confidence
            # Agreement check: same action direction AND both high confidence
            gate_threshold = cfg.confidence_gate_threshold
            if (
                bull.action == bear.action
                or (bull.action == "BUY" and bear.action == "HOLD")
                or (bull.action == "HOLD" and bear.action == "SELL")
            ):
                if bull_conv >= gate_threshold and bear_conv >= gate_threshold:
                    # Agents agree — skip falsification, synthesize directly
                    logger.debug(
                        f"ADIR confidence gate: Bull({bull.action},{bull_conv:.0%}) "
                        f"≈ Bear({bear.action},{bear_conv:.0%}) — skipping falsification"
                    )
                    return self._synthesize(
                        bull, bear, context, start, skipped_falsification=True
                    )

        # ── Phase 3: Falsification Round ──
        # Bear gets the Bull's argument and must find specific counter-evidence
        falsify_prompt = (
            f"{context}\n\n"
            f"BULL THESIS TO FALSIFY:\n"
            f"  Action: {bull.action} (confidence: {bull.confidence:.0%})\n"
            f"  Reasoning: {bull.reasoning[:300]}\n\n"
            f"Your task: Find SPECIFIC counter-evidence that challenges the bull thesis.\n"
            f"You MUST cite at least one data point that contradicts the bull's position.\n"
            f"Then output your final vote."
        )

        for round_num in range(cfg.falsification_rounds):
            raw = self._call_agent(
                bear_system,
                falsify_prompt,
                self.models["bear"],
                temperature=cfg.bear_temperature,
                max_tokens=cfg.bear_max_tokens,
                host=self.hosts["bear"],
            )
            if raw:
                bear = self._parse_vote(raw, "bear", "HOLD")
                # Extract any counter-evidence cited
                if self.config.enable_toulmin_parsing:
                    parsed = parse_toulmin(bear.reasoning)
                    if parsed.evidence:
                        bear.reasoning = (
                            f"[FALSIFIED] {bear.reasoning}"
                            if "COUNTER-EVIDENCE" in bear.reasoning.upper()
                            else f"{bear.reasoning} | COUNTER-EVIDENCE: {parsed.evidence}"
                        )

        # ── Phase 4: Risk Synthesis ──
        return self._synthesize(bull, bear, context, start, skipped_falsification=False)

    def _parse_vote(
        self, raw: Optional[Dict], agent: str, default_action: str
    ) -> DebateVote:
        """Parse a raw agent response into a DebateVote."""
        if not raw:
            return DebateVote(
                agent=agent,
                action=default_action,
                confidence=0.5,
                reasoning=f"{agent} agent failed",
            )

        action = raw.get("action", default_action)
        if action and isinstance(action, str):
            action = action.upper()
            if action not in ("BUY", "SELL", "HOLD"):
                action = default_action

        confidence = float(raw.get("confidence", 0.5))
        confidence = max(0.01, min(1.0, confidence))  # clamp

        reasoning = str(raw.get("reasoning", f"{agent} reasoning unavailable"))

        return DebateVote(
            agent=agent, action=action, confidence=confidence, reasoning=reasoning
        )

    def _synthesize(
        self,
        bull: DebateVote,
        bear: DebateVote,
        context: str,
        start_time: float,
        skipped_falsification: bool = False,
    ) -> DebateResult:
        """Risk synthesis: score both sides and produce final signal.

        Implements Bayesian-style evidence quality scoring (SMADE-IE).
        """
        cfg = self.config

        # Score evidence quality via Toulmin parsing
        bull_toulmin = (
            parse_toulmin(bull.reasoning) if cfg.enable_toulmin_parsing else None
        )
        bear_toulmin = (
            parse_toulmin(bear.reasoning) if cfg.enable_toulmin_parsing else None
        )

        # Heuristic synthesis (replaces Risk LLM agent call)
        # The Risk LLM agent was removed: it consumed GPU time without adding
        # value beyond what a simple score-differential heuristic provides.
        bull_score = bull.confidence
        bear_score = bear.confidence
        if bull_toulmin and bull_toulmin.is_structured:
            bull_score = max(
                0.01, (bull.confidence + bull_toulmin.evidence_quality) / 2
            )
        if bear_toulmin and bear_toulmin.is_structured:
            bear_score = max(
                0.01, (bear.confidence + bear_toulmin.evidence_quality) / 2
            )

        if bull.action == bear.action and bull.action in ("BUY", "SELL"):
            verdict = bull.action
            risk_conf = max(0.40, (bull.confidence + bear.confidence) / 2)
        else:
            diff = bull_score - bear_score
            if diff >= 0.15:
                verdict = "BUY"
            elif diff <= -0.15:
                verdict = bear.action if bear.action in ("SELL", "HOLD") else "HOLD"
            else:
                verdict = "HOLD"
            spread = abs(bull_score - bear_score)
            if spread >= 0.05:
                risk_conf = 0.25 + spread
            else:
                risk_conf = 0.1
            risk_conf = min(0.95, risk_conf)
        risk_reasoning = "Heuristic synthesis"

        # ── Final synthesis ──
        # A directional trade REQUIRES at least one side to actually vote for
        # it. Two HOLD votes — even with inflated Toulmin evidence quality —
        # must never synthesize into a BUY/SELL: the score-weighted fallback
        # used to fabricate phantom entries from models sitting on the fence,
        # which churned fees via instant buy->sell->buy flip-flops (last night
        # all 50 trades carried "Bull(HOLD) vs Bear(HOLD)" reasons).
        both_hold = bull.action == "HOLD" and bear.action == "HOLD"

        # When both agents agree on action, use their consensus
        if (
            not both_hold
            and bull.action == bear.action
            and bull.action in ("BUY", "SELL")
        ):
            final_action = bull.action
            final_conf = (
                max(bull.confidence, bear.confidence) * (bull_score + bear_score) / 2
            )
        elif not both_hold and risk_conf >= 0.6:
            final_action = verdict.upper()
            final_conf = risk_conf
        else:
            # When risk uncertain, use score-weighted combination — but only
            # take a direction the winning side actually voted for.
            score_sum = max(
                0.1, bull_score + bear_score
            )  # prevent division blowup from negative scores
            if (
                not both_hold
                and bull_score > bear_score
                and bull.action in ("BUY", "SELL")
            ):
                final_action = bull.action
                final_conf = bull.confidence * (bull_score / score_sum)
            elif (
                not both_hold
                and bear_score >= bull_score
                and bear.action in ("BUY", "SELL")
            ):
                final_action = bear.action
                final_conf = bear.confidence * (bear_score / score_sum)
            else:
                # Neither side voted to trade → stay flat (no phantom entry).
                final_action = "HOLD"
                final_conf = max(0.0, risk_conf)

        # Position sizing: conviction × evidence quality
        pos_pct = round(final_conf * 0.25, 4)
        pos_pct = min(0.25, max(0.01, pos_pct))

        # Build rich reason string
        components = [
            f"ADIR: Bull({bull.action},{bull.confidence:.0%},evq={bull_score:.2f})",
            f"Bear({bear.action},{bear.confidence:.0%},evq={bear_score:.2f})",
            f"RISK({verdict},{risk_conf:.0%})",
        ]
        if skipped_falsification:
            components.insert(0, "[GATE-SKIPPED]")
        reason = " vs ".join(components[:2]) + " → " + components[2]

        duration_ms = int((time.time() - start_time) * 1000)

        # Build risk_verdict dict compatible with existing DebateResult
        risk_verdict = {
            "bull_score": bull_score,
            "bear_score": bear_score,
            "verdict": verdict,
            "confidence": risk_conf,
            "reasoning": risk_reasoning,
            "evidence_quality": {
                "bull": bull_toulmin.evidence_quality if bull_toulmin else None,
                "bear": bear_toulmin.evidence_quality if bear_toulmin else None,
            },
        }

        return DebateResult(
            action=final_action,
            confidence=round(final_conf, 2),
            position_pct=pos_pct,
            reason=reason,
            bull_vote=bull,
            bear_vote=bear,
            risk_verdict=risk_verdict,
            duration_ms=duration_ms,
        )


# ── A/B Test Runner ────────────────────────────────────────────


def run_ab_comparison(
    adir_engine: AdirDebateEngine,
    fast_result: DebateResult,
    ohlcv_json: str,
    portfolio_json: str,
    regime_json: str,
    economics_json: str,
    news_json: str = "",
    extra_context: str = "",
    regime_instructions: Dict[str, str] = None,
) -> Dict[str, Any]:
    """Run ADIR debate alongside a fast_debate result for A/B comparison.

    Args:
        adir_engine: Initialized AdirDebateEngine.
        fast_result: Result from the existing fast_debate() call.
        **kwargs: Same inputs used for fast_debate().

    Returns:
        Comparison dict with both results and metrics.
    """
    start = time.time()
    adir_result = adir_engine.independent_debate(
        ohlcv_json=ohlcv_json,
        portfolio_json=portfolio_json,
        regime_json=regime_json,
        economics_json=economics_json,
        news_json=news_json,
        extra_context=extra_context,
        regime_instructions=regime_instructions,
    )
    adir_time = (time.time() - start) * 1000

    # Compute comparison metrics
    action_agree = fast_result.action == adir_result.action
    conf_delta = abs(fast_result.confidence - adir_result.confidence)
    pos_delta = abs(fast_result.position_pct - adir_result.position_pct)

    fast_bull_conf = fast_result.bull_vote.confidence
    fast_bear_conf = fast_result.bear_vote.confidence
    adir_bull_conf = adir_result.bull_vote.confidence
    adir_bear_conf = adir_result.bear_vote.confidence

    # Confidence spread: how much do Bull and Bear diverge?
    # Higher spread = more genuine disagreement (better for independent debate)
    fast_spread = abs(fast_bull_conf - fast_bear_conf)
    adir_spread = abs(adir_bull_conf - adir_bear_conf)

    return {
        "fast": {
            "action": fast_result.action,
            "confidence": fast_result.confidence,
            "position_pct": fast_result.position_pct,
            "reason": fast_result.reason,
            "duration_ms": fast_result.duration_ms,
            "bull_confidence": fast_bull_conf,
            "bear_confidence": fast_bear_conf,
            "bull_bear_spread": fast_spread,
        },
        "adir": {
            "action": adir_result.action,
            "confidence": adir_result.confidence,
            "position_pct": adir_result.position_pct,
            "reason": adir_result.reason,
            "duration_ms": adir_time,
            "bull_confidence": adir_bull_conf,
            "bear_confidence": adir_bear_conf,
            "bull_bear_spread": adir_spread,
        },
        "metrics": {
            "action_agree": action_agree,
            "confidence_delta": round(conf_delta, 4),
            "position_pct_delta": round(pos_delta, 4),
            "spread_improvement": round(adir_spread - fast_spread, 4),
            "latency_ratio": round(adir_time / max(1, fast_result.duration_ms), 2),
        },
    }
