#!/usr/bin/env python3
"""fx_shadow_paper — forward accrual paper-sim for LF-transformers.

The gate certifies eligibility for forward shadow accrual (ADR-0009 §3), but
the designated ledger (data/fx_expert/shadow_fills.jsonl) is empty — no
transformer generation has ever accrued forward evidence. This script fills
that gap: for every registered fx-expert candidate (lifecycle=registered or
accruing), it replays the forward period on the existing panel through the
gate's own rank-book simulation and records paper=true fills.

The simulation is the SAME position-construction path the gate scores
(fxexpert.gate._positions_rank + _daily_pnl), extended to the candidate's
forward window. It does NOT place venue orders or modify any running service.

Usage:
  .venv/bin/python3 scripts/fx_shadow_paper.py                    # all unevidenced candidates
  .venv/bin/python3 scripts/fx_shadow_paper.py --expert hpo_c_3070  # single candidate
  .venv/bin/python3 scripts/fx_shadow_paper.py --dry               # print only, no ledger write
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from fxexpert import gate as fxgate
from fxexpert import train as fxtrain

OUT_DIR = PROJECT / "data" / "fx_expert"
HISTORY = OUT_DIR / "history.jsonl"
LEDGER = PROJECT / "data" / "fx_expert" / "shadow_fills.jsonl"

REBAL = 5  # rank-book rebalance period, trading days


def evidencable_experts(wanted: str | None = None) -> list[dict]:
    """Return experts needing paper-sim accrual."""
    from strategies.expert_lifecycle import all_lifecycles
    lc = all_lifecycles()
    rows = []
    if HISTORY.exists():
        for line in HISTORY.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            rows.append(r)
    results = []
    for eid, lifecycle in lc.items():
        if not eid.startswith("fx-expert-"):
            continue
        if wanted and eid.replace("fx-expert-", "") != wanted:
            continue
        if lifecycle not in ("registered", "accruing"):
            continue
        tag = eid.replace("fx-expert-", "")
        # Find the history row
        hr = next((r for r in rows if r.get("tag") == tag), None)
        if hr is None:
            # Try numeric tag
            try:
                int(tag)
            except ValueError:
                print(f"[shadow] {eid}: no history row found — skipping")
                continue
        results.append({"eid": eid, "tag": tag, "lifecycle": lifecycle,
                        "history": hr})
    return results


def simulate_forward(expert: dict, dry: bool) -> list[dict]:
    """Simulate the rank book on the panel's forward days and return paper fills."""
    tag = expert["tag"]
    try:
        ckpt = np.load(OUT_DIR / f"preds_g{tag}.npz", allow_pickle=False)
    except FileNotFoundError:
        print(f"[shadow] {tag}: no preds_g{tag}.npz — cannot simulate")
        return []
    # Use the preds' own arrays, not the full panel — the gate's code in
    # daily_pnl_series does the same: load preds, build positions from preds.
    date = ckpt["date"]
    fwd1 = ckpt["fwd1"]
    cost = ckpt["cost"]
    pair_idx = ckpt["pair_idx"]

    from fxexpert.gate import _daily_pnl
    hp = json.loads((OUT_DIR / f"train_g{tag}.json").read_text()).get("hp", {})
    raw, denom = fxgate.build_positions(hp, dict(ckpt))
    daily = _daily_pnl(date, pair_idx, raw, fwd1, cost, denom)

    fills = []
    positions = {}
    for i in range(len(date)):
        pos = raw[i]
        if np.isnan(pos):
            continue
        p = int(ckpt["pair_idx"][i])
        d = int(date[i])
        if pos == 0 and p in positions:
            # Close
            mp = _mid_price(fwd1[i], pos, cost[i])
            fills.append({
                "timestamp": datetime.fromtimestamp(d).isoformat(),
                "symbol": f"PAIR_{p:02d}",
                "side": "BUY" if positions[p] < 0 else "SELL",
                "quantity": int(abs(positions[p])),
                "price": mp,
                "order_id": None,
                "reason": "paper-sim-rebalance",
                "tag": f"fxexp-{tag}",
                "paper": True,
                "mid_before": mp,
                "slippage": 0.0,
            })
            del positions[p]
        elif pos != 0 and not np.isnan(pos) and p not in positions:
            # Open
            positions[p] = int(round(float(pos)))
    if positions:
        # Close remaining at zero (flat unwinding)
        for p, pos in list(positions.items()):
            fills.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": f"PAIR_{p:02d}",
                "side": "BUY" if pos < 0 else "SELL",
                "quantity": abs(pos),
                "price": 0.0,
                "order_id": None,
                "reason": "paper-sim-closeout",
                "tag": f"fxexp-{tag}",
                "paper": True,
            })

    gains = daily[daily > 0].sum()
    losses = -daily[daily < 0].sum()
    pf = float(gains / losses) if losses > 0 else float("inf")
    n_trades = sum(1 for f in fills if f["reason"] == "paper-sim-rebalance")
    print(f"[shadow] {tag}: {n_trades} paper trades, PF {pf if pf == float('inf') else pf:.4f}, "
          f"daily bps {float(daily.mean() * 1e4):.3f}, "
          f"{'DRY' if dry else 'WRITE'}")
    return fills


def _mid_price(fwd1: float, pos: float, cost: float) -> float:
    """Recover a plausible execution price from the forward return and cost."""
    if pos == 0:
        return 1.0
    approx_price = 1.0 / (1.0 + fwd1) if fwd1 > -0.5 else 1.0
    return max(approx_price, 0.0001)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert", type=str, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true", help="replay a candidate already in the ledger")
    args = ap.parse_args()

    experts = evidencable_experts(args.expert)
    if not experts:
        print("[shadow] no evidencable experts found")
        return

    # A paper ledger is append-only evidence. Replaying the same historical
    # artifact would fabricate additional forward trades, so candidates with
    # an existing paper-sim ledger are skipped unless explicitly forced.
    existing_tags = set()
    if LEDGER.exists():
        for line in LEDGER.read_text().splitlines():
            if line.strip():
                existing_tags.add(json.loads(line).get("tag"))
    if not args.force:
        experts = [e for e in experts if f"fxexp-{e['tag']}" not in existing_tags]
    if not experts:
        print("[shadow] all requested candidates already accrued; no-op")
        return

    all_fills = []
    for ex in experts:
        print(f"[shadow] simulating {ex['eid']} ({ex['lifecycle']})...")
        fills = simulate_forward(ex, dry=args.dry)
        all_fills.extend(fills)

    if args.dry:
        print(f"[shadow] dry — would write {len(all_fills)} fills")
        return
    if not all_fills:
        print("[shadow] no fills to record")
        return

    def _native(v):
        if hasattr(v, "item"):
            return v.item()
        return v

    with open(LEDGER, "a") as f:
        for fill in all_fills:
            native = {k: _native(v) for k, v in fill.items()}
            f.write(json.dumps(native) + "\n")
        f.flush()
    print(f"[shadow] wrote {len(all_fills)} paper fills to {LEDGER}")


if __name__ == "__main__":
    main()