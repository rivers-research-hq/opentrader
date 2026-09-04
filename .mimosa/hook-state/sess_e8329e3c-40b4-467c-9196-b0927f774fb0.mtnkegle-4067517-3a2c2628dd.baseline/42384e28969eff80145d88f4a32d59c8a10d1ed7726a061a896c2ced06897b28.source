"""The curriculum loop: student iterates, curriculum grades, Architect reviews.

Per iteration: run the arena iteration (carrot-tuned battle passes) -> grade
the curriculum (carrot/stick, gating, progression) -> every `arch_every`
iterations, the locally-trained Architect proposes the next skill (validated
and queued). Every `distill_every` iterations the momentum agent is
re-distilled via QLoRA on GPU0 (the heavy, sustained GPU work) from the
arena's labeled dataset at the carrot's budget. Run supervised; writes
data/arena/curriculum.json + the usual arena artifacts.
"""

import subprocess
import sys
from pathlib import Path

from arena import architect as arch_mod
from arena import curriculum as cur_mod
from arena import train as train_mod

PROJECT = Path(__file__).resolve().parent.parent
ROCM_PY = "/home/mrc/rocm_venv/bin/python3"
EXPORT = PROJECT / "data/arena/momentum_dataset.jsonl"


def _distill(budget):
    print(f"[loop] distill: exporting {budget} arena-labeled examples", flush=True)
    r = subprocess.run(
        [sys.executable, "-m", "arena.export", "--examples", str(budget)],
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    last = (r.stdout.strip().splitlines() or [r.stderr[-200:]] or [""])[-1]
    print(last, flush=True)
    if not EXPORT.exists() or EXPORT.stat().st_size < 2000:
        raise SystemExit(f"distill aborted: export produced no dataset ({last})")
    print(f"[loop] distill: QLoRA on GPU0 (budget {budget})", flush=True)
    subprocess.run(
        [
            ROCM_PY,
            "-m",
            "setup_search.train_momentum_agent",
            "--dataset",
            str(EXPORT),
            "--batch",
            "2",
        ],
        cwd=PROJECT,
        check=True,
    )
    print("[loop] distill done", flush=True)


def _notify(status, message):
    import json as _json
    from datetime import datetime, timezone

    marker = PROJECT / "data/arena/run_status.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        _json.dumps(
            {
                "status": status,
                "message": message,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            indent=1,
        )
    )
    try:
        subprocess.run(
            [
                "notify-send",
                "-u",
                "critical" if status != "completed" else "normal",
                f"opentrader: curriculum {status}",
                message[:220],
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception:
        pass


def run(
    iterations,
    arch_every=2,
    distill_every=3,
    epochs=400,
    eta=1.0,
    period="5y",
    war_period="5y",
):
    try:
        _run(iterations, arch_every, distill_every, epochs, eta, period, war_period)
        _notify(
            "completed",
            f"{iterations} iterations done; see data/arena/overnight-monitor-summary.md",
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        _notify("CRASHED", f"curriculum loop crashed: {e}")
        raise


def _run(iterations, arch_every, distill_every, epochs, eta, period, war_period):
    for i in range(iterations):
        state = cur_mod.load_state()
        carrot = state.get("carrot", {})
        n_battles = carrot.get("battle_passes", 8)
        print(
            f"[loop] run {i + 1}/{iterations} | battle passes {n_battles} "
            f"(carrot) | epochs {epochs}",
            flush=True,
        )
        train_mod.run_iteration(
            period=period,
            war_period=war_period,
            n_battles=n_battles,
            epochs=epochs,
            eta=eta,
            use_previous=True,
        )
        cur_mod.run_grade_step()
        if (i + 1) % arch_every == 0:
            print(f"[loop] architect review ({i + 1})", flush=True)
            proposal, ok = arch_mod.arch_review()
            print(f"[loop] architect verdict: {'PASS' if ok else 'FAIL'}", flush=True)
        if distill_every and (i + 1) % distill_every == 0:
            _distill(carrot.get("qlora_budget", 400))
    print("[loop] done", flush=True)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=6)
    ap.add_argument("--arch-every", type=int, default=2)
    ap.add_argument("--distill-every", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--eta", type=float, default=1.0)
    args = ap.parse_args()
    run(args.iterations, args.arch_every, args.distill_every, args.epochs, args.eta)
