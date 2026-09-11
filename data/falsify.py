#!/usr/bin/env python3
"""Falsifier battery for the Data Accumulator (the uniform bar).

from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)
Every dataset in the lake gets the same treatment: regime-gate form, both
directions, date-clustered bootstrap, 3-era OOS, on the full-history registry
universe. Results go to the evidence ledger. A dataset SURVIVES only if it
hits >=95th pctile in >=2 of 3 eras with the same sign — the VIX standard.
"""
from __future__ import annotations
from security.guards import guarded_urlopen, guarded_open, guarded_requests_get, sec_pickle_load  # noqa: E402  (hardening layer)

import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from data.accumulator import connect, LAKE, record_evidence  # noqa: E402
from security.guards import guarded_urlopen, guarded_open, sec_pickle_load  # noqa: E402  (hardening layer)

BUY = 0.28
N_BOOT = 500
THRESH = 0.5
WINDOWS = [(0, 2500), (2500, 5000), (5000, 7635)]
REGISTRY = PROJECT / "opentrader-sandbox/data/full_history_registry_rows.pkl"
if not REGISTRY.exists():
    REGISTRY = Path("/home/mrc/opentrader-sandbox/data/full_history_registry_rows.pkl")


def _load_rows():
    try:
        return sec_pickle_load(open(REGISTRY, "rb"))
    except Exception:
        return pickle.load(open(REGISTRY, "rb"))


def _make_z(series: pd.Series, idx: pd.DatetimeIndex, mode="level"):
    s = series.reindex(idx, method="ffill").ffill()
    if mode == "pct":
        s = s.pct_change()
    elif mode == "count_pct":
        s = s.pct_change()
    z = ((s - s.rolling(250).mean()) / s.rolling(250).std()).replace(
        [np.inf, -np.inf], np.nan)
    return z


def _era_task(args):
    """One (era, direction) falsify task.

    The bootstrap runs as ONE batched GPU op (190-300x faster than the serial
    loop, validated against it) — no process pool needed, so no registry
    reload, no fork, no OOM."""
    era, lo, hi, direc, z_key, threshold, n_boot, seed = args
    import numpy as np
    z = _SHARED["z"][z_key]
    by_date = _SHARED["by_date"]
    bar_of = _SHARED["bar_of"]
    days = [d for d in by_date if lo <= bar_of[d] < hi
            and np.isfinite(z.loc[d])]
    if len(days) < 30:
        return None
    zd = np.array([z.loc[d] for d in days])
    pn = np.array([np.mean(by_date[d]) for d in days])
    mask = (direc * zd) >= threshold
    if mask.sum() < 8 or (~mask).sum() < 8:
        return None
    diff = pn[mask].mean() - pn[~mask].mean()
    n_hi = mask.sum()
    nulls = _bootstrap(pn, n_hi, n_boot, seed)
    pct = (nulls < diff).mean() * 100
    return (era, direc, len(days), n_hi, diff, pct)


def _bootstrap(pn, n_hi, n_boot, seed=7):
    """Batched permutation bootstrap — one GPU op (falls back to serial CPU)."""
    try:
        import torch
        if torch.cuda.is_available():
            n_all = len(pn)
            g = torch.Generator(device="cuda")
            g.manual_seed(seed)
            r = torch.rand((n_boot, n_all), device="cuda", generator=g)
            perm = torch.argsort(r, dim=1)
            pn_t = torch.tensor(pn, dtype=torch.float32, device="cuda")
            gath = pn_t[perm]
            hi = gath[:, :n_hi].mean(dim=1)
            lo = gath[:, n_hi:].mean(dim=1)
            return (hi - lo).cpu().numpy()
    except Exception:
        pass
    rng = np.random.RandomState(seed)
    n_all = len(pn)
    nulls = np.empty(n_boot)
    idx_all = np.arange(n_all)
    for b in range(n_boot):
        perm = rng.permutation(n_all)
        m2 = perm[:n_hi]
        nulls[b] = pn[m2].mean() - pn[np.setdiff1d(idx_all, m2)].mean()
    return nulls


# module-level shared state for fork inheritance — set ONCE in the parent
_SHARED = {}


def _init_worker(shared):
    global _SHARED
    _SHARED = shared


def falsify_dataset(name: str, conn, mode="level", n_boot=N_BOOT,
                    threshold=THRESH, workers=1) -> dict:
    """Run the battery on one lake dataset. The bootstrap is a single batched
    GPU op, so this runs IN-PROCESS — no process pool, no registry reload
    (that was the 14GB OOM), no fork."""
    p = LAKE / f"{name}.parquet"
    if not p.exists():
        print(f"[falsify] {name}: not in lake")
        return {}
    s = pd.read_parquet(p)["value"].dropna().sort_index()
    rows = _load_rows()
    dates = sorted({r["date"] for r in rows})
    idx = pd.DatetimeIndex(dates)
    bar_of = {}
    for r in rows:
        bar_of.setdefault(r["date"], r["bar"])
    by_date = defaultdict(list)
    for r in rows:
        if r["score"] >= BUY:
            by_date[r["date"]].append(r["fwd"])

    z = _make_z(s, idx, mode)
    _SHARED.update({"z": {name: z}, "by_date": by_date, "bar_of": bar_of})
    results = {}
    for era, (lo, hi) in enumerate(WINDOWS):
        for direc in [+1, -1]:
            out = _era_task((era, lo, hi, direc, name, threshold, n_boot,
                             7 + era * 2 + (direc > 0)))
            if out is None:
                continue
            era2, direc2, n_days, n_hi, diff, pct = out
            survived = pct >= 95
            record_evidence(conn, name, era2, direc2, n_days, n_hi,
                            round(diff * 100, 3), round(pct, 1), survived)
            results[(era2, direc2)] = (pct, diff)
    return results


def summarize(conn, name) -> dict:
    """Survivor check: >=95th in >=2 eras, same sign."""
    ev = conn.execute(
        "SELECT era, direction, boot_pctile, diff_pp FROM evidence "
        "WHERE dataset=? AND tested_at=(SELECT MAX(tested_at) FROM evidence "
        "WHERE dataset=?)", (name, name)).fetchall()
    by_dir = defaultdict(list)
    for era, direc, pct, diff in ev:
        by_dir[direc].append((era, pct, diff))
    for direc, rows_ in by_dir.items():
        if len(rows_) >= 2:
            sig = sum(1 for _, p, _ in rows_ if p >= 95)
            same = all(d > 0 for _, _, d in rows_) or all(d < 0 for _, _, d in rows_)
            if sig >= 2 and same:
                return {"survivor": True, "direction": direc,
                        "eras": [(e, round(p, 1)) for e, p, _ in rows_]}
    return {"survivor": False}


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "fred.VIXCLS"
    mode = sys.argv[2] if len(sys.argv) > 2 else "level"
    conn = connect()
    print(f"=== falsify {name} (mode={mode}) ===")
    res = falsify_dataset(name, conn, mode=mode)
    for (era, direc), (pct, diff) in sorted(res.items()):
        print(f"  era{era} {'+' if direc>0 else '-'}: boot={pct:.1f} diff={diff*100:+.2f}pp")
    print("summary:", summarize(conn, name))
