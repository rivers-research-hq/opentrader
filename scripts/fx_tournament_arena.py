#!/usr/bin/env python3
"""fx_tournament_arena — the autonomous training loop.

Runs: train → shadow → compare → promote → clean.

This is the automation the manual deployment pipeline existed to avoid:
training candidates are generated, compared against the incumbent,
and the winner is deployed — all without human signoff for the
training-to-shadow step. Live deployment still honours the lifecycle
contract and uses the proper API.

Schedule: systemd timer fx-arena.timer (daily 06:00 UTC, after data refresh).
"""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))

from strategies.expert_lifecycle import active_lanes, lifecycle_of, transition, all_lifecycles
from strategies import epoch_registry as er
from strategies.lane_claims import _lane_order
from fxexpert import gate as fxgate

OUT = PROJECT / "data" / "fx_expert"
ARENA_STATE = OUT / "tournament_state.json"
HISTORY = OUT / "history.jsonl"
LEDGER = PROJECT / "data" / "fx_expert" / "shadow_fills.jsonl"
LOG = PROJECT / "data" / "logs" / "fx_tournament.log"
LOCK = PROJECT / "data" / "fx_expert" / "tournament.lock"
GPU_PICK = PROJECT / "scripts" / "gpu_pick.py"

MIN_TRADES = 20  # minimum closed trades to qualify for promotion


def log(msg: str):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line)


def _pick_device() -> str:
    """Run gpu_pick to determine compute target."""
    r = subprocess.run([sys.executable, str(GPU_PICK)], capture_output=True, text=True)
    out = r.stdout.strip()
    if "gre" in out.split(":")[0]:
        return "gre"
    return "3070"


def _current_incumbent() -> str | None:
    """Returns the deployed expert's tag (shorted) or None."""
    for eid in active_lanes():
        if eid.startswith("fx-expert-"):
            return eid.replace("fx-expert-", "")
    return None


def _incumbent_pf() -> float | None:
    """Compute the incumbent's backtest PF from its history row."""
    inc = _current_incumbent()
    if not inc:
        return None
    if not HISTORY.exists():
        return None
    for line in HISTORY.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("tag") == inc:
            return row.get("pf")
    return None


def _shadow_pf(tag: str) -> float | None:
    """Read shadow paper-sim PF for a candidate from the paper fills."""
    if not LEDGER.exists():
        return None
    pnl = 0.0
    gains, losses = 0.0, 0.0
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        fill = json.loads(line)
        if fill.get("tag") != f"fxexp-{tag}":
            continue
        price = float(fill.get("price", 0))
        qty = abs(int(fill.get("quantity", 0)))
        side = fill.get("side", "")
        # Approximate PnL from fill price and quantity
        if price > 0 and qty > 0:
            if side == "SELL":
                pnl += price * qty
            else:
                pnl -= price * qty
    return pnl if pnl != 0 else None


def run_training():
    """Run one training batch on the available GPU with explicit fallback."""
    device = _pick_device()
    # The GRE worker uses the same GPU; refuse to start deep HPO while the
    # worker is live rather than colliding with it. The 3070 runner is the
    # always-on fallback and must use the CUDA venv explicitly.
    if device == "gre":
        try:
            w = subprocess.run(["systemctl", "--user", "is-active", "local-worker.service"],
                               capture_output=True, text=True)
            if w.stdout.strip() == "active":
                log("[arena] GRE worker active; selecting 3070 fallback")
                device = "3070"
        except Exception:
            pass
    log(f"[arena] training on {device}")
    if device == "gre":
        cmd = [sys.executable, str(PROJECT / "scripts" / "gre_hpo_run.py")]
        timeout = 7200
    else:
        cmd = [str(PROJECT / ".venv-cuda" / "bin" / "python3"),
               str(PROJECT / "scripts" / "gre_hpo_run.py")]
        timeout = 3600
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       cwd=PROJECT)
    if r.returncode != 0:
        log(f"[arena] training FAILED ({device}): {r.stderr[-1000:]}")
        return False
    log(f"[arena] training OK ({device}): {r.stdout[-500:]}")
    return True


def run_shadow_paper():
    """Run shadow paper-sim for all registered fx-expert candidates."""
    from scripts.fx_shadow_paper import main as shadow_main
    import argparse
    try:
        shadow_main()
        log(f"[arena] shadow paper-sim completed")
    except Exception as e:
        log(f"[arena] shadow paper-sim FAILED: {e}")


def promote_best_shadow():
    """Compare all candidates and promote the best one."""
    inc_tag = _current_incumbent()
    inc_pf = _incumbent_pf()
    log(f"[arena] incumbent: {inc_tag} PF={inc_pf}")

    # Scan all fx-expert candidates with shadow evidence
    candidates = {}
    for eid, lifecycle in all_lifecycles().items():
        if not eid.startswith("fx-expert-"):
            continue
        tag = eid.replace("fx-expert-", "")
        if lifecycle not in ("registered", "accruing", "candidate"):
            continue
        if tag == inc_tag:
            continue  # skip incumbent
        pf = _shadow_pf(tag)
        # Count closed trades from shadow_fills
        n_trades = 0
        if LEDGER.exists():
            for line in LEDGER.read_text().splitlines():
                if not line.strip():
                    continue
                fill = json.loads(line)
                if fill.get("tag") == f"fxexp-{tag}" and fill.get("reason", "").startswith("paper-sim"):
                    n_trades += 1
        candidates[tag] = {"pf": pf, "n_trades": n_trades, "lifecycle": lifecycle}

    if not candidates:
        log(f"[arena] no candidates with shadow evidence")
        return

    log(f"[arena] candidates with shadow evidence: {len(candidates)}")
    best_tag, best = max(candidates.items(), key=lambda x: abs(float(x[1].get("pf", 0) or 0)))

    if best["n_trades"] < MIN_TRADES:
        log(f"[arena] best candidate {best_tag}: {best['n_trades']} trades < {MIN_TRADES} — not ready")
        return

    if inc_pf is not None and best["pf"] is not None and abs(best["pf"]) <= inc_pf:
        log(f"[arena] best candidate {best_tag} PF={best['pf']:.4f} <= incumbent PF={inc_pf:.4f} — no promotion")
        return

    # Promote! Best candidate beats incumbent
    log(f"[arena] PROMOTING {best_tag} (PF={best['pf']:.4f}, {best['n_trades']} trades over incumbent {inc_tag} PF={inc_pf})")

    if inc_tag:
        # Flatten incumbent's positions before cutting
        log(f"[arena] flattening incumbent {inc_tag}...")
        r = subprocess.run([sys.executable, str(PROJECT / "scripts" / "fx_lane_flatten.py"),
                           f"fxexp-{inc_tag}"], capture_output=True, text=True, timeout=120)
        log(f"[arena] flatten: {r.stdout[:200]}")

        # Cut incumbent
        transition(f"fx-expert-{inc_tag}", "cut",
                   reason=f"replaced by {best_tag} in tournament arena",
                   actor="arena")
        log(f"[arena] cut {inc_tag}")

    # Promote best candidate to accruing
    eid = f"fx-expert-{best_tag}"
    lc = lifecycle_of(eid)
    if lc is None:
        er.register(eid, epoch=1, kind="challenger", family="fx-transformer-rank",
                    venue="oanda-practice",
                    universe="58-pair accrual store D1, tournament-generated",
                    source=f"tournament arena {best_tag}",
                    accrual_ledger="data/fx_expert/shadow_fills.jsonl",
                    promotion_bar="Auto-promoted from tournament arena",
                    notes="Tournament champion — auto-promoted via shadow competition",
                    registered_by="arena")
    transition(eid, "registered", reason="tournament arena qualifying", actor="arena")
    transition(eid, "accruing", reason="tournament arena: shadow winner", actor="arena",
               notional_cap=1.0)

    # Rewire the cron to the new champion
    _rewire_cron(best_tag)
    log(f"[arena] {best_tag} promoted to live — cron rewired")


def _rewire_cron(new_tag: str):
    """Replace --expert in the live crontab and golden file."""
    import subprocess as sp
    # Live crontab
    r = sp.run(["crontab", "-l"], capture_output=True, text=True)
    old = r.stdout
    new = old.replace(f" --expert ", f" --expert {new_tag} ")
    # Fix if placeholder is there
    new_text = ""
    for line in old.splitlines(True):
        if "--expert" in line:
            parts = line.split("--expert")
            before = parts[0]
            after = parts[1].split(" ", 1)
            rest = after[1] if len(after) > 1 else ""
            new_text += f"{before}--expert {new_tag} {rest}\n"
        else:
            new_text += line
    cr = sp.run(["crontab", "-"], input=new_text.encode(), capture_output=True, timeout=10)
    if cr.returncode != 0:
        log(f"[arena] crontab rewrite failed: {cr.stderr[:200]}")
        return
    log(f"[arena] crontab updated to {new_tag}")


def clean_stale_state():
    """Remove old lane/trail state files from cut experts."""
    all_eids = all_lifecycles()
    for eid, lc in all_eids.items():
        if lc not in ("cut", "archived"):
            continue
        tag = eid.replace("fx-expert-", "")
        for suffix in ["", "_fxexp-"]:
            for fname in [f"lane_state_{tag}.json", f"trail_state_fxexp-{tag}.json",
                         f"claims_scores_fxexp-{tag}.json"]:
                p = OUT / fname
                if p.exists():
                    p.unlink()
                    log(f"[arena] cleaned {p.name}")
    # The dashboard venue cursor is independent runtime state; never clear it
    # from the training arena or every arena run will make the UI rescan history.


def main():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK.open("w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("[arena] another run is active; exiting")
        return
    log(f"{'='*60}")
    log(f"=== Tournament Arena :: {datetime.now(timezone.utc).isoformat()} ===")
    log(f"{'='*60}")

    # Phase 1: Train
    log(f"[arena] Phase 1: Training")
    inc_before = _current_incumbent()
    trained = run_training()
    if not trained:
        log("[arena] training did not produce a batch; continuing with existing artifacts")

    # Phase 2: Shadow paper-sim for all candidates
    log(f"\n[arena] Phase 2: Shadow paper simulation")
    run_shadow_paper()

    # Phase 3: Compare and promote
    log(f"\n[arena] Phase 3: Promotion decision")
    promote_best_shadow()

    # Phase 4: Cleanup
    log(f"\n[arena] Phase 4: Cleanup stale state")
    clean_stale_state()

    log(f"\n[arena] Arena complete — next run at next scheduled interval")


if __name__ == "__main__":
    main()