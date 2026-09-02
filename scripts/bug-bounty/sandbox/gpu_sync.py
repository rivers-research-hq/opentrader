#!/usr/bin/env python3
"""
GPU Sync — CPU-based multi-GPU orchestrator and request router.

Sits in front of all GPU llama-server instances. Health-checks them,
load-balances requests, and fails over when a GPU goes down. Runs on CPU
so it stays alive even when both GPUs are borked.

Usage:
    python3 gpu_sync.py --port 5801
    python3 gpu_sync.py --backends 5802,5803 --port 5801
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
from aiohttp import web

logger = logging.getLogger("opentrader.gpu_sync")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ── Backend stats ──────────────────────────────────────────────────


@dataclass
class BackendStats:
    url: str
    name: str = ""
    model: str = "unknown"
    healthy: bool = False
    last_health: float = 0.0
    consecutive_failures: int = 0
    total_requests: int = 0
    total_failures: int = 0
    total_success: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""


class BackendPool:
    """Thread-safe pool of GPU backends with health tracking and model-aware routing."""

    def __init__(self, backends: list[str], health_interval: float = 10.0):
        self._lock = asyncio.Lock()
        self._health_interval = health_interval
        self._backends: list[BackendStats] = []
        self._model_to_backend: dict[str, BackendStats] = {}
        self._rr_index = 0

        for i, url in enumerate(backends):
            name = f"gpu{i}"
            bs = BackendStats(url=url.rstrip("/"), name=name)
            self._backends.append(bs)

        logger.info(
            f"Backend pool initialized: {len(self._backends)} GPU(s) — "
            + ", ".join(b.url for b in self._backends)
        )

    async def discover_models(self) -> None:
        """Query /v1/models on each backend to get model name and build model→backend map."""
        async with aiohttp.ClientSession() as session:
            for bs in self._backends:
                try:
                    async with session.get(
                        f"{bs.url}/v1/models", timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            models = data.get("data", data.get("models", []))
                            if models:
                                bs.model = models[0].get("id", "unknown")
                                self._model_to_backend[bs.model] = bs
                                logger.info(f"{bs.name} ({bs.url}): model={bs.model}")
                except Exception as e:
                    logger.warning(
                        f"{bs.name} ({bs.url}): model discovery failed — {e}"
                    )

    async def health_check_all(self) -> None:
        """Ping /health on all backends and update status."""
        async with aiohttp.ClientSession() as session:
            tasks = [self._check_one(session, bs) for bs in self._backends]
            await asyncio.gather(*tasks, return_exceptions=True)

        healthy = [b for b in self._backends if b.healthy]
        unhealthy = [b for b in self._backends if not b.healthy]

        if unhealthy:
            logger.warning(
                f"Unhealthy GPU(s): "
                + ", ".join(f"{b.name}({b.url}):{b.last_error}" for b in unhealthy)
            )

    async def _check_one(
        self, session: aiohttp.ClientSession, bs: BackendStats
    ) -> None:
        was_healthy = bs.healthy
        try:
            t0 = time.monotonic()
            async with session.get(
                f"{bs.url}/health", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                lat = (time.monotonic() - t0) * 1000
                if resp.status == 200:
                    bs.healthy = True
                    bs.consecutive_failures = 0
                    bs.last_health = time.time()
                    bs.last_error = ""
                else:
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history, status=resp.status
                    )
        except Exception as e:
            bs.consecutive_failures += 1
            bs.last_error = str(e)[:120]
            bs.last_health = time.time()
            if bs.consecutive_failures >= 3:
                bs.healthy = False

        if was_healthy != bs.healthy:
            state = "HEALTHY" if bs.healthy else "UNHEALTHY"
            if bs.healthy:
                logger.info(f"GPU state change: {bs.name} ({bs.url}) → {state}")
            else:
                # Exclusion alert: after 3 consecutive failures this backend
                # stops receiving routed requests until it recovers.
                logger.warning(
                    f"GPU state change: {bs.name} ({bs.url}) → {state} "
                    f"(after {bs.consecutive_failures} failures) — EXCLUDED "
                    f"from routing until health recovers. ACTION REQUIRED if "
                    f"this persists: check llama-server process on that port."
                )

    async def _get_fallback(
        self, skip: Optional[BackendStats] = None
    ) -> Optional[BackendStats]:
        """Get any healthy backend, optionally skipping one (for retry)."""
        for b in self._backends:
            if b.healthy and b is not skip:
                return b
        return None

    async def route_request(
        self, session: aiohttp.ClientSession, path: str, payload: dict
    ) -> tuple[Optional[dict], int, Optional[str], float]:
        """Route a request to a healthy backend. Returns (response_json, status, error, latency_ms).

        Strategy:
        1. If payload has a 'model' field matching a discovered backend, route to it.
        2. Fall back to round-robin across healthy backends.
        3. If the primary fails, retry on next healthy backend.
        """
        requested_model = (payload or {}).get("model", "")

        # Model-aware routing: if we know which backend hosts this model, use it.
        if requested_model and requested_model in self._model_to_backend:
            target = self._model_to_backend[requested_model]
            if target.healthy:
                result, status, error, latency = await self._send_to(
                    target, session, path, payload
                )
                if result is not None and status != 503:
                    return result, status, error, latency
                logger.warning(
                    f"Model-aware route to {target.name} ({target.url}) failed, "
                    f"trying fallback: {error}"
                )
            else:
                logger.warning(
                    f"Model {requested_model} backend {target.name} ({target.url}) "
                    f"is unhealthy, falling back to round-robin"
                )

        # Round-robin fallback
        async with self._lock:
            healthy = [b for b in self._backends if b.healthy]
            if not healthy:
                return None, 503, "No healthy GPU backends available", 0.0

            self._rr_index = (self._rr_index + 1) % len(healthy)
            start = self._rr_index

        tried = set()
        for attempt in range(len(healthy)):
            idx = (start + attempt) % len(healthy)
            bs = healthy[idx]
            if bs.url in tried:
                continue
            tried.add(bs.url)

            result, status, error, latency = await self._send_to(
                bs, session, path, payload
            )
            if status != 503 and result is not None:
                return result, status, error, latency

            logger.warning(f"{bs.name} ({bs.url}) failed request, trying next backend")

        return None, 503, "All GPU backends failed", 0.0

    async def _send_to(
        self, bs: BackendStats, session: aiohttp.ClientSession, path: str, payload: dict
    ) -> tuple[Optional[dict], int, Optional[str], float]:
        t0 = time.monotonic()
        url = f"{bs.url}{path}"
        bs.total_requests += 1

        try:
            async with session.post(
                url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                latency = (time.monotonic() - t0) * 1000
                if resp.status == 200:
                    data = await resp.json()
                    bs.total_success += 1
                    n = bs.total_success
                    bs.avg_latency_ms = bs.avg_latency_ms * (n - 1) / n + latency / n
                    return data, 200, None, latency
                else:
                    body = await resp.text()
                    bs.total_failures += 1
                    return None, 502, f"Backend {resp.status}: {body[:200]}", latency
        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            bs.total_failures += 1
            return None, 503, "Backend timeout", latency
        except Exception as e:
            latency = (time.monotonic() - t0) * 1000
            bs.total_failures += 1
            return None, 503, str(e)[:200], latency

    async def any_healthy(self) -> bool:
        return any(b.healthy for b in self._backends)

    async def status(self) -> dict:
        return {
            "backends": [
                {
                    "name": b.name,
                    "url": b.url,
                    "model": b.model,
                    "healthy": b.healthy,
                    "consecutive_failures": b.consecutive_failures,
                    "total_requests": b.total_requests,
                    "total_success": b.total_success,
                    "total_failures": b.total_failures,
                    "avg_latency_ms": round(b.avg_latency_ms, 1),
                    "last_error": b.last_error,
                    "last_health": datetime.fromtimestamp(
                        b.last_health, tz=timezone.utc
                    ).isoformat()
                    if b.last_health
                    else None,
                }
                for b in self._backends
            ],
            "any_healthy": await self.any_healthy(),
        }

    async def models_list(self) -> list[dict]:
        """Aggregate models from healthy backends."""
        models = []
        seen = set()
        for b in self._backends:
            if b.healthy and b.model and b.model not in seen:
                seen.add(b.model)
                models.append(
                    {
                        "id": b.model,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": f"gpu_sync ({b.name})",
                    }
                )
        return models


# ── Health check background task ───────────────────────────────────


async def health_check_loop(pool: BackendPool, interval: float):
    """Periodically health-check all GPU backends. Rediscover models until
    every backend is identified (GPUs may still be loading at startup)."""
    logger.info(f"Health check loop started (interval={interval}s)")
    while True:
        await asyncio.sleep(interval)
        try:
            await pool.health_check_all()
            # Model discovery only runs once at startup; if a GPU was still
            # loading then, re-run discovery until every backend is known.
            if any(b.model == "unknown" for b in pool._backends):
                await pool.discover_models()
        except Exception as e:
            logger.error(f"Health check loop error: {e}")


# ── aiohttp App ────────────────────────────────────────────────────


class GPUSyncApp:
    def __init__(self, pool: BackendPool):
        self.pool = pool
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/v1/models", self.list_models)
        self.app.router.add_post("/v1/chat/completions", self.handle_chat)
        self.app.router.add_post("/v1/completions", self.handle_chat)
        self.app.router.add_get("/status", self.handle_status)

    async def handle_health(self, request: web.Request) -> web.Response:
        healthy = await self.pool.any_healthy()
        return web.json_response(
            {
                "status": "ok" if healthy else "degraded",
                "backends": len(self.pool._backends),
            },
            status=200 if healthy else 503,
        )

    async def list_models(self, request: web.Request) -> web.Response:
        models = await self.pool.models_list()
        return web.json_response({"object": "list", "data": models})

    async def handle_status(self, request: web.Request) -> web.Response:
        return web.json_response(await self.pool.status())

    async def handle_chat(self, request: web.Request) -> web.Response:
        payload = await request.json()

        async with aiohttp.ClientSession() as session:
            data, status, error, latency = await self.pool.route_request(
                session, "/v1/chat/completions", payload
            )

        if data is not None:
            return web.json_response(data, status=status)
        else:
            return web.json_response(
                {
                    "error": {
                        "message": error or "No healthy GPU available",
                        "type": "gpu_sync_error",
                    }
                },
                status=503,
            )


# ── CLI ────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser(description="GPU Sync — multi-GPU orchestrator")
    p.add_argument("--port", type=int, default=5801, help="Listen port (default: 5801)")
    p.add_argument(
        "--backends",
        default="5802",
        help="Comma-separated ports or full URLs for GPU backends (default: 5802 — "
        "5803/qwen2.5-7b is retired; the live unit pins this explicitly)",
    )
    p.add_argument(
        "--health-interval",
        type=float,
        default=10.0,
        help="Health check interval in seconds (default: 10)",
    )
    p.add_argument(
        "--host", default="127.0.0.1", help="Listen host (default: 127.0.0.1)"
    )
    return p.parse_args()


def resolve_backends(raw: str) -> list[str]:
    """Parse --backends argument into full URLs."""
    urls = []
    for part in raw.split(","):
        part = part.strip()
        if part.startswith("http://") or part.startswith("https://"):
            urls.append(part)
        else:
            urls.append(f"http://127.0.0.1:{part}")
    return urls


async def main():
    args = parse_args()
    backends = resolve_backends(args.backends)

    pool = BackendPool(backends, health_interval=args.health_interval)
    await pool.discover_models()
    await pool.health_check_all()

    sync_app = GPUSyncApp(pool)
    app = sync_app.app

    # Start health check loop as background task
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    health_task = asyncio.create_task(health_check_loop(pool, args.health_interval))

    logger.info(f"GPU Sync listening on http://{args.host}:{args.port}")
    logger.info(f"Backends: {', '.join(b.url for b in pool._backends)}")

    # Keep running until signal
    stop_event = asyncio.Event()

    def _shutdown(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s, None))
        except NotImplementedError:
            signal.signal(sig, _shutdown)

    await stop_event.wait()

    logger.info("Shutting down GPU Sync...")
    health_task.cancel()
    try:
        await health_task
    except asyncio.CancelledError:
        pass
    await runner.cleanup()
    logger.info("GPU Sync stopped.")


if __name__ == "__main__":
    asyncio.run(main())
