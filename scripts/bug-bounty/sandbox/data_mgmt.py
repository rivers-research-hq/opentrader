#!/usr/bin/env python3
"""Data Management — prune, archive, and analyze cycle history.

Usage:
    # Dry-run: show what would be pruned
    python3 data_mgmt.py --dry-run --max-cycles 10000

    # Prune dead HOLD cycles (no PV/position/trade change)
    python3 data_mgmt.py --prune-dead

    # Archive old cycles before a given cycle number
    python3 data_mgmt.py --archive-before 10000 --archive-dir /path/to/archive

    # Print stats about cycle history
    python3 data_mgmt.py --stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("opentrader.data_mgmt")


def state_key(state: dict) -> str:
    """Deterministic hash of meaningful trading state — matches StateManager.state_key."""
    positions = state.get("positions", [])
    pos_str = ";".join(sorted(
        f"{p.get('symbol','')}:{p.get('size',0):.6f}:{p.get('entry_price',0):.2f}"
        for p in positions
    )) if positions else ""

    trades = state.get("trades", [])
    trade_str = ";".join(
        f"{t.get('symbol','')}:{t.get('side','')}:{t.get('pnl',0):.4f}"
        for t in trades[-5:]
    ) if trades else ""

    committee = state.get("Committee", {})
    comm_str = f"{committee.get('action','')}:{committee.get('confidence',0):.2f}"

    raw = (
        f"pv={state.get('portfolio_value',0):.2f}|"
        f"cash={state.get('cash',0):.2f}|"
        f"pos={pos_str}|"
        f"fil_ct={len(state.get('fills',[]))}|"
        f"trade_ct={len(state.get('trades',[]))}|"
        f"sig_ct={len(state.get('signals',[]))}|"
        f"comm={comm_str}|"
        f"trd={trade_str}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def list_cycle_files(history_dir: Path) -> List[Tuple[int, Path]]:
    """Return sorted (cycle_num, path) pairs."""
    files = []
    for fn in history_dir.glob("cycle_*.json"):
        try:
            cycle_num = int(fn.stem.split("_")[1])
            files.append((cycle_num, fn))
        except (ValueError, IndexError):
            pass
    return sorted(files, key=lambda x: x[0])


def is_dead_cycle(state: dict) -> bool:
    """Return True if this cycle contains zero trading signal.

    Dead cycle: no fills, no trades, no position changes, PV unchanged from cash.
    """
    # No fills at all
    if state.get("fills"):
        return False
    # Has actual trades in journal
    trades = state.get("trades", [])
    if trades:
        return False
    # Has positions (not empty list and not zero-value)
    positions = state.get("positions", [])
    if positions:
        for p in positions:
            if isinstance(p, dict) and p.get("size", 0) != 0:
                return False
    # Signals contain actual BUY/SELL actions
    signals = state.get("signals", [])
    for s in signals[-5:]:
        if s.get("action") in ("BUY", "SELL"):
            return False
    return True


def prune_dead_cycles(history_dir: Path, dry_run: bool = True) -> int:
    """Remove cycles with zero trading activity. Returns count removed."""
    recent_cutoff = min(f[0] for f in list_cycle_files(history_dir)[-50:]) if list_cycle_files(history_dir) else 0
    files = list_cycle_files(history_dir)
    removed = 0

    for cycle_num, path in files:
        # Always keep the most recent 50 cycles
        if cycle_num >= recent_cutoff:
            continue
        try:
            state = json.loads(path.read_text())
        except Exception:
            logger.warning("Corrupt file, skipping: %s", path.name)
            continue

        if is_dead_cycle(state):
            if dry_run:
                print(f"  Would remove: {path.name} (cycle {cycle_num})")
            else:
                path.unlink()
                if removed == 0:
                    print(f"  Pruning: {path.name}", end="", flush=True)
                if removed % 500 == 0 and removed > 0:
                    print(f" ... {removed}", end="", flush=True)
            removed += 1

    if not dry_run and removed > 0:
        print(f" ({removed} total)")
    return removed


def archive_before(history_dir: Path, before_cycle: int,
                   archive_dir: Path, dry_run: bool = True) -> int:
    """Archive cycles before a given cycle number. Returns count archived."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    files = list_cycle_files(history_dir)
    archived = 0

    for cycle_num, path in files:
        if cycle_num >= before_cycle:
            continue
        dest = archive_dir / path.name
        if dry_run:
            print(f"  Would move: {path.name} → {dest}")
        else:
            shutil.move(str(path), str(dest))
            if archived == 0:
                print(f"  Archiving: {path.name}", end="", flush=True)
            if archived % 500 == 0 and archived > 0:
                print(f" ... {archived}", end="", flush=True)
        archived += 1

    if not dry_run and archived > 0:
        print(f" ({archived} total)")
    return archived


def print_stats(history_dir: Path):
    """Print summary statistics of the cycle history."""
    files = list_cycle_files(history_dir)
    if not files:
        print("No cycle files found.")
        return

    total_size = sum(p.stat().st_size for _, p in files)
    dead_count = 0
    duplicate_keys = set()
    seen_keys = set()
    pv_set = set()
    total_trades = 0
    profitable_trades = 0
    buy_sell_count = 0
    hold_count = 0
    total_cycles = len(files)

    for cycle_num, path in files:
        try:
            state = json.loads(path.read_text())
        except Exception:
            continue

        pv = state.get("portfolio_value", 0)
        pv_set.add(round(pv, 2))

        key = state_key(state)
        if key in seen_keys:
            duplicate_keys.add(key)
        seen_keys.add(key)

        if is_dead_cycle(state):
            dead_count += 1

        for t in state.get("trades", []):
            total_trades += 1
            if t.get("pnl", 0) > 0:
                profitable_trades += 1

        for s in state.get("signals", [])[-5:]:
            if s.get("action") in ("BUY", "SELL"):
                buy_sell_count += 1
            else:
                hold_count += 1

    print(f"Cycle History: {history_dir}")
    print(f"  Total files:     {total_cycles:,}")
    print(f"  Total size:      {total_size / 1024 / 1024:.1f} MB")
    print(f"  Dead (no action): {dead_count:,} ({dead_count/max(total_cycles,1)*100:.0f}%)")
    print(f"  Duplicate keys:  {len(duplicate_keys)} unique duplicates across {total_cycles - len(seen_keys):,} files")
    print(f"  Unique PV vals:  {len(pv_set)} (of {total_cycles:,} cycles)")
    print(f"  Total trades:    {total_trades}")
    print(f"  Profitable:      {profitable_trades} ({profitable_trades/max(total_trades,1)*100:.0f}%)" if total_trades else "  No trades")
    print(f"  BUY/SELL sigs:   {buy_sell_count} ({buy_sell_count/max(buy_sell_count+hold_count,1)*100:.0f}%)")
    print(f"  HOLD sigs:       {hold_count} ({hold_count/max(buy_sell_count+hold_count,1)*100:.0f}%)")
    print(f"  Cycle span:      {files[0][0]} → {files[-1][0]}")


def main():
    parser = argparse.ArgumentParser(description="OpenTrader Cycle Data Manager")
    parser.add_argument("--state-dir", default="data",
                        help="State directory (default: data)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing")
    parser.add_argument("--prune-dead", action="store_true",
                        help="Remove cycles with zero trading activity")
    parser.add_argument("--archive-before", type=int, default=None,
                        help="Archive cycles before this cycle number")
    parser.add_argument("--archive-dir", default=None,
                        help="Directory for archived cycles")
    parser.add_argument("--stats", action="store_true",
                        help="Print cycle history statistics")
    parser.add_argument("--max-cycles", type=int, default=None,
                        help="Maximum cycles to keep (prunes oldest first)")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    project = Path(__file__).resolve().parent
    state_dir = (project / args.state_dir)
    if not state_dir.exists():
        state_dir = Path(args.state_dir)
    history_dir = state_dir / "history"

    if not history_dir.exists():
        print(f"No history directory found: {history_dir}")
        sys.exit(1)

    if args.stats:
        print_stats(history_dir)

    if args.prune_dead:
        action = "Would prune" if args.dry_run else "Pruning"
        print(f"{action} dead HOLD cycles from {history_dir}")
        count = prune_dead_cycles(history_dir, dry_run=args.dry_run)
        if count == 0:
            print("  No dead cycles to prune.")
        elif args.dry_run:
            print(f"  ({count:,} cycles would be removed)")

    if args.archive_before is not None:
        archive_dir = Path(args.archive_dir) if args.archive_dir else state_dir / "archive"
        action = "Would archive" if args.dry_run else "Archiving"
        print(f"{action} cycles before {args.archive_before} to {archive_dir}")
        count = archive_before(history_dir, args.archive_before, archive_dir,
                               dry_run=args.dry_run)
        if args.dry_run:
            print(f"  ({count:,} cycles would be archived)")

    if args.max_cycles:
        files = list_cycle_files(history_dir)
        if len(files) > args.max_cycles:
            cutoff = files[-(args.max_cycles + 1)][0] + 1
            archive_dir = state_dir / "archive"
            action = "Would archive" if args.dry_run else "Archiving"
            print(f"{action} {len(files) - args.max_cycles:,} cycles to keep {args.max_cycles}")
            archive_before(history_dir, cutoff, archive_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
