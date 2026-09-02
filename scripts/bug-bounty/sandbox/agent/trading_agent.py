#!/usr/bin/env python3
"""TradingAgent -- model-driven agent that calls MCP tools.

Architecture:
  1. Receive market context (OHLCV, portfolio, regime)
  2. Call MCP tools to gather intelligence
  3. Call model (via llama-swap) for reasoning + tool selection
  4. Execute tool calls against MCP server
  5. Produce final Signal

The model "calls tools" via structured JSON inside <tool_calls> tags.
The agent executes those calls via MCPClient.
This is the "model calls tools via MCP" paradigm.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

from .base import BaseAgent, Signal, AgentContext, register_agent
from .mcp_client import MCPClient

logger = logging.getLogger("opentrader.trading_agent")


# ── JSON extraction helpers (brace-aware, handles nesting) ────


def _find_json_objects(text: str) -> List[str]:
    """Extract all valid JSON objects from text, handling nested braces.

    Uses brace-depth counting to find complete {} blocks,
    then validates each with json.loads.
    """
    results = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                try:
                    json.loads(candidate)
                    results.append(candidate)
                except json.JSONDecodeError:
                    pass
                start = -1
    return results


def _parse_gemma_tool_call(text: str) -> List[dict]:
    """Parse Gemma-native <|tool_call|>call:Name{params}<tool_call|> format.

    Handles variants:
      <|tool_call|>call:Name{params}<tool_call|>
      <|tool_call>call:Name{params}<tool_call|>  (missing trailing |)
    Also handles <|"|> delimited string values in params.
    """
    calls = []
    pattern = r"<\|tool_call\|?>\s*call:(\w+)\s*\{([^}]*)\}\s*<tool_call\|>"
    for m in re.finditer(pattern, text, re.DOTALL):
        name = m.group(1)
        params_raw = m.group(2).strip()
        params = {}
        if params_raw:
            # Parse key:value pairs, handling <|"|> delimited strings
            for pair in re.findall(
                r'(\w+)\s*:\s*(<\|"\|\>[^<]*<\|"\|\>|true|false|\d+\.?\d*|"[^"]*"|\'[^\']*\')',
                params_raw,
            ):
                key = pair[0]
                val = pair[1]
                # Strip <|"|> delimiters
                if val.startswith('<|"|>') and val.endswith('<|"|>'):
                    val = val[5:-5]
                elif val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val == "true":
                    val = True
                elif val == "false":
                    val = False
                else:
                    try:
                        if "." in val:
                            val = float(val)
                        else:
                            val = int(val)
                    except (ValueError, TypeError):
                        pass
                params[key] = val
        calls.append({"tool": name, "params": params})
    return calls


def _extract_tool_calls(text: str) -> List[dict]:
    """Extract tool call JSON objects from model output.

    Supports multiple formats:
      1. <|tool_call|>call:Name{params}<tool_call|> (Gemma native)
      2. <tool_calls>[{"tool":...,"params":{...}}]</tool_calls> (our format)
      3. Raw JSON objects with "tool" key (fallback)
    """
    if not text:
        return []

    # Try Gemma native format first
    gemma_calls = _parse_gemma_tool_call(text)
    if gemma_calls:
        return gemma_calls

    # Try our tagged format: <tool_calls>[{...}, {...}]</tool_calls>
    calls = []
    tag_m = re.search(r"<tool_calls>\s*(.*?)\s*</tool_calls>", text, re.DOTALL)
    if tag_m:
        inner = tag_m.group(1)
        try:
            parsed = json.loads(inner)
            if isinstance(parsed, list):
                return [c for c in parsed if isinstance(c, dict) and "tool" in c]
            elif isinstance(parsed, dict) and "tool" in parsed:
                return [parsed]
        except json.JSONDecodeError:
            pass
        for obj_str in _find_json_objects(inner):
            try:
                obj = json.loads(obj_str)
                if isinstance(obj, dict) and "tool" in obj:
                    calls.append(obj)
            except json.JSONDecodeError:
                continue
        if calls:
            return calls

    # Fallback: scan for any JSON object with "tool" key
    for obj_str in _find_json_objects(text):
        try:
            obj = json.loads(obj_str)
            if (
                isinstance(obj, dict)
                and "tool" in obj
                and obj["tool"] not in ("SIGNAL", "signal")
            ):
                calls.append(obj)
        except json.JSONDecodeError:
            continue

    return calls


def _extract_signal(text: str) -> Optional[Signal]:
    """Extract a Signal from model output. Handles nested JSON."""
    if not text:
        return None

    # Try SIGNAL: <json> format first
    m = re.search(r"SIGNAL:\s*(\{)", text, re.DOTALL)
    if m:
        start = m.start(1)
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    raw = text[start : i + 1]
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = None
                    if data and "action" in data:
                        action = data.get("action", "HOLD").upper()
                        if action not in ("BUY", "SELL", "HOLD"):
                            action = "HOLD"
                        return Signal(
                            action=action,
                            symbol=data.get("symbol", "BTC/USDT"),
                            confidence=float(data.get("confidence", 0.5)),
                            reason=str(data.get("reason", "")),
                            position_pct=float(data.get("position_pct", 0.05)),
                            stop_loss=data.get("stop_loss"),
                            take_profit=data.get("take_profit"),
                            meta={
                                k: v
                                for k, v in data.items()
                                if k
                                not in (
                                    "action",
                                    "symbol",
                                    "confidence",
                                    "reason",
                                    "position_pct",
                                    "stop_loss",
                                    "take_profit",
                                )
                            },
                        )
                    # If we found something with balanced braces but it wasn't right, continue scan

    # Fallback: find any JSON with "action" field
    for obj_str in _find_json_objects(text):
        try:
            data = json.loads(obj_str)
            action = data.get("action", "").upper()
            if action in ("BUY", "SELL", "HOLD"):
                return Signal(
                    action=action,
                    symbol=data.get("symbol", "BTC/USDT"),
                    confidence=float(data.get("confidence", 0.5)),
                    reason=str(data.get("reason", "")),
                    position_pct=float(data.get("position_pct", 0.05)),
                    stop_loss=data.get("stop_loss"),
                    take_profit=data.get("take_profit"),
                    meta={
                        k: v
                        for k, v in data.items()
                        if k
                        not in (
                            "action",
                            "symbol",
                            "confidence",
                            "reason",
                            "position_pct",
                            "stop_loss",
                            "take_profit",
                        )
                    },
                )
        except (json.JSONDecodeError, ValueError, TypeError):
            continue

    return None


def _extract_thinking(text: str) -> List[str]:
    """Extract Kimi K3-style thinking blocks from model output.

    Supports three formats:
      1. <|thinking_start|> / <|thinking_end|> with Thought: lines
      2. <thinking> / </thinking> with Thought: lines
      3. THOUGHT: inline comments
    """
    thinking_steps = []
    if not text:
        return thinking_steps

    # Format 1: <|thinking_start|> / <|thinking_end|>
    thinking_start = r"<\\|thinking_start\\|>"
    thinking_end = r"<\\|thinking_end\\|>"
    m = re.search(f"{thinking_start}(.*?){thinking_end}", text, re.DOTALL)
    if m:
        block = m.group(1)
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("Thought:"):
                thinking_steps.append(line[8:].strip())
            elif line:
                thinking_steps.append(line)
        return thinking_steps if thinking_steps else [block]

    # Format 2: <thinking> / </thinking>
    m = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
    if m:
        block = m.group(1)
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("Thought:"):
                thinking_steps.append(line[8:].strip())
            elif line:
                thinking_steps.append(line)
        return thinking_steps if thinking_steps else [block]

    # Format 3: THOUGHT: inline comments
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("THOUGHT:"):
            thinking_steps.append(line[8:].strip())

    return thinking_steps

# ── System prompt template ────────────────────────────────────

TOOL_SCHEMA_JSON = json.dumps(
    [
        {
            "name": "get_ohlcv",
            "description": "Fetch OHLCV price bars for a symbol",
            "params": {
                "symbol": "str (e.g. BTC/USDT)",
                "timeframe": "str (1m, 5m, 1h, 4h, 1d)",
                "limit": "int (max 200, default 50)",
            },
        },
        {
            "name": "get_portfolio",
            "description": "Get current portfolio state: cash, positions, total value",
            "params": {},
        },
        {
            "name": "get_regime",
            "description": "Analyze market regime (trending_up, bearish, ranging, volatile)",
            "params": {"symbol": "str (e.g. BTC/USDT)"},
        },
        {
            "name": "get_economics",
            "description": "Fetch economic indicators",
            "params": {},
        },
        {
            "name": "qmath",
            "description": "Accurate math/quant/stat. CALL THIS instead of hand-arithmetic. ops: evaluate, mean, median, std, percentile, iqr, skew, kurtosis, simple_returns, log_returns, total_return, annualized_return, annualized_volatility, max_drawdown, sharpe_ratio, sortino_ratio, calmar_ratio, var_historical, var_parametric, cvar, kelly_fraction, position_size_kelly, covariance, correlation, correlation_matrix, beta, ols_regression, black_scholes, future_value, present_value, npv, irr, compound_annual_growth_rate, percent_change, percent_of",
            "params": {
                "op": "str (the operation name, e.g. 'sharpe_ratio')",
                "args": "dict (kwargs for the op, e.g. {\"returns\":[0.01,-0.02,...],\"confidence\":0.95} or {\"expr\":\"(110-100)/100*100\"} or {\"prices\":[...]} or {\"x\":[...],\"y\":[...]})",
            },
        },
    ]
)

SYSTEM_PROMPT = '''Your task: analyze the provided market data, portfolio state, and regime, then output a single trading decision.

PRIMARY OBJECTIVE: Accumulate capital for hardware upgrades (MI60 32GB GPU + 64GB RAM + 2TB NVMe -- approximately $270). Grow the account through small, consistent wins. Protect the downside -- you can\'t buy hardware from a blown account. Aim for +0.5-2% per trade rather than Hail Mary gains.

OUTPUT FORMAT -- exactly one line:
SIGNAL: {{"action": "BUY|SELL|HOLD", "symbol": "BTC/USDT", "confidence": 0.5, "reason": "brief thesis", "position_pct": 0.1}}

RULES:
- action: BUY (enter), SELL (exit), or HOLD (do nothing)
- confidence: 0.0-1.0 (>0.6 consider trade, >0.8 execute)
- position_pct: 0.0-0.2 (fraction of portfolio to risk, 0 for HOLD)
- reason: 10-30 words explaining your reasoning
- Do NOT output any tool calls, functions, or extra text before/after SIGNAL.
- Do NOT call any Order, trade, or submit function.
- If data is insufficient, output HOLD with low confidence.
- Be conservative: protect capital first, seek opportunities second.
- Track progress toward the hardware goal and mention it in your reasoning.
You are OpenTrader, an autonomous trading agent managing a ${initial_cash} portfolio.

## THINKING FORMAT (Kimi K3 Style)
Before making your trading decision, think through the market systematically.
Output your reasoning in steps, then conclude with SIGNAL.

<|thinking_start|>
Thought: [Step 1: Assess current position and portfolio state]
Thought: [Step 2: Analyze price action -- trend, momentum, support/resistance]
Thought: [Step 3: Evaluate market regime and volatility]
Thought: [Step 4: Consider risk/reward and position sizing]
Thought: [Step 5: Formulate final decision with confidence assessment]
<|thinking_end|>

Then output your final decision:
SIGNAL: {"action": "BUY|SELL|HOLD", "symbol": "BTC/USDT", "confidence": 0.5, "reason": "brief thesis", "position_pct": 0.1}

PRIMARY OBJECTIVE: Accumulate capital for hardware upgrades (MI60 32GB GPU + 64GB RAM + 2TB NVMe -- approximately $270). Grow the account through small, consistent wins. Protect the downside -- you can\'t buy hardware from a blown account. Aim for +0.5-2% per trade rather than Hail Mary gains.

OUTPUT FORMAT -- exactly one line:
SIGNAL: {"action": "BUY|SELL|HOLD", "symbol": "BTC/USDT", "confidence": 0.5, "reason": "brief thesis", "position_pct": 0.1}

RULES:
- action: BUY (enter), SELL (exit), or HOLD (do nothing)
- confidence: 0.0-1.0 (>0.6 consider trade, >0.8 execute)
- position_pct: 0.0-0.2 (fraction of portfolio to risk, 0 for HOLD)
- reason: 10-30 words explaining your reasoning
- Do NOT output any tool calls, functions, or extra text before/after SIGNAL.
- Do NOT call any Order, trade, or submit function.
- If data is insufficient, output HOLD with low confidence.
- Be conservative: protect capital first, seek opportunities second.
- Track progress toward the hardware goal and mention it in your reasoning.
'''



# ── Model client (llama-swap) ─────────────────────────────────


def call_llama_swap(
    prompt: str,
    system_prompt: str = "",
    model: str = "opentrader-agent",
    host: str = "http://127.0.0.1:8080",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    timeout: float = 90.0,
) -> Optional[str]:
    """Call a model via llama-swap\'s OpenAI-compatible API."""
    url = f"{host.rstrip('/')}/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    req = Request(url, data=json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode())
        choices = result.get("choices", [])
        if not choices:
            logger.warning(f"llama-swap returned empty choices: {result}")
            return None
        return choices[0].get("message", {}).get("content", "")
    except URLError as e:
        logger.warning(f"llama-swap unavailable: {e}")
        return None
    except Exception as e:
        logger.warning(f"llama-swap error: {e}")
        return None


# ── Heuristic fallback ────────────────────────────────────────


def _heuristic_signal(
    ohlcv_data: dict, portfolio: dict, regime: dict, symbol: str
) -> Signal:
    """Simple heuristic trading logic when model is unavailable."""
    bars = ohlcv_data.get("bars", [])
    if not bars or len(bars) < 10:
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=0.3,
            reason="insufficient data for heuristic",
        )

    closes = [b.get("close", 0) for b in bars[-20:]]
    if not closes:
        return Signal(
            action="HOLD", symbol=symbol, confidence=0.3, reason="no close prices"
        )

    short = sum(closes[-5:]) / max(1, len(closes[-5:]))
    medium = sum(closes[-10:]) / max(1, len(closes[-10:]))
    long_ = sum(closes) / len(closes)

    current_price = closes[-1] if closes else 0
    cash = float(portfolio.get("cash", 0))
    total = float(portfolio.get("total_value", 0))

    if current_price < short * 0.98 and short > medium:
        confidence = min(0.7, abs(current_price - short) / current_price * 10)
        return Signal(
            action="BUY",
            symbol=symbol,
            confidence=round(confidence, 2),
            reason=f"heuristic pullback: price {current_price:.2f} < MA5 {short:.2f}",
            position_pct=min(0.10, cash / max(total, 1) * 0.5),
        )
    elif current_price > long_ * 1.05 and current_price > short * 1.02:
        confidence = min(0.6, abs(current_price - long_) / long_ * 5)
        return Signal(
            action="SELL",
            symbol=symbol,
            confidence=round(confidence, 2),
            reason=f"heuristic take-profit: price {current_price:.2f} > MA20 {long_:.2f}",
            position_pct=0.05,
        )
    else:
        return Signal(
            action="HOLD",
            symbol=symbol,
            confidence=0.4,
            reason=f"price={current_price:.2f}, MA5={short:.2f}, MA20={long_:.2f}",
        )


# ── TradingAgent ──────────────────────────────────────────────


class TradingAgent(BaseAgent):
    """Model-driven trading agent that calls MCP tools via llama-swap.

    Flow per cycle:
      1. Build prompt with market data + tool schemas
      2. Call model → model outputs <tool_calls> JSON blocks
      3. Execute each tool call via MCPClient
      4. Feed tool results back to model for next reasoning round
      5. Extract final SIGNAL from model output
      6. Fallback to heuristic if model unavailable or output unclear
    """

    def __init__(self, name: str = "trading_agent", config: dict = None):
        super().__init__(name, config)
        self.mcp = (
            MCPClient(
                base_url=config.get("mcp_url", "http://127.0.0.1:8092"),
            )
            if config
            else MCPClient()
        )
        self.model = (
            config.get("model", "opentrader-agent") if config else "opentrader-agent"
        )
        self.llama_host = (
            config.get("llama_host", "http://127.0.0.1:5801")
            if config
            else "http://127.0.0.1:5802"
        )
        self.use_model = config.get("use_model", True) if config else True
        self.max_tool_rounds = config.get("max_tool_rounds", 3) if config else 3
        self._history: List[dict] = []

    def analyze(self, ctx: AgentContext) -> Signal:
        """Main analysis entry point. Runs model loop or heuristic."""
        signal = self._model_loop(ctx)

        self._history.append(
            {
                "cycle": ctx.cycle,
                "symbol": ctx.symbol,
                "signal": {
                    "action": signal.action,
                    "confidence": signal.confidence,
                    "reason": signal.reason,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return signal

    def _model_loop(self, ctx: AgentContext) -> Signal:
        """Single-shot model reasoning: we provide all data, model outputs SIGNAL."""
        if not self.use_model:
            return self._fallback(ctx)
        initial_cash = self.config.get("initial_cash", 100_000)
        context_block = (
            f"## Market Data ({ctx.symbol} / {ctx.timeframe})"
            f"OHLCV: {self._trunc(ctx.ohlcv_json, 2500)}"
            f"## Portfolio{self._trunc(ctx.portfolio_json, 1000)}"
            f"## Regime{self._trunc(ctx.regime_json, 500)}"
            f"## Economics{self._trunc(ctx.economics_json, 500)}"
            f"## Cycle{ctx.cycle}"
        )
        system = SYSTEM_PROMPT.format(
            tool_schemas=TOOL_SCHEMA_JSON,
            initial_cash=initial_cash,
            cycle=ctx.cycle,
        )
        prompt = (
            context_block
            + "Based on the data above, analyze the market and output your trading decision."
            + "Output **only** a SIGNAL line with JSON. Do NOT call any tools or functions."
        )
        model_output = call_llama_swap(
            prompt,
            system_prompt=system,
            model=self.model,
            host=self.llama_host,
        )
        if not model_output:
            logger.info("Model unavailable, heuristic fallback")
            return self._fallback(ctx)
        thinking = _extract_thinking(model_output)
        tool_calls = _extract_tool_calls(model_output)
        if tool_calls:
            logger.info(f"Model called {len(tool_calls)} tool(s), executing...")
            results = []
            for tc in tool_calls[:3]:
                result = self._execute_tool(tc.get("tool"), tc.get("params", {}))
                results.append(result)
            prompt = (
                f"Tool results:{json.dumps(results, indent=2)[:2000]}"
                f"Now output SIGNAL with your trading decision."
            )
            model_output = call_llama_swap(
                prompt,
                system_prompt=system,
                model=self.model,
                host=self.llama_host,
            )
        signal = _extract_signal(model_output)
        if signal:
            history_entry = {
                "cycle": ctx.cycle,
                "symbol": ctx.symbol,
                "signal": {
                    "action": signal.action,
                    "confidence": signal.confidence,
                    "reason": signal.reason,
                },
                "thinking": thinking,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._history.append(history_entry)
            return signal
        final_tc = _extract_tool_calls(model_output or "")
        if not final_tc:
            prompt = 'Output SIGNAL: {"action":"HOLD","confidence":0.3,"reason":"Analysis complete, no clear trade"}'
            model_output = call_llama_swap(
                prompt,
                system_prompt=system,
                model=self.model,
                host=self.llama_host,
            )
            signal = _extract_signal(model_output)
            if signal:
                return signal
        logger.info("No clear signal from model, heuristic fallback")
        return self._fallback(ctx)

    def _fallback(self, ctx: AgentContext) -> Signal:
        """Heuristic fallback using context data."""
        return _heuristic_signal(
            json.loads(ctx.ohlcv_json or "{}"),
            json.loads(ctx.portfolio_json or "{}"),
            json.loads(ctx.regime_json or "{}"),
            ctx.symbol,
        )

    def _execute_tool(self, tool_name: str, params: dict) -> dict:
        """Execute a single MCP tool call."""
        tool_map = {
            "get_ohlcv": lambda: self.mcp.get_ohlcv(**params),
            "get_portfolio": lambda: self.mcp.get_portfolio(),
            "get_regime": lambda: self.mcp.get_regime(**params),
            "get_economics": lambda: self.mcp.get_economics(),
            "submit_order": lambda: self.mcp.submit_order(**params),
            "render_chart": lambda: self.mcp.render_chart(**params),
        }
        fn = tool_map.get(tool_name)
        if fn is None:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"unknown tool: {tool_name}"}
        try:
            result = fn()
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"raw": result}
            return result
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return {"error": str(e)}

    @staticmethod
    def _trunc(s: str, max_len: int) -> str:
        if len(s) <= max_len:
            return s
        return s[:max_len] + f"\n... [truncated, {len(s) - max_len} more chars]"

    def get_state(self) -> dict:
        thinking_history = []
        for h in self._history[-50:]:
            if h.get("thinking"):
                thinking_history.append({
                    "cycle": h["cycle"],
                    "symbol": h["symbol"],
                    "thinking": h.get("thinking", []),
                    "action": h.get("signal", {}).get("action", "N/A"),
                })
        return {
            "name": self.name,
            "cycle_count": self._cycle_count,
            "history": self._history[-50:],
            "thinking_history": thinking_history,
            "config": {k: v for k, v in self.config.items() if k != "mcp_url"},
        }

    def load_state(self, state: dict) -> None:
        self._cycle_count = state.get("cycle_count", 0)
        self._history = state.get("history", [])

    def cycle_complete(self, signal: Signal, result: dict) -> None:
        super().cycle_complete(signal, result)


# ── Register ──────────────────────────────────────────────────

register_agent("trading_agent", TradingAgent)
register_agent(
    "heuristic",
    type(
        "HeuristicAgent",
        (TradingAgent,),
        {
            "__init__": lambda self, name="heuristic", config=None: (
                TradingAgent.__init__(self, name, config or {}),
                setattr(self, "use_model", False),
            )[0],
            "analyze": lambda self, ctx: _heuristic_signal(
                json.loads(ctx.ohlcv_json or "{}"),
                json.loads(ctx.portfolio_json or "{}"),
                json.loads(ctx.regime_json or "{}"),
                ctx.symbol,
            ),
        },
    ),
)


