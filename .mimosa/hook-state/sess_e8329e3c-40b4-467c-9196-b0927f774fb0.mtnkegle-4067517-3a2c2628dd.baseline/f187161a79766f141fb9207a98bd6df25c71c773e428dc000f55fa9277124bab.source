#!/usr/bin/env python3
"""Continuity test: prove cash/positions/fills survive a simulated restart.

Simulates:
  1. Fresh start with 3 positions + 3 fills
  2. Save state (paper_state.json + fills_ledger.jsonl)
  3. Simulated restart (new harness instance, same state_dir)
  4. Assert cash/positions/fills-history survive
  5. Forced reset via --reset-portfolio flag
"""
import json
import os
import sys
import tempfile
import shutil

# Add sandbox root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import OpenTraderHarness


def make_fill(order_id, symbol, side, qty, price, ts):
    return {
        "order_id": order_id,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "price": price,
        "cost": qty * price,
        "timestamp": ts,
    }


def test_restart_survival():
    """3 positions + 3 fills must survive a simulated restart."""
    tmpdir = tempfile.mkdtemp(prefix="ot_continuity_")
    try:
        # ── Phase 1: Fresh start, create 3 positions + 3 fills ──
        h1 = OpenTraderHarness(
            symbol="BTC/USDT",
            initial_cash=500.0,
            exchange="paper",
            state_dir=tmpdir,
            synthetic_data=False,
            use_model=False,
        )
        # Simulate 3 fills
        fills = [
            make_fill("paper_1", "BTC/USDT", "buy", 0.5, 60000.0, "2026-08-30T10:00:00Z"),
            make_fill("paper_2", "ETH/USDT", "buy", 5.0, 3000.0, "2026-08-30T10:01:00Z"),
            make_fill("paper_3", "SOL/USDT", "buy", 50.0, 150.0, "2026-08-30T10:02:00Z"),
        ]
        # Inject fills into the exchange
        h1.exchange._fills = fills
        h1.exchange._cash = 500.0 - (0.5 * 60000 + 5.0 * 3000 + 50.0 * 150)
        h1.exchange._positions = {"BTC/USDT": 0.5, "ETH/USDT": 5.0, "SOL/USDT": 50.0}
        h1.exchange._cost_basis = {
            "BTC/USDT": 0.5 * 60000,
            "ETH/USDT": 5.0 * 3000,
            "SOL/USDT": 50.0 * 150,
        }
        # Append fills to ledger
        h1._append_fills_to_ledger(fills)
        # Save state — write paper_state.json directly (bypass _record_state
        # which requires a live signal object)
        h1.state_mgr.write(
            cycle=1,
            portfolio={"cash": h1.exchange._cash, "total_value": h1.exchange._cash, "positions": h1.exchange._positions},
            positions=[
                {"symbol": "BTC/USDT", "quantity": 0.5, "entry_price": 60000.0, "current_price": 60000.0},
                {"symbol": "ETH/USDT", "quantity": 5.0, "entry_price": 3000.0, "current_price": 3000.0},
                {"symbol": "SOL/USDT", "quantity": 50.0, "entry_price": 150.0, "current_price": 150.0},
            ],
            fills=fills,
            prices={},
            regime={},
            symbol_regimes={},
            signals=[],
            models={"agent": "test", "stage": 1, "symbols": ["BTC/USDT"]},
            initial_cash=500.0,
            trades=[],
        )
        h1._save_agent_state()

        # Verify state files exist
        paper_path = os.path.join(tmpdir, "paper_state.json")
        ledger_path = os.path.join(tmpdir, "fills_ledger.jsonl")
        assert os.path.exists(paper_path), "paper_state.json not created"
        assert os.path.exists(ledger_path), "fills_ledger.jsonl not created"

        # Read back the saved state
        with open(paper_path) as f:
            saved = json.load(f)
        with open(ledger_path) as f:
            ledger_lines = [json.loads(l) for l in f if l.strip()]

        print(f"Phase 1: saved cash={saved['cash']:.2f}, "
              f"positions={len(saved['positions'])}, "
              f"fills_in_paper_state={len(saved['fills'])}, "
              f"fills_in_ledger={len(ledger_lines)}")

        # ── Phase 2: Simulated restart (new instance, same state_dir) ──
        h2 = OpenTraderHarness(
            symbol="BTC/USDT",
            initial_cash=500.0,
            exchange="paper",
            state_dir=tmpdir,
            synthetic_data=False,
            use_model=False,
        )
        # Check restored state
        bal = h2.exchange.get_balance()
        restored_fills = h2.exchange.get_fills()
        print(f"Phase 2: restored cash={bal.cash:.2f}, "
              f"positions={len(bal.positions)}, "
              f"fills={len(restored_fills)}")

        # ── Assertions ──
        errors = []
        if abs(bal.cash - saved["cash"]) > 0.01:
            errors.append(f"Cash mismatch: expected {saved['cash']:.2f}, got {bal.cash:.2f}")
        if len(bal.positions) != 3:
            errors.append(f"Position count mismatch: expected 3, got {len(bal.positions)}")
        if len(restored_fills) < 3:
            errors.append(f"Fills count mismatch: expected >=3, got {len(restored_fills)}")

        # Check specific positions
        for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
            if sym not in bal.positions:
                errors.append(f"Missing position: {sym}")

        if errors:
            for e in errors:
                print(f"  FAIL: {e}")
            return False
        else:
            print("PASS: cash/positions/fills survived restart")
            return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_forced_reset():
    """--reset-portfolio must wipe state and start fresh."""
    tmpdir = tempfile.mkdtemp(prefix="ot_reset_")
    try:
        # Create state first
        h1 = OpenTraderHarness(
            symbol="BTC/USDT",
            initial_cash=500.0,
            exchange="paper",
            state_dir=tmpdir,
            synthetic_data=False,
            use_model=False,
        )
        fills = [make_fill("paper_1", "BTC/USDT", "buy", 0.5, 60000.0, "2026-08-30T10:00:00Z")]
        h1.exchange._fills = fills
        h1.exchange._cash = 20000.0
        h1.exchange._positions = {"BTC/USDT": 0.5}
        h1.exchange._cost_basis = {"BTC/USDT": 30000.0}
        h1._append_fills_to_ledger(fills)
        h1.state_mgr.write(
            cycle=1,
            portfolio={"cash": h1.exchange._cash, "total_value": h1.exchange._cash, "positions": h1.exchange._positions},
            positions=[{"symbol": "BTC/USDT", "quantity": 0.5, "entry_price": 60000.0, "current_price": 60000.0}],
            fills=fills,
            prices={},
            regime={},
            symbol_regimes={},
            signals=[],
            models={"agent": "test", "stage": 1, "symbols": ["BTC/USDT"]},
            initial_cash=500.0,
            trades=[],
        )
        h1._save_agent_state()

        paper_path = os.path.join(tmpdir, "paper_state.json")
        ledger_path = os.path.join(tmpdir, "fills_ledger.jsonl")
        assert os.path.exists(paper_path)
        assert os.path.exists(ledger_path)

        # Now restart with reset_portfolio=True
        h2 = OpenTraderHarness(
            symbol="BTC/USDT",
            initial_cash=500.0,
            exchange="paper",
            state_dir=tmpdir,
            synthetic_data=False,
            use_model=False,
            reset_portfolio=True,
        )
        # State files should be wiped
        if os.path.exists(paper_path):
            print("FAIL: paper_state.json still exists after reset")
            return False
        if os.path.exists(ledger_path):
            print("FAIL: fills_ledger.jsonl still exists after reset")
            return False
        # Cash should be initial
        bal = h2.exchange.get_balance()
        if abs(bal.cash - 500.0) > 0.01:
            print(f"FAIL: cash after reset = {bal.cash}, expected 500.0")
            return False
        if len(bal.positions) != 0:
            print(f"FAIL: positions after reset = {len(bal.positions)}, expected 0")
            return False
        print("PASS: forced reset wiped state, cash=500.0, positions=0")
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 60)
    print("CONTINUITY TEST — fills/equity survival across restarts")
    print("=" * 60)
    ok1 = test_restart_survival()
    print()
    ok2 = test_forced_reset()
    print()
    print("=" * 60)
    if ok1 and ok2:
        print("ALL TESTS PASSED")
    else:
        print("TESTS FAILED")
        sys.exit(1)
