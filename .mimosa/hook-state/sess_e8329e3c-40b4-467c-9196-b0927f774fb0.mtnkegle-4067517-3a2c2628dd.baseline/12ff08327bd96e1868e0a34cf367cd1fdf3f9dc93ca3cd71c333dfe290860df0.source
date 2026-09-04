#!/usr/bin/env python3
"""RTX 3070 comprehensive benchmark suite."""

import time
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

DEVICE = "cuda"
DTYPE = torch.float32


def fmt(n):
    if n >= 1e12:
        return f"{n / 1e12:.2f} TFLOPS"
    if n >= 1e9:
        return f"{n / 1e9:.2f} GFLOPS"
    if n >= 1e6:
        return f"{n / 1e6:.2f} MFLOPS"
    return f"{n:.0f} FLOPS"


def bench_matmul():
    print("\n--- Matrix Multiply (FP32) ---")
    for N in [1024, 2048, 4096, 8192]:
        a = torch.randn(N, N, device=DEVICE, dtype=DTYPE)
        b = torch.randn(N, N, device=DEVICE, dtype=DTYPE)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(20):
            c = a @ b
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        flops = 2 * N**3 * 20 / elapsed
        print(f"  {N:5d}x{N:<5d}: {elapsed / 20 * 1000:8.2f}ms   {fmt(flops)}")


def bench_conv2d():
    print("\n--- Conv2D (FP32) ---")
    for C in [64, 128, 256]:
        x = torch.randn(16, C, 224, 224, device=DEVICE, dtype=DTYPE)
        conv = nn.Conv2d(C, C, 3, padding=1).to(DEVICE, dtype=DTYPE)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(50):
            y = conv(x)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        print(f"  {C:4d} channels 224x224: {elapsed / 50 * 1000:8.2f}ms/iter")


def bench_reduction():
    print("\n--- Reduction Ops (FP32) ---")
    sizes = [100_000, 1_000_000, 10_000_000, 100_000_000]
    for n in sizes:
        x = torch.randn(n, device=DEVICE, dtype=DTYPE)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(100):
            y = x.mean()
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        bw = (n * 4 * 100) / elapsed
        print(
            f"  {n:>12,} elem mean: {elapsed / 100 * 1e6:7.2f}us   {bw / 1e9:.1f} GB/s"
        )


def bench_attention():
    print("\n--- Scaled Dot-Product Attention (FP16) ---")
    for N in [512, 1024, 2048]:
        for d in [64, 128]:
            q = torch.randn(1, 8, N, d, device=DEVICE, dtype=torch.float16)
            k = torch.randn(1, 8, N, d, device=DEVICE, dtype=torch.float16)
            v = torch.randn(1, 8, N, d, device=DEVICE, dtype=torch.float16)
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            for _ in range(50):
                out = F.scaled_dot_product_attention(q, k, v)
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - t0
            print(f"  seq={N:5d} d={d:3d}: {elapsed / 50 * 1000:8.2f}ms")


def bench_memory():
    print("\n--- Memory Bandwidth ---")
    for size_mb in [64, 256, 1024, 2048]:
        n = size_mb * 1024 * 1024 // 4
        x = torch.randn(n, device=DEVICE, dtype=DTYPE)
        y = torch.empty_like(x)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(20):
            y.copy_(x)
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        bw = (size_mb * 20) / elapsed
        print(
            f"  {size_mb:5d} MB copy: {elapsed / 20 * 1000:7.2f}ms   {bw / 1024:.1f} GB/s"
        )


def bench_xgboost():
    print("\n--- XGBoost GPU ---")
    try:
        import xgboost as xgb

        rng = np.random.RandomState(42)
        n_samples, n_features = 100_000, 50
        X = rng.randn(n_samples, n_features).astype(np.float32)
        y = (X[:, 0] + X[:, 1] * 0.5 + rng.randn(n_samples) * 0.1 > 0).astype(
            np.float32
        )
        dtrain = xgb.DMatrix(X, label=y)
        params = {
            "device": "cuda",
            "tree_method": "hist",
            "max_depth": 8,
            "eta": 0.1,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
        }
        t0 = time.perf_counter()
        bst = xgb.train(params, dtrain, num_boost_round=100, verbose_eval=False)
        elapsed = time.perf_counter() - t0
        print(f"  100k samples, 50 features, 100 trees: {elapsed:.2f}s")
    except Exception as e:
        print(f"  Skipped: {e}")


def bench_jax():
    print("\n--- JAX GPU ---")
    try:
        import os

        os.environ.setdefault("XLA_PYTHON_CLIENT_PREALLOCATE", "false")
        os.environ.setdefault("XLA_PYTHON_CLIENT_MEM_FRACTION", ".50")
        import jax, jax.numpy as jnp

        key = jax.random.PRNGKey(0)
        for N in [1024, 2048]:
            a = jax.random.normal(key, (N, N), dtype=jnp.float32)
            b = jax.random.normal(key, (N, N), dtype=jnp.float32)
            t0 = time.perf_counter()
            for _ in range(50):
                c = jnp.dot(a, b)
            c.block_until_ready()
            elapsed = time.perf_counter() - t0
            flops = 2 * N**3 * 50 / elapsed
            print(f"  {N}x{N} matmul x50: {fmt(flops)}")
    except Exception as e:
        print(f"  Skipped: {e}")


def bench_cupy():
    print("\n--- CuPy GPU ---")
    try:
        import cupy as cp

        for N in [1024, 2048]:
            a = cp.random.randn(N, N, dtype=cp.float32)
            b = cp.random.randn(N, N, dtype=cp.float32)
            cp.cuda.Stream.null.synchronize()
            t0 = time.perf_counter()
            for _ in range(50):
                c = a @ b
            cp.cuda.Stream.null.synchronize()
            elapsed = time.perf_counter() - t0
            flops = 2 * N**3 * 50 / elapsed
            print(f"  {N}x{N} matmul x50: {fmt(flops)}")
            del a, b, c
            cp.get_default_memory_pool().free_all_blocks()
    except Exception as e:
        print(f"  Skipped: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print(f"RTX 3070 Benchmark Suite")
    print(f"Device: {torch.cuda.get_device_name(0)}")
    p = torch.cuda.get_device_properties(0)
    print(
        f"VRAM: {p.total_memory / 1024**3:.1f} GB | SMs: {p.multi_processor_count} | CC: {p.major}.{p.minor}"
    )
    print("=" * 60)

    bench_memory()
    bench_matmul()
    bench_conv2d()
    bench_reduction()
    bench_attention()
    bench_xgboost()
    bench_jax()
    bench_cupy()

    print("\n" + "=" * 60)
    print("Benchmark complete.")
