#!/usr/bin/env python3
"""Base Agent — ABC + registry for all trading agents.

Every agent produces Signals from market context.
Models call MCP tools; the agent orchestrates.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class Signal:
    """A trading signal produced by an agent."""

    action: str  # BUY, SELL, HOLD
    symbol: str  # Trading pair
    confidence: float = 0.0  # 0.0 - 1.0
    reason: str = ""  # Why this signal
    position_pct: float = 0.0  # % of portfolio to risk
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Full context passed to an agent each cycle."""

    symbol: str
    timeframe: str
    cycle: int
    ohlcv_json: str = ""  # Pre-fetched OHLCV data (LLM-friendly text summary)
    portfolio_json: str = ""  # Current portfolio JSON
    regime_json: str = ""  # Regime analysis JSON
    economics_json: str = ""  # Economic indicators JSON
    news_json: str = ""  # Crypto news & sentiment JSON
    fundamentals_json: str = ""  # Fundamentals (SEC EDGAR) context
    valuation_json: str = ""  # DCF/EPV/Quality valuation context
    funding_json: str = ""  # Perp funding rates context (wayfinder #22)
    depth_json: str = ""  # Order-book depth context (wayfinder #22)
    fred_json: str = ""  # FRED macro context block (wayfinder #20)
    # Typed data for heuristic fallback (avoids json.loads round-trip on text fields)
    ohlcv_bars: Optional[List[Any]] = (
        None  # List[OHLCV] raw bars for heuristic computation
    )
    portfolio_dict: Optional[Dict[str, Any]] = None  # Raw portfolio dict for heuristic
    regime_dict: Optional[Dict[str, Any]] = None  # Raw regime dict for heuristic


class BaseAgent(ABC):
    """Abstract trading agent. 3 methods to implement."""

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}
        self._cycle_count = 0

    @abstractmethod
    def analyze(self, ctx: AgentContext) -> Signal:
        """Analyze market context and produce a trading Signal."""
        ...

    @abstractmethod
    def get_state(self) -> dict:
        """Return agent state for persistence."""
        ...

    @abstractmethod
    def load_state(self, state: dict) -> None:
        """Restore agent state from persistence."""
        ...

    def cycle_complete(self, signal: Signal, result: dict) -> None:
        """Called after a signal is submitted (for learning/adaptation)."""
        self._cycle_count += 1


# ── Registry ──
_AGENT_REGISTRY: Dict[str, type] = {}


def register_agent(name: str, cls: type) -> None:
    _AGENT_REGISTRY[name.lower()] = cls


def get_agent(name: str, config: dict = None) -> Optional[BaseAgent]:
    cls = _AGENT_REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(name=name, config=config)


def list_agents() -> List[str]:
    return sorted(_AGENT_REGISTRY.keys())
