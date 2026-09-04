#!/usr/bin/env python3
"""OpenTrader Agent System — models call tools via MCP.

Architecture:
    MCPClient (REST) → TradingAgent (model + tools) → Harness (loop)
"""
from .base import BaseAgent, Signal, register_agent, get_agent, list_agents
from .mcp_client import MCPClient
from .trading_agent import TradingAgent

__all__ = [
    "BaseAgent", "Signal", "register_agent", "get_agent", "list_agents",
    "MCPClient", "TradingAgent",
]
