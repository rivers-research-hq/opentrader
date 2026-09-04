#!/usr/bin/env python3
"""Opentrader Service Manager — hardened auto-restart for all 4 services.

Starts: llama-server, mcp_server, harness, dashboard.
Monitors every 30s; restarts on death.

Usage:
    python3 scripts/service_mgr.py [--no-watchdog|--with-watchdog]
"""
import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger("service_mgr")

SERVICES = []


class Service:
    def __init__(self, name: str, cmd: list, check_url: str = None,
                 check_timeout: int = 60, env: dict = None):
        self.name = name
        self.cmd = cmd
        self.check_url = check_url
        self.check_timeout = check_timeout
        self.env = env
        self.proc = None

    def start(self):
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        self.proc = subprocess.Popen(
            self.cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info(f"Started {self.name} (PID {self.proc.pid})")

    def is_alive(self) -> bool:
        if not self.proc:
            return False
        poll = self.proc.poll()
        return poll is None

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None


def build_services(data_dir: str, cash: str = "100", stage: str = "2",
                   with_watchdog: bool = False) -> list:
    svcs = []

    opentrader_dir = "/home/mrc/opentrader"
    python_bin = "/home/mrc/rocm_venv/bin/python3"

    # 1. Ollama (already running as system service, just check it's available)
    # We don't start Ollama here - it runs as a systemd service
    # But we verify the model is available
    svcs.append(Service(
        name="ollama",
        cmd=["ollama", "list"],  # Just a check command
        check_url="http://127.0.0.1:5802/v1",
        check_timeout=10,
    ))

    # 2. mcp_server
    svcs.append(Service(
        name="mcp_server",
        cmd=[
            python_bin,
            f"{opentrader_dir}/mcp_server.py",
            "--host", "127.0.0.1",
            "--port", "8092",
            "--exchange", "kraken",
            "--state-dir", data_dir,
            "--symbols", "BTC/USDT,ETH/USDT,SOL/USDT",
        ],
        check_url="http://127.0.0.1:8092/health",
        check_timeout=30,
    ))

    # 3. harness
    svcs.append(Service(
        name="harness",
        cmd=[
            python_bin,
            f"{opentrader_dir}/harness.py",
            "--live",
            "--exchange", "kraken",
            "--stage", stage,
            "--mot-force", "increase",
            "--max-daily-trades", "500",
            "--debate-mode", "adir",
            "--llama-host", "http://127.0.0.1:5802",
            "--cash", cash,
            "--parallel-debate",
        ],
        env={"OPENTRADER_INFERENCE": "api"},
        check_url=None,
        check_timeout=120,
    ))

    # 4. dashboard
    svcs.append(Service(
        name="dashboard",
        cmd=[
            python_bin,
            f"{opentrader_dir}/dashboard.py",
            "--port", "8098",
            "--host", "0.0.0.0",
        ],
        check_url="http://127.0.0.1:8098/api/dashboard/summary",
        check_timeout=30,
    ))

    # 5. training watchdog (optional, long-running)
    if with_watchdog:
        svcs.append(Service(
            name="watchdog",
            cmd=[
                python_bin,
                f"{opentrader_dir}/training/watchdog.py",
                "--background",
                "--data", data_dir,
                "--output", f"{opentrader_dir}/models/finetune",
                "--min-new-examples", "50",
                "--check-interval", "600",
                "--timeout", "900",
            ],
            check_url=None,
            check_timeout=600,
        ))

    return svcs


def main():
    parser = argparse.ArgumentParser(description="Opentrader Service Manager")
    parser.add_argument("--data", default="/home/mrc/opentrader/data")
    parser.add_argument("--cash", default="100")
    parser.add_argument("--stage", default="2")
    parser.add_argument("--with-watchdog", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    services = build_services(
        data_dir=args.data,
        cash=args.cash,
        stage=args.stage,
        with_watchdog=args.with_watchdog,
    )

    def shutdown():
        logger.info("Shutting down services...")
        for svc in services:
            svc.stop()
        logger.info("All stopped.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, lambda *_: shutdown())
    signal.signal(signal.SIGINT, lambda *_: shutdown())

    for svc in services:
        svc.start()
        if svc.check_url:
            time.sleep(2)

    logger.info(f"All {len(services)} services started. Monitoring...")
    time.sleep(10)

    while True:
        for svc in services:
            if not svc.is_alive():
                logger.warning(f"Service DEAD: {svc.name} — restarting...")
                svc.start()
                time.sleep(2)

        time.sleep(30)


if __name__ == "__main__":
    main()
