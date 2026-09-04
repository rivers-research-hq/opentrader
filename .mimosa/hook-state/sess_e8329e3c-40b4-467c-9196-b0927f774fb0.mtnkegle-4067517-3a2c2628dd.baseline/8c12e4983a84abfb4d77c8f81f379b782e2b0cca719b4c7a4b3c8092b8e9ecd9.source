#!/usr/bin/env python3
"""RealTradePatternBank — extract labeled patterns from closed trades.

Reads paper_state.json trades, agent_state.json signal history, and
symbol_regimes to build a labeled dataset of real trading decisions.
Each pattern: {context: {symbol, signal, regime, price, indicators}, label: outcome}

Used by: TrainingController, FlashTrainer, data_builder (fine-tuning export).
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("opentrader.real_pattern_bank")


@dataclass
class RealTradePattern:
    """A single real trade pattern with context and outcome label."""
    symbol: str
    entry_cycle: int
    exit_cycle: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl_pct: float
    pnl_dollar: float
    outcome: str          # WIN / LOSS / BE
    exit_reason: str      # manual_SELL / stop_loss / take_profit / max_time

    # Context at entry time
    signal_action: str = ""
    signal_confidence: float = 0.0
    signal_reason: str = ""
    position_pct: float = 0.0
    regime: str = "unknown"
    regime_confidence: float = 0.0
    regime_thesis: str = ""
    regime_indicators: dict = field(default_factory=dict)

    # Metadata
    entry_timestamp: str = ""
    exit_timestamp: str = ""
    duration_cycles: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def context_summary(self) -> str:
        """Human-readable context string for training."""
        parts = [
            f"Symbol: {self.symbol}",
            f"Price: ${self.entry_price:.2f}",
            f"Regime: {self.regime} ({self.regime_confidence:.0%})",
            f"Signal: {self.signal_action} (conf={self.signal_confidence:.2f})",
            f"Position: {self.position_pct:.1%}",
        ]
        if self.signal_reason:
            parts.append(f"Reason: {self.signal_reason[:80]}")
        return "\n".join(parts)

    def label_text(self) -> str:
        """Label as text for training."""
        if self.outcome == "WIN":
            return f"WIN (+{self.pnl_pct*100:.2f}%, +${self.pnl_dollar:.2f})"
        elif self.outcome == "LOSS":
            return f"LOSS ({self.pnl_pct*100:.2f}%, ${self.pnl_dollar:.2f})"
        else:
            return f"BREAK-EVEN ({self.pnl_pct*100:.4f}%)"


class RealTradePatternBank:
    """Extract and manage labeled patterns from real trades.

    Reads from:
        paper_state.json  — closed trades with entry/exit prices, PnL
        agent_state.json  — signal history (context at entry time)
        symbol_regimes    — per-symbol regime classification

    Usage:
        bank = RealTradePatternBank("/path/to/data")
        patterns = bank.extract_patterns(min_pnl_abs=0.001)
        print(bank.summary())
    """

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.state_dir = Path(state_dir)
        self.patterns: List[RealTradePattern] = []
        self._trades_cache: Optional[List[dict]] = None
        self._signals_cache: Optional[List[dict]] = None
        self._regimes_cache: Optional[dict] = None

    # ── Data loading ──────────────────────────────────────────

    def _load_trades(self) -> List[dict]:
        if self._trades_cache is not None:
            return self._trades_cache
        path = self.state_dir / "paper_state.json"
        if not path.exists():
            return []
        try:
            state = json.loads(path.read_text())
            trades = state.get("trades", [])
            self._trades_cache = trades
            return trades
        except Exception as e:
            logger.warning(f"Could not load trades: {e}")
            return []

    def _load_signals(self) -> List[dict]:
        if self._signals_cache is not None:
            return self._signals_cache
        path = self.state_dir / "agent_state.json"
        if not path.exists():
            return []
        try:
            state = json.loads(path.read_text())
            signals = state.get("_signal_history", [])
            self._signals_cache = signals
            return signals
        except Exception as e:
            logger.warning(f"Could not load signals: {e}")
            return []

    def _load_regimes(self) -> Dict[str, dict]:
        if self._regimes_cache is not None:
            return self._regimes_cache
        path = self.state_dir / "paper_state.json"
        if not path.exists():
            return {}
        try:
            state = json.loads(path.read_text())
            regimes = state.get("symbol_regimes", {})
            self._regimes_cache = regimes
            return regimes
        except Exception as e:
            logger.warning(f"Could not load regimes: {e}")
            return {}

    # ── Matching logic ───────────────────────────────────────

    def _find_signal_at_cycle(
        self, signals: List[dict], symbol: str, min_cycle: int, max_cycle: int
    ) -> Optional[dict]:
        """Find the most relevant signal for a trade entry.

        Looks for a BUY signal for the same symbol where the signal timestamp
        falls between the trade entry and exit cycles.
        """
        candidates = []
        for sig in signals:
            if sig.get("symbol") != symbol:
                continue
            if sig.get("action") != "BUY":
                continue
            ts = sig.get("timestamp", "")
            if not ts:
                continue
            try:
                ts_dt = datetime.fromisoformat(ts)
                # Use timestamp-based matching if available
                candidates.append((ts_dt, sig))
            except (ValueError, TypeError):
                continue

        if candidates:
            # Return the latest signal before exit (most relevant for entry)
            candidates.sort(key=lambda x: x[0])
            # Find the one closest to min_cycle (entry)
            return candidates[0][1] if len(candidates) == 1 else candidates[-1][1]

        # Fallback: return first BUY signal for this symbol
        for sig in signals:
            if sig.get("symbol") == symbol and sig.get("action") == "BUY":
                return sig
        return None

    def _find_regime(self, regimes: Dict[str, dict], symbol: str) -> dict:
        """Find the regime for a given symbol."""
        return regimes.get(symbol, {})

    # ── Pattern extraction ───────────────────────────────────

    def extract_patterns(
        self,
        min_pnl_abs: float = 0.0001,   # Minimum absolute PnL% to count as WIN/LOSS
        min_quantity: float = 0.0,      # Minimum trade quantity
        max_patterns: int = 1000,       # Cap total patterns
        skip_be: bool = False,          # Skip break-even trades
        reload: bool = False,           # Force reload from disk
    ) -> List[RealTradePattern]:
        """Extract labeled patterns from all closed trades.

        Args:
            min_pnl_abs: Trades with |pnl_pct| < this are classified as BREAK-EVEN
            min_quantity: Skip tiny dust trades
            max_patterns: Limit total patterns returned
            skip_be: If True, omit break-even trades (for WIN/LOSS-only training)
            reload: Force re-read from disk (otherwise uses caches)

        Returns:
            List of RealTradePattern objects
        """
        if reload:
            self._trades_cache = None
            self._signals_cache = None
            self._regimes_cache = None

        trades = self._load_trades()
        signals = self._load_signals()
        regimes = self._load_regimes()

        if not trades:
            logger.warning("No trades found in paper_state.json")
            return []

        patterns = []
        for trade in trades:
            if len(patterns) >= max_patterns:
                break

            symbol = trade.get("symbol", "")
            entry_price = float(trade.get("entry_price", 0))
            exit_price = float(trade.get("exit_price", 0))
            quantity = float(trade.get("quantity", 0))
            pnl_pct = float(trade.get("pnl_pct", 0))
            pnl_dollar = float(trade.get("pnl_dollar", 0))
            exit_reason = trade.get("exit_reason", "unknown")
            entry_cycle = trade.get("entry_cycle", 0)
            exit_cycle = trade.get("exit_cycle", 0)

            if not symbol or entry_price <= 0:
                continue
            if quantity < min_quantity:
                continue

            # Classify outcome
            if abs(pnl_pct) < min_pnl_abs:
                outcome = "BE"
                if skip_be:
                    continue
            elif pnl_pct > 0:
                outcome = "WIN"
            else:
                outcome = "LOSS"

            # Find signal context
            signal = self._find_signal_at_cycle(
                signals, symbol, entry_cycle, exit_cycle
            )

            # Find regime context
            regime = self._find_regime(regimes, symbol)

            pattern = RealTradePattern(
                symbol=symbol,
                entry_cycle=entry_cycle,
                exit_cycle=exit_cycle,
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                pnl_pct=pnl_pct,
                pnl_dollar=pnl_dollar,
                outcome=outcome,
                exit_reason=exit_reason,
                signal_action=signal.get("action", "") if signal else "",
                signal_confidence=signal.get("confidence", 0) if signal else 0,
                signal_reason=signal.get("reason", "") if signal else "",
                position_pct=signal.get("position_pct", 0) if signal else 0,
                regime=regime.get("regime", "unknown"),
                regime_confidence=regime.get("confidence", 0),
                regime_thesis=regime.get("thesis", ""),
                regime_indicators=regime.get("indicators", {}),
                entry_timestamp=trade.get("entry_timestamp", ""),
                exit_timestamp=trade.get("exit_timestamp", ""),
                duration_cycles=exit_cycle - entry_cycle,
            )
            patterns.append(pattern)

        self.patterns = patterns
        logger.info(
            f"Extracted {len(patterns)} patterns: "
            f"{self._count_outcome('WIN')}W / "
            f"{self._count_outcome('LOSS')}L / "
            f"{self._count_outcome('BE')}BE"
        )
        return patterns

    def _count_outcome(self, outcome: str) -> int:
        return sum(1 for p in self.patterns if p.outcome == outcome)

    # ── Query methods ─────────────────────────────────────────

    def get_winners(self) -> List[RealTradePattern]:
        return [p for p in self.patterns if p.outcome == "WIN"]

    def get_losers(self) -> List[RealTradePattern]:
        return [p for p in self.patterns if p.outcome == "LOSS"]

    def get_be(self) -> List[RealTradePattern]:
        return [p for p in self.patterns if p.outcome == "BE"]

    def get_by_symbol(self, symbol: str) -> List[RealTradePattern]:
        return [p for p in self.patterns if p.symbol == symbol]

    def get_recent(self, n: int = 10) -> List[RealTradePattern]:
        return self.patterns[-n:]

    def summary(self) -> dict:
        """Return summary statistics for dashboard / API."""
        if not self.patterns:
            return {"count": 0, "wins": 0, "losses": 0, "be": 0}

        wins = self.get_winners()
        losses = self.get_losers()
        total = len(self.patterns)

        avg_win = sum(p.pnl_pct for p in wins) / max(1, len(wins))
        avg_loss = sum(p.pnl_pct for p in losses) / max(1, len(losses))
        avg_conf_win = sum(p.signal_confidence for p in wins) / max(1, len(wins))
        avg_conf_loss = sum(p.signal_confidence for p in losses) / max(1, len(losses))

        # Regime breakdown
        regime_wins: Dict[str, int] = {}
        regime_total: Dict[str, int] = {}
        for p in self.patterns:
            regime_total[p.regime] = regime_total.get(p.regime, 0) + 1
            if p.outcome == "WIN":
                regime_wins[p.regime] = regime_wins.get(p.regime, 0) + 1

        regime_stats = {
            r: {"wins": regime_wins.get(r, 0), "total": t,
                "win_rate": regime_wins.get(r, 0) / max(1, t)}
            for r, t in regime_total.items()
        }

        return {
            "count": total,
            "wins": len(wins),
            "losses": len(losses),
            "be": self._count_outcome("BE"),
            "win_rate": len(wins) / max(1, len(wins) + len(losses)),
            "avg_win_pct": round(avg_win * 100, 2),
            "avg_loss_pct": round(avg_loss * 100, 2),
            "avg_conf_winners": round(avg_conf_win, 2),
            "avg_conf_losers": round(avg_conf_loss, 2),
            "regime_breakdown": regime_stats,
            "symbols": list(set(p.symbol for p in self.patterns)),
        }

    # ── Export methods ────────────────────────────────────────

    def to_jsonl(self, path: str = None) -> Path:
        """Export patterns as JSONL (one per line)."""
        if path is None:
            path = self.state_dir / "training" / "real_patterns.jsonl"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for p in self.patterns:
                f.write(json.dumps(p.to_dict()) + "\n")
        logger.info(f"Exported {len(self.patterns)} patterns to {path}")
        return path

    def to_sharegpt(self, path: str = None, version: str = "Ptolemy-S0") -> Path:
        """Export as ShareGPT-formatted JSONL for fine-tuning.

        Each entry:
        {
          "conversations": [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."}
          ]
        }
        """
        if path is None:
            path = self.state_dir / "training" / "real_patterns_sharegpt.jsonl"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        system_prompt = (
            f"You are a crypto trading agent (version {version}). "
            "Given market context at entry, predict whether a trade will be profitable. "
            "Consider regime, signal confidence, and market conditions. "
            "Respond with WIN, LOSS, or BREAK-EVEN and a brief reasoning."
        )

        count = 0
        with open(path, "w") as f:
            for p in self.patterns:
                user_msg = (
                    f"Symbol: {p.symbol}\n"
                    f"Entry Price: ${p.entry_price:.2f}\n"
                    f"Position Size: {p.position_pct:.1%}\n"
                    f"Regime: {p.regime} (confidence: {p.regime_confidence:.0%})\n"
                    f"Thesis: {p.regime_thesis}\n"
                    f"Signal: {p.signal_action} (confidence: {p.signal_confidence:.2f})\n"
                    f"Signal Reason: {p.signal_reason[:120]}\n"
                    f"Indicators: ADX={p.regime_indicators.get('adx','?')}, "
                    f"BB={p.regime_indicators.get('bb_width','?')}, "
                    f"Vol={p.regime_indicators.get('volume_ratio','?')}"
                )
                assistant_msg = (
                    f"Outcome: {p.outcome}\n"
                    f"PnL: {p.pnl_pct*100:+.2f}% (${p.pnl_dollar:+.2f})\n"
                    f"Reasoning: Trade closed after {p.duration_cycles} cycles "
                    f"via {p.exit_reason}"
                )
                entry = {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": assistant_msg},
                    ]
                }
                f.write(json.dumps(entry) + "\n")
                count += 1

        logger.info(f"Exported {count} ShareGPT patterns to {path}")
        return path


# ── CLI ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract real trade patterns")
    parser.add_argument("--state-dir", default=None, help="Path to state dir (default: opentrader/data)")
    parser.add_argument("--min-pnl", type=float, default=0.0001, help="Min abs PnL%% for WIN/LOSS")
    parser.add_argument("--skip-be", action="store_true", help="Skip break-even trades")
    parser.add_argument("--export-jsonl", action="store_true", help="Export patterns as JSONL")
    parser.add_argument("--export-sharegpt", action="store_true", help="Export as ShareGPT JSONL")
    parser.add_argument("--version", default="Ptolemy-S0", help="Version string for ShareGPT export")
    parser.add_argument("--summary", action="store_true", default=True, help="Print summary")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    bank = RealTradePatternBank(args.state_dir)
    patterns = bank.extract_patterns(
        min_pnl_abs=args.min_pnl,
        skip_be=args.skip_be,
    )

    if args.summary and patterns:
        s = bank.summary()
        print(f"\n{'='*50}")
        print(f"RealTradePatternBank Summary")
        print(f"{'='*50}")
        print(f"Total patterns: {s['count']}")
        print(f"Wins: {s['wins']} ({s['win_rate']:.1%} win rate)")
        print(f"Losses: {s['losses']}")
        print(f"Break-even: {s['be']}")
        print(f"Avg win PnL: +{s['avg_win_pct']}%")
        print(f"Avg loss PnL: {s['avg_loss_pct']}%")
        print(f"Avg confidence (winners): {s['avg_conf_winners']:.2f}")
        print(f"Avg confidence (losers): {s['avg_conf_losers']:.2f}")
        print(f"Symbols: {', '.join(s['symbols'])}")
        print(f"\nRegime breakdown:")
        for r, info in sorted(s['regime_breakdown'].items()):
            print(f"  {r:20s}: {info['wins']}/{info['total']} wins ({info['win_rate']:.0%})")

    if args.export_jsonl:
        bank.to_jsonl()
    if args.export_sharegpt:
        bank.to_sharegpt(version=args.version)
