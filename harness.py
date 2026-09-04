#!/usr/bin/env python3
"""OpenTrader Harness — the event loop.

Architecture (sync-only, matching the spec):
  Exchange → Agent (MCP tools) → Risk → State → Dashboard

The model calls tools via MCP. The harness orchestrates the cycle.
"""

import argparse
import concurrent.futures
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on path
PROJECT = str(Path(__file__).resolve().parent)
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

from agent import TradingAgent, MCPClient, BaseAgent, Signal
from exchange.base import ExchangeBase, get_exchange, OHLCV
from exchange.paper import PaperExchange
from exchange.multi_router import MultiExchangeRouter
from data.synthetic import generate_bars, generate_trending_bars
from mot.tradable_universe import TRADABLE_UNIVERSE, DEFAULT_START_PRICES, SCOUT_PROMPT
from mot.dynamic_discovery import (
    resolve_discovery,
    get_sector_list,
    PRICE_ESTIMATES,
    refresh_from_exchange,
)
from mot.monitors import CommitteeChair
from data.regime_classifier import classify_regime
from risk.manager import RiskManager, RiskConfig
from risk.regime_adaptation import get_regime_instructions, get_regime_risk_overrides
from risk.asset_allocator import AssetClassAllocator
from state.manager import StateManager
from state.context import AccountContext, FEE_TABLES
from training.real_pattern_bank import RealTradePatternBank
from mot.trader_md import TraderMD, distill_coach_report, distill_atdl_action

logger = logging.getLogger("opentrader.harness")


def _find_gpu_python() -> str:
    """Find a Python executable with ROCm/CUDA and Unsloth.

    Checks known ROCm venvs. Falls back to sys.executable.
    """
    candidates = [
        os.path.expanduser("~/rocm_venv/bin/python3"),
        os.path.expanduser("~/rocm_venv/bin/python"),
        sys.executable,
    ]
    for py in candidates:
        if os.path.isfile(py):
            return py
    return sys.executable


# — Hardware Funding Goal —
# Opentrader's current objective: grow paper capital to fund real hardware.
# Target: $270 (MI60 32GB ~$120 + 64GB DDR4 ~$60 + 2TB NVMe ~$90)
GOAL_CAPITAL: float = 270.0

# — Progression Stages —
# Agent graduates to more symbols as it proves profitability.
# Each stage requires: minimum hours running AND minimum % return.
STAGES: Dict[int, Dict[str, Any]] = {
    1: {
        "symbols": ["BTC/USDT"],
        "label": "BTC Only",
        "unlock_hours": 6,
        "unlock_return_pct": 1.0,
    },
    2: {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "label": "Crypto Basket",
        "unlock_hours": 24,
        "unlock_return_pct": 5.0,
    },
    3: {
        "symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AAPL", "NVDA", "SONY"],
        "label": "Crypto + Equities",
        "unlock_hours": 48,
        "unlock_return_pct": 10.0,
    },
}
MAX_STAGE = max(STAGES.keys()) if STAGES else 1

# — Minimum hold cycles: prevent flip-flop sells —
# Positions no longer subject
MIN_HOLD_CYCLES: int = 3


# — Main Class Definition —
class Harness:
    """The central orchestrator running the event loop."""

    def __init__(self, symbol: str = "BTC/USDT"):
        self.symbol = symbol
        self.state: Optional[StateManager] = None
        self.risk: Optional[RiskManager] = None
        self.agent: Optional[TradingAgent] = None
        
        # Initialize core components safely
        try:
            self.agent = TradingAgent(symbol=self.symbol)
            self.risk = RiskManager()
            self.state = StateManager()
        except (ImportError, NameError):
            logger.debug("Agent components optional initialized")
            
    def _get_goal_context(self) -> str:
        """Inject current state into the global GOAL_DESCRIPTION context."""
        current_balance = self.state.get_current_balance() if self.state else 0.0
        progress = (current_balance / GOAL_CAPITAL) * 100
        remaining = GOAL_CAPITAL - current_balance
        
        return f"""
        HARDWARE FUND GOAL: Accumulate ${GOAL_CAPITAL:.0f} for LLM upgrades. 
        Current paper balance: ${current_balance:.2f}. 
        Progress: {progress:.1f}% (need ${remaining:.2f} more). 
        Target hardware: MI60 32GB GPU + 64GB DDR4 RAM + 2TB NVMe for running larger models. 
        Use this as your primary strategic objective. Grow capital through repeated small wins, 
        not Hail Mary trades. Protect the downside — you can't buy hardware from a blown account.
        """
    
    def _update_stage(self):
        """Logic to promote stage based on MIN_HOLD_CYCLES."""
        if self.state and self.state.get_cycle() >= 6:
            logger.info(f"Cycle {self.state.get_cycle()}, considering stage unlock.")
            
    def run_cycle(self, time_frame: str = "1h"):
        """Run a single market cycle."""
        if self.agent:
            self.agent.run_cycle(time_frame=time_frame)
        else:
            logger.debug("Agent not present, running in shadow mode.")
            
    def run(self, time_frame: str = "1h"):
        """The main event loop runner."""
        def signal_handler(sig, frame):
            logger.info("Signal received, shutting down gracefully...")
            if self.state:
                self.state.save()
            sys.exit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            # Register handlers
            pass
        
        while True:
            if self.state and self.state.get_cycle() > 0:
                self.state.load()
                self._update_stage()
                self.run_cycle(time_frame=time_frame)
            else:
                self.agent.warmup() if self.agent else logger.info("Warmup run initiated.")
            
            # Check Stage Unlocking logic
            if self.state:
                current_cycle = self.state.get_cycle()
                current_return = self.state.get_return_pct()
                
                # Check if Stage 2 is unlocked (example logic)
                # if current_cycle >= 24 and current_return >= 5.0: ...
                
            # Check Goal Progress
            goal_pct = (self.state.get_current_balance() / GOAL_CAPITAL) * 100 if self.state else 0
            if goal_pct > 110:  # 10% buffer
                logger.info("Goal Capital reached, escalating risk.")
                break
            
            # Yield to allow other threads (if running concurrently)
            time.sleep(60)
            
        # Finalize
        if self.state:
            self.state.save()


# — Harness Runner Entry —
def main(args=None):
    parser = argparse.ArgumentParser(description="OpenTrader Harness")
    parser.add_argument("--symbols", "-s", default="BTC/USDT", help="Primary symbols")
    parser.add_argument("--timeframe", "-t", default="1h", help="Default timeframe")
    parser.add_argument("--state-dir", help="Where to save state")
    
    parsed = parser.parse_args(args)
    
    # Create the instance
    harness = Harness(symbol=parsed.symbols)
    
    # Optionally inject state manager from outside
    if parsed.state_dir:
        from state.manager import StateManager
        harness.state = StateManager(dir=parsed.state_dir)
        
    # Start the engine
    harness.run(time_frame=parsed.timeframe)


if __name__ == "__main__":
    main()