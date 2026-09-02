#!/usr/bin/env python3
"""Exchange Adapter ABC — plug any venue into OpenTrader.

Ported from ATLANTIS TraderHarness. Same interface, zero async.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from state.context import FeeSchedule


@dataclass
class OHLCV:
    """One OHLCV bar — the universal market data unit."""
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_dict(cls, d: dict) -> "OHLCV":
        return cls(
            timestamp=int(d.get("timestamp", d.get("time", 0))),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
            volume=float(d["volume"]),
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass
class OrderResult:
    """Result of placing an order."""
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str
    timestamp: str
    raw: dict = field(default_factory=dict)


@dataclass
class Balance:
    """Account balance snapshot."""
    cash: float
    total_value: float
    positions: Dict[str, float] = field(default_factory=dict)


class ExchangeBase(ABC):
    """Abstract exchange adapter. 5 methods to implement."""

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}
        self._connected = False

    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> List[OHLCV]:
        ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> Optional[float]:
        ...

    @abstractmethod
    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = "market", price: Optional[float] = None) -> OrderResult:
        ...

    @abstractmethod
    def get_balance(self) -> Balance:
        ...

    def disconnect(self) -> None:
        pass

    def get_fee_schedule(self, symbol: str = "default") -> FeeSchedule:
        """Return the fee schedule for a given symbol. Override per-exchange."""
        from state.context import FEE_TABLES
        table = FEE_TABLES.get(self.name.lower(), FEE_TABLES.get("paper", {}))
        return table.get("default", FeeSchedule())

    def get_name(self) -> str:
        return self.name

    def is_connected(self) -> bool:
        return self._connected

    def discover_symbols(self, max_symbols: int = 20) -> List[str]:
        """Return all tradable symbols available on this exchange.
        
        Subclasses should override to fetch live symbol lists from the provider.
        Returns empty list by default — caller should fall back to hardcoded universe.
        """
        return []


_REGISTRY: Dict[str, type] = {}

def register_exchange(name: str, cls: type) -> None:
    _REGISTRY[name.lower()] = cls

def get_exchange(name: str, config: dict = None) -> Optional[ExchangeBase]:
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(name=name, config=config)

def list_exchanges() -> List[str]:
    return sorted(_REGISTRY.keys())
