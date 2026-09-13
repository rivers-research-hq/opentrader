#!/usr/bin/env python3
"""fxexp_leak_ab — the #249 D1 leak A/B (pre-registered 2026-09-12).

Question (map #243, #249): did the #244 standardization-leak fix change the
reported OOS numbers — did the leak flatter, hurt, or sit neutral to PF/IC?
This determines whether any pre-fix number is quotable.

Design: PAIRED A/B on ONE panel. The same hp config, seed and warm checkpoint
are trained twice, differing ONLY in the standardization stats source
(leak_standardization=True reintroduces the pre-#244 path; fxexpert/train.py).
The recorded pre-fix history values are context only — their panel predates
the current one (rows and features changed, panel rebuilds are not
snapshotted per generation), so they cannot be the comparator.

Pre-registration (docs/agents/research/fxexp-leak-ab-preregistration-2026-09-12.md):
  configs  U and V — the distinct hp of the decision-relevant generations
           (g137/g151/g185 = U, g138 = V), read from their train_g*.json
  warm     g109 in BOTH arms (their recorded warm source; identical across
           arms so the paired diff isolates the standardization leak)
  seeds    11 + 1009*k for k = 0..4 (the loop's own gseed formula shape)
  metrics  OOS IC mean = primary (the search's selection statistic);
           gate PF via fxgate.rescore = secondary
  verdict  sign test over the 10 (config, seed) pairs on dIC = leaky - fixed:
             >= 8 pairs dIC > 0  -> "leak flattered IC"
             >= 8 pairs dIC < 0  -> "leak hurt IC"
             else                -> "not resolved at this power (10 pairs)"
           dPF medians reported as context, never as the verdict.

GPU-window contract (AGENTS.md): run `rcheck check_environment` first; idle
window only (VRAM-lock rule — this script REFUSES without --confirm-idle and
without CUDA); never disturb the live loop. A/B tags (ab<cfg><L|F><k>) are
non-numeric, so the deflation populations (scripts/white_reality_check.py)
and the loop's history/state/registry are untouched. Record honestly even
if nothing promotes.

Usage: .venv/bin/python3 scripts/fxexp_leak_ab.py --confirm-idle
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

PREREG = "docs/agents/research/fxexp-leak-ab-preregistration-2026-09-12.md"
WARM_TAG = "109"
BASE_SEED = 11
SEED_STRIDE = 1009
N_SEEDS = 5
# tag -> config letter: the distinct hp of the named generations (map #243)
CONFIG_SOURCES = {"U": ("137", "151", "185"), "V": ("138",)}
OUT = PROJECT / "data" / "fx_expert" / "leak_ab_result.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-idle", action="store_true",
                    help="confirm the GPU is in an idle window (VRAM-lock rule)")
    ap.add_argument("--configs", default="U,V")
    ap.add_argument("--seeds", type=int, default=N_SEEDS)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    if not a.confirm_idle:
        raise SystemExit("[leak-ab] refusing: this is a GPU idle-window job "
                         "(VRAM-lock rule). Re-run with --confirm-idle after "
                         "`rcheck check_environment`.")
    import torch
    if getattr(torch.version, "hip", None):
        # ROCm torch's "cuda" device is the RX 7900 GRE — the human's gaming
        # GPU (incident 2026-09-13: a guard test trained on it via the ROCm
        # venv). The GRE is never a compute target; the 3070 is the GPU job
        # device. version check first: is_available() would init HIP.
        raise SystemExit("[leak-ab] refusing: this is a ROCm torch build — "
                         "its cuda device is the RX 7900 GRE (gaming GPU). "
                         "Run with the CUDA venv: "
                         ".venv-cuda/bin/python scripts/fxexp_leak_ab.py "
                         "--confirm-idle")
    if not torch.cuda.is_available():
        raise SystemExit("[leak-ab] refusing: no CUDA device — the A/B is "
                         "pinned to the RTX 3070.")
    if "RTX 3070" not in torch.cuda.get_device_name(0):
        raise SystemExit(f"[leak-ab] refusing: CUDA device 0 is "
                         f"{torch.cuda.get_device_name(0)!r}, not the RTX "
                         f"3070 — wrong machine or wrong device order.")

    from fxexpert import gate as fxgate
    from fxexpert import train as fxtrain

    panel_meta = json.loads((fxtrain.OUT_DIR / "panel_meta.json").read_text())

    warm_folds = sorted(
        p.name for p in (fxtrain.OUT_DIR / "checkpoints").glob(f"g{WARM_TAG}_f*.pt"))
    if not warm_folds:
        raise SystemExit(f"[leak-ab] no per-fold warm checkpoints "
                         f"g{WARM_TAG}_f*.pt — the pre-registered warm "
                         f"source is missing; do not silently substitute")

    runs = []
    for cfg in [c.strip().upper() for c in a.configs.split(",") if c.strip()]:
        if cfg not in CONFIG_SOURCES:
            raise SystemExit(f"[leak-ab] unknown config {cfg!r} "
                             f"(known: {sorted(CONFIG_SOURCES)})")
        hp = json.loads(
            (fxtrain.OUT_DIR / f"train_g{CONFIG_SOURCES[cfg][0]}.json").read_text())["hp"]
        for k in range(a.seeds):
            seed = BASE_SEED + SEED_STRIDE * k
            for leak in (True, False):
                tag = f"ab{cfg}{'L' if leak else 'F'}{k}"
                g = fxtrain.run_generation(tag, hp, warm_tag=WARM_TAG,
                                           seed=seed, panel=None,
                                           leak_standardization=leak)
                runs.append({
                    "config": cfg, "seed": seed, "leaky": leak, "tag": tag,
                    "ic_mean": g["aggregate"]["ic_mean"],
                    "folds_positive": g["aggregate"]["folds_positive"],
                    "n_folds": g["aggregate"]["n_folds"],
                    "pf": fxgate.rescore(tag),
                })
                print(f"[leak-ab] {tag}: IC {g['aggregate']['ic_mean']} "
                      f"PF {runs[-1]['pf']}")

    # paired verdict per the pre-registered rule
    by_key = {(r["config"], r["seed"], r["leaky"]): r for r in runs}
    pairs = []
    for cfg in CONFIG_SOURCES:
        for k in range(a.seeds):
            seed = BASE_SEED + SEED_STRIDE * k
            L, F = by_key[(cfg, seed, True)], by_key[(cfg, seed, False)]
            if L["ic_mean"] is None or F["ic_mean"] is None:
                continue
            pairs.append({"config": cfg, "seed": seed,
                          "ic_leaky": L["ic_mean"], "ic_fixed": F["ic_mean"],
                          "d_ic": round(L["ic_mean"] - F["ic_mean"], 5),
                          "pf_leaky": L["pf"], "pf_fixed": F["pf"],
                          "d_pf": None if None in (L["pf"], F["pf"])
                          else round(L["pf"] - F["pf"], 4)})
    pos = sum(1 for p in pairs if p["d_ic"] > 0)
    neg = sum(1 for p in pairs if p["d_ic"] < 0)
    n = len(pairs)
    verdict = ("leak flattered IC" if n and pos >= 0.8 * n else
               "leak hurt IC" if n and neg >= 0.8 * n else
               "not resolved at this power")
    dics = sorted(p["d_ic"] for p in pairs)
    dpfs = sorted(p["d_pf"] for p in pairs if p["d_pf"] is not None)
    result = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "preregistration": PREREG,
        "question": "#249 D1: did the #244 standardization leak flatter, hurt, "
                    "or sit neutral to reported PF/IC?",
        "device": torch.cuda.get_device_name(0),
        "panel_snapshot": {"n_rows": panel_meta.get("n_rows"),
                           "date_min": panel_meta.get("date_min"),
                           "date_max": panel_meta.get("date_max"),
                           "n_features": panel_meta.get("n_features")},
        "design": {"configs": sorted(CONFIG_SOURCES), "warm_tag": WARM_TAG,
                   "seeds": [BASE_SEED + SEED_STRIDE * k for k in range(a.seeds)],
                   "metric_primary": "oos_ic_mean", "metric_secondary": "gate_pf"},
        "runs": runs,
        "pairs": pairs,
        "verdict": {"rule": f"sign test, >= 80% of {n} pairs on d_ic",
                    "n_pairs": n, "pos": pos, "neg": neg,
                    "median_d_ic": dics[len(dics) // 2] if dics else None,
                    "median_d_pf": dpfs[len(dpfs) // 2] if dpfs else None,
                    "verdict": verdict},
    }
    Path(a.out).write_text(json.dumps(result, indent=1))
    print(f"\n[leak-ab] {verdict}  (dIC>0 {pos}/{n}, dIC<0 {neg}/{n}, "
          f"median dIC {result['verdict']['median_d_ic']}, "
          f"median dPF {result['verdict']['median_d_pf']})")
    print(f"[leak-ab] wrote {a.out} — record the verdict on #249 verbatim")


if __name__ == "__main__":
    main()
