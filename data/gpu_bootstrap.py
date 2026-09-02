#!/usr/bin/env python3
"""GPU bootstrap for the falsify battery (wayfinder #92, user's hardware push).

The falsify battery's hot loop is 500 x rng.permutation in Python. Replace with
a BATCHED permutation op: generate all 500 permutation matrices at once
(torch.randint + argsort), gather, mean — one kernel on the GPU.

Benchmarks CPU vs GPU honestly (this workload is small; transfer latency may
dominate at n=1, but batching across the 6 tasks of a dataset + 19 datasets
gives the GPU real work).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

import torch  # noqa: E402


def _device():
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def bootstrap_cpu(pn, n_hi, n_boot, seed=7):
    """Baseline: the current serial numpy loop."""
    rng = np.random.RandomState(seed)
    n_all = len(pn)
    nulls = np.empty(n_boot)
    idx_all = np.arange(n_all)
    for b in range(n_boot):
        perm = rng.permutation(n_all)
        m2 = perm[:n_hi]
        nulls[b] = pn[m2].mean() - pn[np.setdiff1d(idx_all, m2)].mean()
    return nulls


def bootstrap_batched(pn, n_hi, n_boot, seed=7, device="cpu"):
    """All n_boot permutations in ONE batched op.

    Trick: argsort of a (n_boot, n_all) random matrix gives n_boot independent
    permutations in a single kernel — no loop."""
    n_all = len(pn)
    g = torch.Generator(device=device)
    g.manual_seed(seed)
    r = torch.rand((n_boot, n_all), device=device, generator=g)
    perm = torch.argsort(r, dim=1)  # (n_boot, n_all) permutations
    pn_t = torch.tensor(pn, dtype=torch.float32, device=device)
    # gather pn[perm]
    gathered = pn_t[perm]  # (n_boot, n_all)
    hi_mean = gathered[:, :n_hi].mean(dim=1)
    lo_mean = gathered[:, n_hi:].mean(dim=1)
    nulls = (hi_mean - lo_mean).cpu().numpy()
    return nulls


def main():
    np.random.seed(7)
    device = _device()
    print(f"device: {device} "
          f"({torch.cuda.get_device_name(0) if device=='cuda' else 'CPU'})")
    for n_days in [1500, 2000]:
        pn = np.random.randn(n_days) * 0.02
        n_hi = n_days // 3
        # warmup
        bootstrap_cpu(pn, n_hi, 50)
        bootstrap_batched(pn, n_hi, 50, device=device)
        # benchmark
        t0 = time.time(); bootstrap_cpu(pn, n_hi, 500); t_cpu = time.time() - t0
        t0 = time.time(); bootstrap_batched(pn, n_hi, 500, device=device)
        t_gpu = time.time() - t0
        print(f"n={n_days}: cpu={t_cpu*1000:.1f}ms  "
              f"{device}={t_gpu*1000:.1f}ms  speedup={t_cpu/t_gpu:.1f}x")
        # correctness
        a = bootstrap_cpu(pn, n_hi, 200)
        b = bootstrap_batched(pn, n_hi, 200, device=device)
        print(f"  max|diff| cpu-vs-batched: {np.abs(a-b).max():.2e} (0 = identical)")


if __name__ == "__main__":
    main()
