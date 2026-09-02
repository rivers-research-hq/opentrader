#!/usr/bin/env python3
"""OpenTrader Multi-Asset Coordinator — spawns & monitors multiple harness instances.

Phase 7: Launches separate harnesses per asset class, aggregates state,
provides a unified portfolio view. Each harness runs independently;
the coordinator watches their state files and reports aggregate metrics.

Usage:
    python3 coordinator.py --config multi_asset.yaml

Config format (YAML):
    instances:
      crypto:
        args: --live --symbols BTC/USDT,ETH/USDT,SOL/USDT --timeframe 1h
        state_dir: data/crypto
      equities:
        args: --symbols AAPL,NVDA --exchange paper --bars 500 --backtest --backtest-bars 5000
        state_dir: data/equities

Or pass instances directly on CLI:
    python3 coordinator.py \\
      --instance crypto:--live,--symbols,BTC/USDT,ETH/USDT:data/crypto \\
      --instance equities:--symbols,AAPL,NVDA,--backtest:data/equities
"""
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("opentrader.coordinator")


class HarnessInstance:
    """Tracks a single harness subprocess."""
    def __init__(self, name: str, args: List[str], state_dir: str):
        self.name = name
        self.args = args
        self.state_dir = Path(state_dir)
        self.process: Optional[subprocess.Popen] = None
        self.cycles: int = 0
        self.portfolio_value: float = 0
        self.cash: float = 0
        self.positions: int = 0
        self.return_pct: float = 0
        self.running: bool = False

    def start(self) -> bool:
        cmd = [sys.executable, str(Path(__file__).parent / "harness.py")] + self.args
        logger.info(f"[{self.name}] Starting: {' '.join(cmd[:4])}...")
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
            self.running = True
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Failed to start: {e}")
            return False

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.running = False

    def read_state(self) -> dict:
        """Read the paper_state.json from this instance and update metrics."""
        state_file = self.state_dir / "paper_state.json"
        if not state_file.exists():
            return {}
        try:
            data = json.loads(state_file.read_text())
            self.cycles = data.get("cycle", 0)
            self.portfolio_value = data.get("portfolio_value", 0)
            self.cash = data.get("cash", 0)
            self.positions = len(data.get("positions", []))
            init = data.get("initial_cash", 100000)
            self.return_pct = ((self.portfolio_value - init) / init * 100) if init else 0
            return data
        except Exception:
            return {}

    def check_alive(self) -> bool:
        if self.process:
            self.running = self.process.poll() is None
        return self.running


class MultiAssetCoordinator:
    """Manages multiple harness instances with aggregated state."""

    def __init__(self, instances: List[dict]):
        self.instances = {
            i["name"]: HarnessInstance(
                name=i["name"],
                args=i.get("args", []),
                state_dir=i.get("state_dir", f"data/{i['name']}"),
            )
            for i in instances
        }
        self._shutdown = False

    def start_all(self) -> bool:
        ok = True
        for name, inst in self.instances.items():
            os.makedirs(inst.state_dir, exist_ok=True)
            if not inst.start():
                ok = False
        return ok

    def stop_all(self) -> None:
        for inst in self.instances.values():
            inst.stop()

    def aggregate(self) -> dict:
        """Read all instances and compute an aggregate portfolio view."""
        total_value = 0
        total_cash = 0
        total_positions = 0
        total_cycles = 0
        breakdown = []

        for name, inst in self.instances.items():
            inst.check_alive()
            state = inst.read_state()
            total_value += inst.portfolio_value
            total_cash += inst.cash
            total_positions += inst.positions
            total_cycles += inst.cycles
            breakdown.append({
                "name": name,
                "running": inst.running,
                "cycles": inst.cycles,
                "value": inst.portfolio_value,
                "cash": inst.cash,
                "positions": inst.positions,
                "return_pct": round(inst.return_pct, 2),
            })

        # Compute aggregate metrics
        init_total = sum(
            state.get("initial_cash", 100000)
            for state in [inst.read_state() for inst in self.instances.values()]
        )
        agg_return = ((total_value - init_total) / max(init_total, 1) * 100)

        return {
            "total_value": round(total_value, 2),
            "total_cash": round(total_cash, 2),
            "total_positions": total_positions,
            "total_cycles": total_cycles,
            "total_return_pct": round(agg_return, 2),
            "instances": breakdown,
            "timestamp": time.time(),
        }

    def run_loop(self, poll_interval: float = 30.0):
        """Main loop: poll instances and print aggregate status."""
        logger.info(f"Coordinator: {len(self.instances)} instances, polling every {poll_interval:.0f}s")
        while not self._shutdown:
            agg = self.aggregate()
            active = sum(1 for i in agg["instances"] if i["running"])
            logger.info(
                f"Aggregate: ${agg['total_value']:,.2f} "
                f"({agg['total_return_pct']:+.2f}%) | "
                f"{agg['total_positions']} pos | "
                f"{active}/{len(self.instances)} running"
            )
            for inst in agg["instances"]:
                logger.info(
                    f"  [{inst['name']:>12s}] {'RUN' if inst['running'] else 'STOP'} "
                    f"c{inst['cycles']:>4d} ${inst['value']:>10,.2f} "
                    f"({inst['return_pct']:+.2f}%) {inst['positions']} pos"
                )
            #
            # Aggregate state file
            #
            agg_path = Path("data/aggregate_state.json")
            agg_path.write_text(json.dumps(agg, indent=2))

            time.sleep(poll_interval)

        self.stop_all()
        logger.info("Coordinator stopped")


def main():
    parser = argparse.ArgumentParser(description="OpenTrader Multi-Asset Coordinator")
    parser.add_argument("--config", help="YAML config file")
    parser.add_argument("--instance", action="append", default=[],
                        help="Instance spec: name:--arg1,--arg2:state_dir")
    parser.add_argument("--poll", type=float, default=30.0, help="Poll interval (seconds)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    instances = []
    for spec in args.instance:
        parts = spec.split(":")
        name = parts[0]
        cli_args = parts[1].split(",") if len(parts) > 1 else []
        state_dir = parts[2] if len(parts) > 2 else f"data/{name}"
        instances.append({"name": name, "args": cli_args, "state_dir": state_dir})

    if args.config:
        import yaml
        with open(args.config) as f:
            cfg = yaml.safe_load(f)
        for name, spec in cfg.get("instances", {}).items():
            instances.append({
                "name": name,
                "args": spec.get("args", "").split(),
                "state_dir": spec.get("state_dir", f"data/{name}"),
            })

    if not instances:
        logger.error("No instances configured. Use --instance or --config.")
        sys.exit(1)

    coordinator = MultiAssetCoordinator(instances)

    def _shutdown(*_):
        coordinator._shutdown = True
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if coordinator.start_all():
        coordinator.run_loop(poll_interval=args.poll)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
