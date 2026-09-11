#!/usr/bin/env python3
"""GPU-RESIDENT exogenous falsify — cappuccino pattern.

Loads ALL data onto GPU VRAM as BF16 tensors ONCE (cappuccino's
environment_Alpaca_gpu.py pattern), computes all z-scores + bootstraps
on-device, zero CPU round-trips. Batches ALL datasets × eras × directions
into one giant tensor op so the GPU has real work.

VRAM budget (BF16): registry features 2.7M×11×2B=59MB + 19 series×7525×2B=286KB
+ bootstrap batch 19×6×500×5325×2B=608MB => <1GB of 24GB available.
"""
from __future__ import annotations
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from data.accumulator import connect, LAKE, record_evidence  # noqa: E402

BUY = 0.28
N_BOOT = 2000  # doubled — GPU can handle it
THRESH = 0.5
WINDOWS = [(0, 2500), (2500, 5000), (5000, 7635)]
REGISTRY = Path("/home/mrc/opentrader-sandbox/data/full_history_registry_rows.pkl")
DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def main():
    datasets = sys.argv[1:]
    if not datasets:
        # all lake datasets
        datasets = sorted(p.stem for p in LAKE.glob("*.parquet"))
    print(f"device: {DEVICE} ({torch.cuda.get_device_name(DEVICE)})", flush=True)
    print(f"datasets: {len(datasets)}", flush=True)

    t_start = time.time()

    # ── 1. Load registry ONCE, push ALL to GPU VRAM as BF16 ────────────
    print("[1/4] loading registry to VRAM...", flush=True)
    dates = sorted({r["date"] for r in rows})
    d2i = {d: i for i, d in enumerate(dates)}
    n_dates = len(dates)

    from collections import defaultdict
    by_date = defaultdict(list)
    bar_of_date = {}
    for r in rows:
        bar_of_date.setdefault(r["date"], r["bar"])
        if r["score"] >= BUY:
            by_date[d2i[r["date"]]].append(r["fwd"])

    tail_days = sorted(by_date)  # date INDICES (0..7524) into z/pn grids
    n_tail = len(tail_days)
    # bar VALUES (110..7634) for era-window masking ONLY — never for tensor indexing
    tail_bars = torch.tensor([bar_of_date[dates[d]] for d in tail_days],
                             dtype=torch.long, device=DEVICE)
    # date INDICES for tensor indexing into z (length n_dates)
    tail_idx = torch.tensor(tail_days, dtype=torch.long, device=DEVICE)
    tail_pn = torch.tensor([float(np.mean(by_date[d])) for d in tail_days],
                           dtype=torch.float32, device=DEVICE)
    tail_ord = torch.arange(n_tail, device=DEVICE)
    del rows  # free RAM — data is on GPU now
    print(f"   {n_tail:,} tail-days on GPU, VRAM: "
          f"{torch.cuda.memory_allocated()/1e9:.2f}GB", flush=True)

    # ── 2. Load ALL exogenous series to GPU ────────────────────────────
    print("[2/4] loading exogenous series to VRAM...", flush=True)
    series_z = {}  # name -> GPU z-score tensor (full date grid)
    for name in datasets:
        p = LAKE / f"{name}.parquet"
        if not p.exists():
            print(f"   {name}: skip (not in lake)", flush=True)
            continue
        ser = pd.read_parquet(p)["value"].dropna().sort_index()
        vals = ser.reindex(pd.DatetimeIndex(dates), method="ffill").ffill()
        t = torch.tensor(vals.to_numpy(dtype=np.float32), device=DEVICE)
        # causal rolling z via conv (all on GPU)
        t2 = t.reshape(1, 1, -1)
        win = 250
        kernel = torch.ones(1, 1, win, device=DEVICE) / win
        mean = torch.nn.functional.conv1d(t2, kernel, padding=win - 1)[0, 0, :n_dates]
        sq = (t - mean) ** 2
        var = torch.nn.functional.conv1d(sq.reshape(1, 1, -1), kernel,
                                         padding=win - 1)[0, 0, :n_dates]
        z = (t - mean) / torch.sqrt(var.clamp_min(1e-12))
        z[:win - 1] = 0.0  # sentinel (not NaN — GPU-safe)
        series_z[name] = z
    print(f"   {len(series_z)} series on GPU, VRAM: "
          f"{torch.cuda.memory_allocated()/1e9:.2f}GB", flush=True)

    # ── 3. Batch ALL era×direction tests per dataset on GPU ─────────────
    print(f"[3/4] running {len(series_z)} datasets × 3 eras × 2 dirs "
          f"× {N_BOOT} bootstraps on GPU...", flush=True)
    conn = connect()
    for name, z in series_z.items():
        z_tail = z[tail_idx]  # z at each tail-day's DATE INDEX (GPU gather)
        results = {}
        for era, (lo, hi) in enumerate(WINDOWS):
            mask = (tail_bars >= lo) & (tail_bars < hi) & (z_tail != 0)
            ord_e = tail_ord[mask]
            if len(ord_e) < 30:
                continue
            zd = z_tail[mask]
            pn_e = tail_pn[ord_e]
            n_e = len(ord_e)
            for direc in [+1, -1]:
                gate = (direc * zd) >= THRESH
                n_hi = int(gate.sum())
                if n_hi < 8 or (n_e - n_hi) < 8:
                    continue
                diff = pn_e[gate].mean() - pn_e[~gate].mean()
                # batched bootstrap — ALL N_BOOT permutations in one GPU op
                g = torch.Generator(device=DEVICE.type)
                g.manual_seed(7 + era * 2 + (direc > 0))
                r = torch.rand((N_BOOT, n_e), device=DEVICE, generator=g)
                perm = torch.argsort(r, dim=1)
                gath = pn_e[perm]
                nulls = gath[:, :n_hi].mean(dim=1) - gath[:, n_hi:].mean(dim=1)
                pct = float((nulls < diff).float().mean() * 100)
                survived = pct >= 95
                record_evidence(conn, name, era, direc, n_e, n_hi,
                                round(float(diff) * 100, 3), round(pct, 1),
                                survived)
                results[(era, direc)] = (pct, float(diff))
        best = max((p for p, d in results.values()), default=0)
        sig = sum(1 for p, d in results.values() if p >= 95)
        print(f"   {name:20s} best={best:5.0f}  sig_eras={sig}  "
              f"VRAM={torch.cuda.memory_allocated()/1e9:.2f}GB", flush=True)

    # ── 4. Survivors check ─────────────────────────────────────────────
    print(f"[4/4] elapsed {time.time()-t_start:.1f}s", flush=True)
    from data.falsify import summarize
    survivors = []
    for name in series_z:
        s = summarize(conn, name)
        if s["survivor"]:
            survivors.append(name)
            print(f"   *** SURVIVOR: {name} {s}", flush=True)
    print(f"\nsurvivors: {survivors or 'none'}", flush=True)
    print(f"peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f}GB "
          f"of {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB",
          flush=True)


if __name__ == "__main__":
    main()
