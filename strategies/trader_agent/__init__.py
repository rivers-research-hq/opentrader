"""Agentic trading prototype — a ReAct agent that votes on FX pairs daily.

Architecture
  The agent receives a daily feature vector (bars + macro + regime flags) for
  one pair, reasons about it with a short chain-of-thought, and outputs a
  decision (BUY/SELL/HOLD + conviction 0-1). Decisions are scored against the
  next day's close-to-close return. No positions, no P&L, no live orders.

Status
  Prototype — runs against historical data to build a track record.
  Graduates to daily paper voting after N>50 periods scored above random.
"""

VERSION = "0.1.0-prototype"
