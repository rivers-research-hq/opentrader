#!/usr/bin/env python3
"""Multi-Agent Debate Engine — Bull/Bear/Risk agents debate → final signal.

Architecture:
  Bull Agent  → makes the bullish case (BUY)
  Bear Agent  → makes the bearish case (SELL/HOLD) — independent of Bull
  Risk Agent  → scores both arguments → weighted verdict
  Synthesis   → final Signal with confidence

Parallel mode: Bull + Bear run concurrently (2 threads → ~3.7s),
Risk runs after both complete (~3.7s). Total LLM time: ~7.4s (was ~11s).

Based on TradingAgents (arXiv:2412.20138) with ATLANTIS orchestration pattern.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("opentrader.debate")

DEBATE_TIMEOUT = 600  # seconds per agent call (GPU1 27B model needs 10 min)

import threading
_API_SEMAPHORE = threading.Semaphore(2)

def _extract_json_from_text(text: str) -> Optional[str]:
    """Extract JSON from a response that may be wrapped in markdown fences or other text."""
    match = re.search(r"```(?:json)?\s*\n?(.*)\s*\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            json.loads(match.group())
            return match.group()
        except json.JSONDecodeError:
            pass
    return None

def _safe_parse_json(text: str) -> Dict[str, Any]:
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

def _strip_markdown_fences(text: str) -> str:
    """Strip markdown code fences from LLM response."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?\u2026$", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text



@dataclass
class DebateVote:
    """A single agent's vote in a debate session."""

    agent: str
    action: str  # BUY / SELL / HOLD
    confidence: float  # 0-1
    reasoning: str
    score: float = 0.0  # assigned by risk agent


@dataclass
class DebateResult:
    """Final output of a debate session."""

    action: str
    confidence: float
    position_pct: float
    reason: str
    bull_vote: DebateVote
    bear_vote: DebateVote
    risk_verdict: Dict[str, float]
    duration_ms: int = 0


# ── Response Text Extraction ──────────────────────────────────


def _extract_text(message: dict) -> str:
    """Extract text from LLM response, handling models that use reasoning_content.

    Some models (Qwen Revised, DeepSeek R1, Qwythos-MTP) put their output in
    `reasoning_content` with an empty `content`. This normalizes to always
    return usable text.
    """
    content = message.get("content", "") or ""
    if content.strip():
        return content

    # Fallback: reasoning_content (Qwen thinking mode, DeepSeek R1, etc.)
    reasoning = message.get("reasoning_content", "") or ""
    if not reasoning.strip():
        return ""

    # If reasoning_content is a thinking trace, try to extract the final
    # structured output that the model wrote near the end.
    lines = reasoning.split("\n")
    formatted_lines = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # Skip meta-commentary / thinking preamble lines
        if any(
            s.startswith(p)
            for p in (
                "Alright,",
                "Let me",
                "I need",
                "Now,",
                "I will",
                "I'll",
                "I can",
                "The user",
                "I'm",
                "I think",
                "I should",
                "I have",
                "First,",
                "Next,",
                "Then,",
                "Finally,",
                "I note",
                "I see",
                "I understand",
                "I realize",
                "I notice",
                "I'm going",
                "I am going",
                "I am",
                "I want",
                "I expect",
                "I believe",
                "I suppose",
                "Here",
                "This",
                "That",
            )
        ):
            continue
        # Keep lines that look like structured output
        formatted_lines.append(s)

    if formatted_lines:
        return "\n".join(formatted_lines)

    # If no formatted lines extracted, return the last 2000 chars of reasoning
    # (the model typically outputs final answer at the end of its thinking)
    return reasoning[-2000:] if len(reasoning) > 2000 else reasoning


# ── Agent Prompts ─────────────────────────────────────────────

BULL_SYSTEM = """You are the BULL — argue ONLY for BUYING. Never output SELL or HOLD.

Analyze with a BUY bias:
1. Trend: higher highs/lows? Breakout above resistance? Price above 20-period MA?
2. Momentum: volume increasing on up moves? RSI recovering from oversold (<30)?
3. Sentiment: Fear & Greed below 40 is a contrarian BUY signal.
4. Target: what's the next resistance? How much upside room?

Output JSON:
{
  "action": "BUY",
  "confidence": 0.0-1.0,
  "reasoning": "1-sentence thesis naming a specific indicator or level",
  "position_pct": 0.0-0.20
}
High confidence (>0.70): strong trend + volume + sentiment aligned.
Medium (0.40-0.70): mixed signals, some confirmation present.
Low (<0.40): choppy, low volume, conflicting signals — but still vote BUY if any rationale exists.
"""

BEAR_SYSTEM = """You are the BEAR — argue ONLY against buying. Output SELL (exit) or HOLD (stay out). Never BUY.

You see the bull's argument. CRITIQUE it:
1. Trend: weakening? Lower highs, declining volume, bearish divergence?
2. Overbought: RSI > 70? Price at resistance? Exhaustion candles?
3. Risk/reward: upside limited vs downside risk? Check recent range.
4. Headwinds: negative sentiment, market-wide selling, macro risk?

Output JSON:
{
  "action": "SELL"|"HOLD",
  "confidence": 0.0-1.0,
  "reasoning": "1-sentence counter-thesis: what did the bull miss?",
  "position_pct": 0.0-0.20
}
SELL (>0.60): clear reversal, resistance rejection, panic conditions.
HOLD (<0.40): uncertain, wait for confirmation.
"""

BEAR_SYSTEM_INDEPENDENT = """You are the BEAR — argue ONLY for SELL or HOLD. Never BUY. Analyze the data INDEPENDENTLY.

Look for bearish signals:
1. Trend: weakening momentum, lower highs, declining volume?
2. Overbought: RSI > 70? Price at resistance? Bearish divergence?
3. Risk/reward: upside limited vs downside risk? Check recent range.
4. Headwinds: negative sentiment, market-wide selling, macro risk?

Output JSON:
{
  "action": "SELL"|"HOLD",
  "confidence": 0.0-1.0,
  "reasoning": "1-sentence bearish thesis naming a specific indicator or level",
  "position_pct": 0.0-0.20
}
SELL (>0.60): clear reversal, resistance rejection, panic conditions.
HOLD (<0.40): uncertain, wait for confirmation — but if any bearish signal exists, vote SELL.
"""

RISK_SYSTEM = """You are the risk manager. Score the bull and bear arguments, then decide.

Scoring criteria:
1. Regime alignment: does the action match the market regime?
2. Risk/reward: is the potential upside worth the downside?
3. Conviction: how confident are the arguments based on data?

Output JSON:
{
  "bull_score": 0.0-1.0,
  "bear_score": 0.0-1.0,
  "verdict": "BUY"|"SELL"|"HOLD",
  "confidence": 0.0-1.0,
  "reasoning": "Brief synthesis of which case is stronger"
}

BUY when: bull scores higher, regime supports it, risk/reward favorable.
SELL when: bear scores higher, clear exit signal, trend reversing.
HOLD only when: both cases equally strong, too uncertain to act.
"""


# ── Debate Engine ─────────────────────────────────────────────


class DebateEngine:
    """Orchestrates multi-agent debate rounds.

    Each round: Bull → Bear → Risk → Synthesis
    """

    def __init__(
        self,
        llama_host: str = "http://127.0.0.1:5801",
        bull_model: str = "qwythos-9b-mtp",
        bear_model: str = "qwythos-9b-mtp",
        risk_model: str = "qwythos-9b-mtp",
        enable_reflection: bool = True,
    ):
        self.llama_host = llama_host.rstrip("/")
        self.models = {
            "bull": bull_model,
            "bear": bear_model,
            "risk": risk_model,
        }
        self.enable_reflection = enable_reflection
        # Optional in-process HF backend for LoRA adapter inference
        self._finetuned_backend = None

    def set_finetuned_backend(self, backend: Any) -> None:
        """Route agent calls through a FineTunedAgent (HF + LoRA)."""
        self._finetuned_backend = backend
        logger.info("Debate engine routing through FineTunedAgent")

    # ── Build Context ───────────────────────────────────────────

    @staticmethod
    def _parse_ohlcv_text(text: str) -> dict:
        """Parse harness ohlcv_json text string into a dict with bars and indicators.

        String format: "SYM $PRICE 1h:RSI=N SMA=N 4h:RSI=N SMA=N 1d:RSI=N SMA=N ATR=N chg=+N%"
        Returns dict with 'symbol', 'price', and 'bars' list suitable for build_context consumption.
        """
        import re

        if not text or not isinstance(text, str):
            return {}
        text = text.strip()
        m = re.match(
            r"^(\S+)\s+"                      # symbol (any non-whitespace)
            r"\$?([\d,.]+)\s+"                # price (optional $)
            r"1h:RSI=([\d.-]+)\s+SMA=([\d,.]+)\s+"
            r"4h:RSI=([\d.-]+)\s+SMA=([\d,.]+)\s+"
            r"1d:RSI=([\d.-]+)\s+SMA=([\d,.]+)\s+"
            r"ATR=([\d,.]+)\s+"
            r"chg=([\d.+-]+)%",
            text,
        )
        if not m:
            return {}

        sym, p, r1, s1, r4, s4, rd, sd, atr_s, chg_s = m.groups()
        try:
            price = float(p.replace(",", ""))
            rsi_1h = float(r1)
            sma_1h = float(s1.replace(",", ""))
            rsi_4h = float(r4)
            sma_4h = float(s4.replace(",", ""))
            rsi_1d = float(rd)
            sma_1d = float(sd.replace(",", ""))
            atr = float(atr_s.replace(",", ""))
        except (ValueError, AttributeError):
            return {}

        # Synthesize a bars-like structure with key datapoints as named closes
        bars = [
            {"close": sma_1d, "name": "SMA_1d"},
            {"close": sma_4h, "name": "SMA_4h"},
            {"close": sma_1h, "name": "SMA_1h"},
            {"close": price, "name": "current"},
            {"close": price + atr, "name": "ATR_upper"},
            {"close": price - atr, "name": "ATR_lower"},
        ]
        return {
            "symbol": sym,
            "price": price,
            "rsi_1h": rsi_1h,
            "rsi_4h": rsi_4h,
            "rsi_1d": rsi_1d,
            "atr": atr,
            "chg_pct": chg_s,
            "bars": bars,
        }

    def build_context(
        self,
        ohlcv_json: str,
        portfolio_json: str,
        regime_json: str,
        economics_json: str,
        news_json: str = "",
        extra_context: str = "",
    ) -> str:
        """Build a shared context block for all agents."""
        ohlcv_text = ohlcv_json if isinstance(ohlcv_json, str) else ""
        try:
            ohlcv = json.loads(ohlcv_json or "{}")
            portfolio = json.loads(portfolio_json or "{}")
            regime = json.loads(regime_json or "{}")
            econ = json.loads(economics_json or "{}")
            news = json.loads(news_json or "{}")
        except Exception:
            portfolio = regime = econ = {}
            news = {}
            ohlcv = self._parse_ohlcv_text(ohlcv_text) if ohlcv_text else {}
            if ohlcv:
                logger.debug("build_context: text-parsed ohlcv fallback (symbol=%s price=%.2f)", ohlcv.get("symbol"), ohlcv.get("price"))

        bars = ohlcv.get("bars", [])
        symbol = ohlcv.get("symbol", "")
        prices = [b.get("close", 0) for b in bars if "close" in b]
        current = prices[-1] if prices else 0

        # Check if we hold this symbol
        positions = portfolio.get("positions", {})
        position_qty = float(positions.get(symbol, 0))
        # Entry price not in portfolio JSON — approximate from recent bars
        position_entry = float(portfolio.get("entry_price", 0))
        position_pnl = 0.0
        if position_qty > 0 and position_entry > 0 and current > 0:
            position_pnl = (current / position_entry - 1) * 100

        context = (
            f"SYMBOL: {symbol}  |  Price: ${current:,.2f}\n"
            f"Portfolio: ${float(portfolio.get('total_value', 0)):,.2f} "
            f"(cash: ${float(portfolio.get('cash', 0)):,.2f})\n"
        )
        if position_qty > 0:
            if position_entry > 0:
                context += (
                    f"HOLDING: {position_qty:.4f} @ ${position_entry:,.2f} "
                    f"(PNL: {position_pnl:+.2f}%)\n"
                )
            else:
                context += f"HOLDING: {position_qty:.4f} (entry unknown)\n"
        context += (
            f"Regime: {regime.get('regime', 'unknown')} "
            f"(confidence: {regime.get('confidence', 0):.0%})\n"
            f"\nRecent closes: "
            f"{' → '.join(f'${p:,.0f}' for p in prices[-10:])}\n"
        )
        if econ:
            context += f"\nMacro: {json.dumps(econ, indent=1)[:200]}\n"
        if news.get("sources"):
            fg = news["sources"].get("fear_greed", {})
            gl = news["sources"].get("coingecko_global", {})
            btc = news["sources"].get("btc_stats", {})
            fg_val = fg.get("value", 50)
            fg_hint = ""
            if fg_val <= 25:
                fg_hint = " ← CONTRARIAN BUY SIGNAL (Extreme Fear = opportunity)"
            elif fg_val >= 75:
                fg_hint = " ← CONTRARIAN SELL SIGNAL (Extreme Greed = caution)"
            context += (
                f"\nCRYPTO SENTIMENT:\n"
                f"  Fear & Greed: {fg_val}/100 ({fg.get('classification', '?')}){fg_hint}\n"
                f"  Total Market Cap: ${gl.get('total_market_cap_usd', 0) / 1e12:.2f}T "
                f"(24h: {gl.get('market_cap_change_24h_pct', 0):+.1f}%)\n"
                f"  BTC Dominance: {gl.get('btc_dominance_pct', 0):.1f}%\n"
            )
            if btc:
                context += (
                    f"  BTC: ${btc.get('price_usd', 0):,.0f} "
                    f"(24h: {btc.get('price_change_24h_pct', 0):+.1f}% "
                    f"7d: {btc.get('price_change_7d_pct', 0):+.1f}% "
                    f"ATH: ${btc.get('ath_usd', 0):,.0f} [{btc.get('ath_change_pct', 0):+.1f}%])\n"
                )
            trending = (
                news["sources"].get("coingecko_trending", {}).get("top_trending", [])
            )
            if trending:
                names = ", ".join(c["symbol"] for c in trending[:5])
                context += f"  Trending: {names}\n"
        # ── Equity market data ──
        equity = (
            news.get("sources", {}).get("equity_markets", {})
            if isinstance(news, dict)
            else {}
        )
        if equity:
            sp = equity.get("sp500", {})
            ix = equity.get("nasdaq", {})
            vx = equity.get("vix", {})
            context += (
                f"\nEQUITY MARKETS:\n"
                f"  S&P 500: {sp.get('price', 0):,.0f} ({sp.get('change_pct', 0):+.1f}%)\n"
                f"  NASDAQ: {ix.get('price', 0):,.0f} ({ix.get('change_pct', 0):+.1f}%)\n"
                f"  VIX: {vx.get('price', 0):,.0f}"
            )
            if vx.get("price", 0) > 25:
                context += " (ELEVATED FEAR)"
            elif vx.get("price", 0) < 15:
                context += " (COMPLACENCY)"
            context += "\n"
        if extra_context:
            context += f"\n{extra_context}\n"
        return context

    # ── Agent Calls ─────────────────────────────────────────────

    # ── Agent Call ──────────────────────────────────────────────

    def _call_agent(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 400,
        host: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Call LLM via finetuned backend or direct API."""
        if self._finetuned_backend is not None:
            try:
                result = self._finetuned_backend.generate(system_prompt, user_prompt)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"Debate agent finetuned fallback ({model}): {e}")

        from urllib.request import Request, urlopen
        from urllib.error import URLError

        acquired = _API_SEMAPHORE.acquire(timeout=DEBATE_TIMEOUT * 2)
        if not acquired:
            logger.error(f"Debate semaphore acquire timed out ({model}) — deadlock suspected")
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
                        logger.debug(f"Debate agent empty response ({model}), retrying once")
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
                        json_str = _strip_markdown_fences(text)
                        if json_str:
                            try:
                                return _safe_parse_json(json_str)
                            except ValueError:
                                pass
                        return None
                json_str = _extract_json_from_text(text) or _strip_markdown_fences(text)
                if json_str:
                    try:
                        return _safe_parse_json(json_str)
                    except ValueError:
                        pass
                return None
            except (URLError, OSError, ConnectionError) as e:
                logger.warning(f"Debate agent HTTP error ({model}), retrying after 1s: {e}")
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
                    ) or _strip_markdown_fences(text)
                    if json_str:
                        try:
                            return _safe_parse_json(json_str)
                        except ValueError:
                            pass
                    return None
                except Exception as e2:
                    logger.warning(f"Debate agent retry also failed ({model}): {e2}")
                    return None
            finally:
                _API_SEMAPHORE.release()

        except Exception as e:
            logger.error(f"Debate agent call failed: {e}")
            return None

    @staticmethod
    def _compute_tf_indicators(bars: list) -> str:
        """Compute multi-timeframe technical indicators from 1h bars."""
        if not bars:
            return "  Multi-TF: insufficient data\n"
        closes = [b.get("close", 0) for b in bars if "close" in b]
        highs = [b.get("high", 0) for b in bars if "high" in b]
        lows = [b.get("low", 0) for b in bars if "low" in b]

        # 1h indicators
        n = len(closes)
        if n >= 14:
            # RSI-14
            diffs = [closes[i] - closes[i - 1] for i in range(1, n)]
            gains = [d if d > 0 else 0 for d in diffs]
            losses = [-d if d < 0 else 0 for d in diffs]
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            rsi1h = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 0
        else:
            rsi1h = 0

        # 4h indicators (downsample)
        if n >= 28:
            closes4h = [sum(closes[i : i + 4]) / 4 for i in range(0, n - 3, 4)]
            highs4h = [max(highs[i : i + 4]) for i in range(0, n - 3, 4)]
            lows4h = [min(lows[i : i + 4]) for i in range(0, n - 3, 4)]
        else:
            closes4h = closes[-4:] if n >= 4 else []
            highs4h = highs[-4:] if n >= 4 else []
            lows4h = lows[-4:] if n >= 4 else []
        if len(closes4h) >= 14:
            diffs4h = [closes4h[i] - closes4h[i - 1] for i in range(1, len(closes4h))]
            gains4h = [d if d > 0 else 0 for d in diffs4h]
            losses4h = [-d if d < 0 else 0 for d in diffs4h]
            avg_gain4h = sum(gains4h[-14:]) / 14
            avg_loss4h = sum(losses4h[-14:]) / 14
            rsi4h = 100 - 100 / (1 + avg_gain4h / avg_loss4h) if avg_loss4h > 0 else 0
        else:
            rsi4h = 0

        # 1d indicators (downsample 24)
        if n >= 48:
            closes1d = [sum(closes[i : i + 24]) / 24 for i in range(0, n - 23, 24)]
        else:
            closes1d = []

        # Volatility
        vol1h = (max(highs) - min(highs)) / max(closes[-1], 1) if highs else 0
        vol4h = (max(highs4h) - min(highs4h)) / max(closes4h[-1], 1) if highs4h else 0

        return (
            f"\nMulti-TF Indicators:\n"
            f"  1h  RSI={rsi1h:.0f}  Vol={vol1h:.2%}  Price=${closes[-1]:,.0f}\n"
            f"  4h  RSI={rsi4h:.0f}  Vol={vol4h:.2%}  Price=${sum(closes4h[-5:]) / 5:.0f}"
            if highs4h
            else "\n  4h  insufficient data"
        )

    def build_context(
        self,
        ohlcv_json: str,
        portfolio_json: str,
        regime_json: str,
        economics_json: str,
        news_json: str = "",
        extra_context: str = "",
    ) -> str:
        """Build a shared context block for all agents."""
        ohlcv_text = ohlcv_json if isinstance(ohlcv_json, str) else ""
        try:
            ohlcv = json.loads(ohlcv_json or "{}")
            portfolio = json.loads(portfolio_json or "{}")
            regime = json.loads(regime_json or "{}")
            econ = json.loads(economics_json or "{}")
            news = json.loads(news_json or "{}")
        except Exception:
            portfolio = regime = econ = {}
            news = {}
            ohlcv = self._parse_ohlcv_text(ohlcv_text) if ohlcv_text else {}
            if ohlcv:
                logger.debug("build_context: text-parsed ohlcv fallback (symbol=%s price=%.2f)", ohlcv.get("symbol"), ohlcv.get("price"))

        bars = ohlcv.get("bars", [])
        symbol = ohlcv.get("symbol", "")
        prices = [b.get("close", 0) for b in bars if "close" in b]
        current = prices[-1] if prices else 0

        # Check if we hold this symbol
        positions = portfolio.get("positions", {})
        position_qty = float(positions.get(symbol, 0))
        position_entry = float(portfolio.get("entry_price", 0))
        position_pnl = 0.0
        if position_qty > 0 and position_entry > 0 and current > 0:
            position_pnl = (current / position_entry - 1) * 100

        # ── Shared cycle-level context FIRST (identical across symbols within a
        #    cycle → llama.cpp KV-cache prefix reuse across bull calls and
        #    across bear calls, cutting redundant re-tokenization). ──
        shared = ""
        if econ:
            try:
                from data.economics import fred_to_context

                _fred = fred_to_context(econ)
            except Exception:
                _fred = ""
            shared += _fred or f"\nMacro: {json.dumps(econ, indent=1)[:200]}\n"
        if news.get("sources"):
            fg = news["sources"].get("fear_greed", {})
            gl = news["sources"].get("coingecko_global", {})
            btc = news["sources"].get("btc_stats", {})
            fg_val = fg.get("value", 50)
            fg_hint = ""
            if fg_val <= 25:
                fg_hint = " ← CONTRARIAN BUY SIGNAL (Extreme Fear = opportunity)"
            elif fg_val >= 75:
                fg_hint = " ← CONTRARIAN SELL SIGNAL (Extreme Greed = caution)"
            shared += (
                f"\nCRYPTO SENTIMENT:\n"
                f"  Fear & Greed: {fg_val}/100 ({fg.get('classification', '?')}){fg_hint}\n"
                f"  Total Market Cap: ${gl.get('total_market_cap_usd', 0) / 1e12:.2f}T "
                f"(24h: {gl.get('market_cap_change_24h_pct', 0):+.1f}%)\n"
                f"  BTC Dominance: {gl.get('btc_dominance_pct', 0):.1f}%\n"
            )
            if btc:
                shared += (
                    f"  BTC: ${btc.get('price_usd', 0):,.0f} "
                    f"(24h: {btc.get('price_change_24h_pct', 0):+.1f}% "
                    f"7d: {btc.get('price_change_7d_pct', 0):+.1f}% "
                    f"ATH: ${btc.get('ath_usd', 0):,.0f} [{btc.get('ath_change_pct', 0):+.1f}%])\n"
                )
            trending = (
                news["sources"].get("coingecko_trending", {}).get("top_trending", [])
            )
            if trending:
                names = ", ".join(c["symbol"] for c in trending[:5])
                shared += f"  Trending: {names}\n"
        # ── Equity market data ──
        equity = (
            news.get("sources", {}).get("equity_markets", {})
            if isinstance(news, dict)
            else {}
        )
        if equity:
            sp = equity.get("sp500", {})
            ix = equity.get("nasdaq", {})
            vx = equity.get("vix", {})
            shared += (
                f"\nEQUITY MARKETS:\n"
                f"  S&P 500: {sp.get('price', 0):,.0f} ({sp.get('change_pct', 0):+.1f}%)\n"
                f"  NASDAQ: {ix.get('price', 0):,.0f} ({ix.get('change_pct', 0):+.1f}%)\n"
                f"  VIX: {vx.get('price', 0):,.0f}"
            )
            if vx.get("price", 0) > 25:
                shared += " (ELEVATED FEAR)"
            elif vx.get("price", 0) < 15:
                shared += " (COMPLACENCY)"
            shared += "\n"

        # ── Symbol-specific context AFTER the shared block ──
        context = shared
        context += (
            f"\nSYMBOL: {symbol}  |  Price: ${current:,.2f}\n"
            f"Portfolio: ${float(portfolio.get('total_value', 0)):,.2f} "
            f"(cash: ${float(portfolio.get('cash', 0)):,.2f})\n"
        )
        if position_qty > 0:
            if position_entry > 0:
                context += (
                    f"HOLDING: {position_qty:.4f} @ ${position_entry:,.2f} "
                    f"(PNL: {position_pnl:+.2f}%)\n"
                )
            else:
                context += f"HOLDING: {position_qty:.4f} (entry unknown)\n"
        context += (
            f"Regime: {regime.get('regime', 'unknown')} "
            f"(confidence: {regime.get('confidence', 0):.0%})\n"
            f"\nRecent closes: "
            f"{' → '.join(f'${p:,.0f}' for p in prices[-10:])}\n"
        )
        # ── Multi-Timeframe Indicators ──
        tf_context = self._compute_tf_indicators(bars)
        context += tf_context
        if extra_context:
            context += f"\n{extra_context}\n"
        return context
        """Call an LLM agent via llama-swap or in-process FineTunedAgent.

        When a FineTunedAgent is active, routes the call through its in-process
        HF transformers inference instead of llama-swap.
        """
        # Check if in-process backend handles this agent role
        if self._finetuned_backend is not None:
            try:
                result = self._finetuned_backend.generate(system_prompt, user_prompt)
                if result is not None:
                    return result
            except Exception as e:
                logger.debug(f"FinetunedBackend fallback ({model}): {e}")

        # Default: llama-swap / standard OpenAI-compatible API
        url = f"{self.llama_host}/v1/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 300,
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
                return json.loads(text)
        except (URLError, json.JSONDecodeError, KeyError, ConnectionResetError) as e:
            logger.debug(f"Debate agent error ({model}): {e}")
            return None

    # ── Full Debate Round ───────────────────────────────────────

    def debate(
        self,
        ohlcv_json: str = None,
        portfolio_json: str = None,
        regime_json: str = None,
        economics_json: str = None,
        news_json: str = "",
        reflection_context: str = "",
        extra_context: str = "",
        regime_instructions: Dict[str, str] = None,
        parallel: bool = False,
    ) -> DebateResult:
        """Run a full debate round. Returns the final signal.

        Args:
            regime_instructions: Optional dict with 'bull', 'bear', 'risk' keys.
            parallel: If True, Bull and Bear run concurrently (~2x speedup).
        """
        start = time.time()
        context = self.build_context(
            ohlcv_json,
            portfolio_json,
            regime_json,
            economics_json,
            news_json=news_json,
            extra_context=extra_context,
        )
        if reflection_context:
            context = f"REFLECTION: {reflection_context}\n\n{context}"

        # Build regime-adaptive system prompts
        bull_system = BULL_SYSTEM
        bear_system = BEAR_SYSTEM
        risk_system = RISK_SYSTEM
        if regime_instructions:
            bull_inst = regime_instructions.get("bull", "")
            bear_inst = regime_instructions.get("bear", "")
            risk_inst = regime_instructions.get("risk", "")
            if bull_inst:
                bull_system = f"{bull_inst}\n\n{bull_system}"
            if bear_inst:
                bear_system = f"{bear_inst}\n\n{bear_system}"
            if risk_inst:
                risk_system = f"{risk_inst}\n\n{risk_system}"

        if parallel:
            # ── Parallel: Bull + Bear run concurrently ──────
            # Bear gets independent prompt (no Bull dependency)
            # so both can run in parallel → ~3.7s total vs ~7.4s sequential
            def _call_bull():
                raw = self._call_agent(bull_system, context, self.models["bull"])
                return DebateVote(
                    agent="bull",
                    action=raw.get("action", "HOLD") if raw else "HOLD",
                    confidence=raw.get("confidence", 0.5) if raw else 0.5,
                    reasoning=raw.get("reasoning", "Bull unavailable")
                    if raw
                    else "Bull agent failed",
                )

            def _call_bear():
                raw = self._call_agent(
                    BEAR_SYSTEM_INDEPENDENT, context, self.models["bear"]
                )
                return DebateVote(
                    agent="bear",
                    action=raw.get("action", "HOLD") if raw else "HOLD",
                    confidence=raw.get("confidence", 0.5) if raw else 0.5,
                    reasoning=raw.get("reasoning", "Bear unavailable")
                    if raw
                    else "Bear agent failed",
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                bull_future = pool.submit(_call_bull)
                bear_future = pool.submit(_call_bear)
                bull = bull_future.result()
                bear = bear_future.result()
        else:
            # ── Sequential: Bull → Bear (original) ──────────
            # Round 1: Bull makes the case
            bull_raw = self._call_agent(bull_system, context, self.models["bull"])
            bull = DebateVote(
                agent="bull",
                action=bull_raw.get("action", "HOLD") if bull_raw else "HOLD",
                confidence=bull_raw.get("confidence", 0.5) if bull_raw else 0.5,
                reasoning=bull_raw.get("reasoning", "Bull unavailable")
                if bull_raw
                else "Bull agent failed",
            )

            # Round 2: Bear challenges with bull's argument
            bear_prompt = (
                f"{context}\n\n"
                f"Bull analyst argues: {bull.reasoning[:200]}\n"
                f"Bull wants to: {bull.action} at {bull.confidence:.0%} confidence.\n\n"
                f"Challenge this thesis. Are they wrong?"
            )
            bear_raw = self._call_agent(bear_system, bear_prompt, self.models["bear"])
            bear = DebateVote(
                agent="bear",
                action=bear_raw.get("action", "HOLD") if bear_raw else "HOLD",
                confidence=bear_raw.get("confidence", 0.5) if bear_raw else 0.5,
                reasoning=bear_raw.get("reasoning", "Bear unavailable")
                if bear_raw
                else "Bear agent failed",
            )

        # ── Round 3: Risk scores both ────────────────────────
        risk_prompt = (
            f"Market Context:\n{context}\n\n"
            f"BULL: {bull.reasoning[:200]} (confidence: {bull.confidence:.0%})\n"
            f"BEAR: {bear.reasoning[:200]} (confidence: {bear.confidence:.0%})\n\n"
            f"Which argument is stronger? Score each and give a verdict."
        )
        risk_raw = self._call_agent(risk_system, risk_prompt, self.models["risk"])
        risk_verdict = {}
        if risk_raw:
            risk_verdict = {
                "bull_score": risk_raw.get("bull_score", 0.5),
                "bear_score": risk_raw.get("bear_score", 0.5),
                "verdict": risk_raw.get("verdict", "HOLD"),
                "confidence": risk_raw.get("confidence", 0.5),
                "reasoning": risk_raw.get("reasoning", ""),
            }

        # ── Synthesis ────────────────────────────────────────
        # Weighted: if risk verdict matches bull → BUY, matches bear → bear action
        verdict = risk_verdict.get("verdict", bear.action)
        risk_conf = risk_verdict.get("confidence", 0.5)
        bull_weight = risk_verdict.get("bull_score", 0.5)
        bear_weight = risk_verdict.get("bear_score", 0.5)

        # If risk confidence is high, use risk verdict directly
        if risk_conf >= 0.6:
            final_action = verdict
            final_conf = risk_conf
        else:
            # Weighted average: dominant agent wins
            if bull_weight > bear_weight:
                final_action = bull.action
                final_conf = bull.confidence * bull_weight
            else:
                final_action = bear.action
                final_conf = bear.confidence * bear_weight

        # Position sizing based on conviction
        pos_pct = round(final_conf * 0.25, 4)  # 0-25% of portfolio (was 0.12)

        # Reason string
        reason = (
            f"Debate: Bull({bull.confidence:.0%}) vs Bear({bear.confidence:.0%}) "
            f"→ Risk({verdict},{risk_conf:.0%})"
        )

        duration = int((time.time() - start) * 1000)
        return DebateResult(
            action=final_action,
            confidence=round(final_conf, 2),
            position_pct=pos_pct,
            reason=reason,
            bull_vote=bull,
            bear_vote=bear,
            risk_verdict=risk_verdict,
            duration_ms=duration,
        )

    # ── Fast Debate (single composite call, ~3x faster) ──────────

    def _call_raw(
        self, system_prompt: str, user_prompt: str, model: str
    ) -> Optional[str]:
        """Call LLM and return raw text (no JSON parsing)."""
        url = f"{self.llama_host}/v1/chat/completions"
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 2000,
            }
        ).encode()

        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urlopen(req, timeout=DEBATE_TIMEOUT) as resp:
                raw = resp.read().decode()
                data = json.loads(raw)
                return _extract_text(data["choices"][0]["message"])
        except Exception as e:
            logger.debug(f"_call_raw ({model}): {e}")
            return None

    def fast_debate(
        self,
        ohlcv_json: str = None,
        portfolio_json: str = None,
        regime_json: str = None,
        economics_json: str = None,
        news_json: str = "",
        extra_context: str = "",
        regime_instructions: Dict[str, str] = None,
        parallel: bool = False,
    ) -> DebateResult:
        """Single-call composite debate: one LLM call produces all perspectives.

        Cuts per-symbol debate time from ~24s (3 calls) to ~10s.
        """
        start = time.time()
        context = self.build_context(
            ohlcv_json,
            portfolio_json,
            regime_json,
            economics_json,
            news_json=news_json,
            extra_context=extra_context,
        )
        model = self.models.get("bull", self.models.get("default", ""))

        bull_inst = (regime_instructions or {}).get("bull", "")
        bear_inst = (regime_instructions or {}).get("bear", "")
        risk_inst = (regime_instructions or {}).get("risk", "")

        system = (
            "You are a crypto trading analyst. Analyze the data and output a BUY, SELL, or HOLD signal.\n"
            "Do NOT default to HOLD — if the data supports a trade, take a position.\n"
            "Consider Fear & Greed as contrarian: fear=opportunity, greed=caution.\n\n"
            "IMPORTANT: Output DIRECTLY in your response content. Do NOT use reasoning/thinking mode.\n"
            "No preamble, no chain-of-thought. Start immediately with the sections.\n\n"
            "Output THREE sections:\n\n"
            "BULL: action=BUY confidence=0.XX position_pct=0.XX reasoning=Best case for buying.\n"
            f"{'Regime: ' + bull_inst + chr(10) if bull_inst else ''}"
            "BEAR: action=SELL confidence=0.XX position_pct=0.XX reasoning=Risks and why NOT to buy.\n"
            f"{'Regime: ' + bear_inst + chr(10) if bear_inst else ''}"
            "RISK: action=BUY|SELL|HOLD confidence=0.XX position_pct=0.XX reasoning=Final verdict.\n"
            f"{'Regime: ' + risk_inst + chr(10) if risk_inst else ''}"
            "Format: label action=X confidence=0.XX position_pct=0.XX reasoning=..."
        )
        prompt = f"{context}\n\nMulti-perspective analysis:"

        raw = self._call_raw(system, prompt, model)
        if not raw:
            return self.debate(
                ohlcv_json,
                portfolio_json,
                regime_json,
                economics_json,
                news_json=news_json,
                extra_context=extra_context,
                regime_instructions=regime_instructions,
                parallel=parallel,
            )

        # Parse composite response — regex-based, handles all model output formats
        bull = DebateVote(agent="bull", action="HOLD", confidence=0.5, reasoning="")
        bear = DebateVote(agent="bear", action="HOLD", confidence=0.5, reasoning="")
        risk_verdict, risk_conf, pos_pct = "HOLD", 0.5, 0.05

        raw_text = str(raw)
        # Find labeled sections: [BULL], [BEAR], [RISK] or [SECTION]
        markers = list(
            re.finditer(r"\[(BULL|BEAR|RISK|SECTION)\]", raw_text, re.IGNORECASE)
        )
        if not markers:
            # Fallback: try to find un-bracketed section labels
            markers = list(
                re.finditer(
                    r"(?:^|\n)\s*\d*\.?\s*(BULL|BEAR|RISK)\s*[:=-]?\s*",
                    raw_text,
                    re.MULTILINE | re.IGNORECASE,
                )
            )

        if markers:
            for i, m in enumerate(markers):
                label = m.group(1).lower()
                start = m.end()
                end = markers[i + 1].start() if i + 1 < len(markers) else len(raw_text)
                section_text = raw_text[start:end].strip()
                s_lower = section_text.lower()

                # Parse action (first 200 chars)
                action = "HOLD"
                for act in ("buy", "sell", "hold"):
                    if act in s_lower[:200]:
                        action = act.upper()
                        break

                # Parse confidence with regex
                conf = 0.5
                cm = re.search(r"confidence\s*[=:]\s*(\d+\.?\d*)", s_lower)
                if cm:
                    v = float(cm.group(1))
                    if v > 100:
                        # Bogus value, clamp at 1.0
                        conf = 1.0
                    elif v > 1.0:
                        # Model output integer-percentage (e.g. 85 → 0.85)
                        conf = v / 100
                    elif v <= 0.0:
                        conf = 0.01  # minimum viable signal
                    else:
                        conf = v  # Already decimal (e.g. 0.85)
                    # Warn on ambiguous outputs that could be either format
                    if 1.0 < v <= 10.0:
                        logger.warning(
                            f"fast_debate: low-confidence integer {v} detected "
                            f"(treated as {conf:.0%}) — check prompt format drift"
                        )

                # Parse position_pct with regex
                pos = 0.10
                pm = re.search(r"position_pct\s*[=:]\s*(\d+\.?\d*)", s_lower)
                if pm:
                    v = float(pm.group(1))
                    if v > 100:
                        pos = 0.25  # max
                    elif v > 1.0:
                        pos = v / 100  # integer-percentage
                    elif v <= 0.0:
                        pos = 0.01
                    else:
                        pos = v

                if label == "bull":
                    bull = DebateVote(
                        agent="bull",
                        action=action,
                        confidence=conf,
                        reasoning=section_text[:100],
                    )
                elif label == "bear":
                    bear = DebateVote(
                        agent="bear",
                        action=action,
                        confidence=conf,
                        reasoning=section_text[:100],
                    )
                else:  # risk or section
                    risk_verdict, risk_conf, pos_pct = action, conf, pos
        else:
            # No structured markers at all — fall back to full debate
            logger.debug(
                "fast_debate: no section markers in response, falling back to full debate"
            )
            return self.debate(
                ohlcv_json,
                portfolio_json,
                regime_json,
                economics_json,
                news_json=news_json,
                extra_context=extra_context,
                regime_instructions=regime_instructions,
                parallel=parallel,
            )

        # HOLD is a valid signal — no forced override.
        # The model must have conviction to trade; weak signals stay HOLD.

        pos_pct = min(0.25, max(0.01, pos_pct))  # clamp 1%-25%
        elapsed = (time.time() - start) * 1000
        logger.debug(
            f"Fast debate {elapsed:.0f}ms → Bull({bull.action},{bull.confidence:.0%}) "
            f"Bear({bear.action},{bear.confidence:.0%}) Risk({risk_verdict},{risk_conf:.0%})"
        )

        return DebateResult(
            action=risk_verdict,
            confidence=round(risk_conf, 2),
            position_pct=pos_pct,
            reason=f"Composite: Bull({bull.confidence:.0%}) vs Bear({bear.confidence:.0%}) → Risk({risk_verdict},{risk_conf:.0%})",
            bull_vote=bull,
            bear_vote=bear,
            risk_verdict=risk_verdict,
            duration_ms=elapsed,
        )
