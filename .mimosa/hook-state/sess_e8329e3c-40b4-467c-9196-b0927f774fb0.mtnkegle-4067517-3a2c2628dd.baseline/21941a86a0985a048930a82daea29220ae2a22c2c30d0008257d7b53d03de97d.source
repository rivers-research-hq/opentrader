#!/usr/bin/env python3
"""GPU1 setup-search loop orchestrator.

Each iteration: ask the LLM Scientist (on GPU1) to propose candidate configs
from the running feedback, evaluate each with a fast cost-aware backtest,
score it, checkpoint, and feed the results back. Adds local jitter mutants
of the current best so progress continues even if the LLM call fails.

Resumes from checkpoint; stops on iteration / wall-clock / plateau budget.
"""

import argparse
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from setup_search.core import (
    CONFIG_BOUNDS,
    DEFAULT_CONFIG,
    clamp_config,
    objective,
    summary_bundle,
)
from setup_search.data import REGIME_SYM, load_ohlcv, align, slice_aligned
from setup_search.engine import run_backtest
from setup_search.scientist import propose_configs
from setup_search.wide import build_wide_aligned, wide_metrics

PROJECT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT / "data" / "setup_search"

OBJECTIVE_NOTE = (
    "score = 0.6*ann_sharpe + 1.0*max(net_return,0,cap=0.6) "
    "- 2.0*max_drawdown - 3.0*fee_ratio - 0.3*churn(n_trades/300). "
    "Fee-bleed and drawdown are heavily penalized; a flat account beats a "
    "churning one."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jitter(cfg: dict, rng: random.Random, sigma: float = 0.15) -> dict:
    out = dict(cfg)
    keys = list(CONFIG_BOUNDS.keys())
    rng.shuffle(keys)
    for k in keys[: rng.randint(2, 5)]:
        lo, hi = CONFIG_BOUNDS[k]
        cur = out[k]
        if isinstance(cur, int) or k in (
            "rank_on",
            "regime_filter",
            "max_positions",
            "max_hold",
            "mom_lb",
            "rev_lb",
            "rsi_period",
            "breakout_lb",
            "z_period",
            "regime_window",
        ):
            step = max(1, int(round((hi - lo) * sigma)))
            out[k] = int(min(hi, max(lo, cur + rng.choice([-1, 1]) * step)))
        else:
            delta = (hi - lo) * sigma * rng.gauss(0, 1)
            out[k] = round(min(hi, max(lo, cur + delta)), 4)
    return clamp_config(out)


def random_cfg(rng: random.Random) -> dict:
    out = {}
    for k, (lo, hi) in CONFIG_BOUNDS.items():
        if k in ("rank_on", "regime_filter"):
            out[k] = rng.randint(0, 1)
        elif k in ("max_positions", "max_hold") or k in (
            "mom_lb",
            "rev_lb",
            "rsi_period",
            "breakout_lb",
            "z_period",
            "regime_window",
        ):
            out[k] = rng.randint(int(lo), int(hi))
        else:
            out[k] = round(rng.uniform(lo, hi), 4)
    return clamp_config(out)


def _save(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, default=str)
    tmp.replace(path)


def load_checkpoint():
    ledger_path = OUT_DIR / "ledger.jsonl"
    best_path = OUT_DIR / "best.json"
    history = []
    if ledger_path.exists():
        for line in ledger_path.read_text().splitlines():
            if line.strip():
                history.append(json.loads(line))
    best = None
    if best_path.exists():
        try:
            best = json.loads(best_path.read_text())
        except Exception:
            best = None
    return history, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=600)
    ap.add_argument("--max-hours", type=float, default=10.0)
    ap.add_argument("--plateau", type=int, default=60)
    ap.add_argument("--data-period", default="2y")
    ap.add_argument("--force-data", action="store_true")
    ap.add_argument("--scientist-every", type=int, default=1)
    ap.add_argument("--mutants", type=int, default=4)
    ap.add_argument("--val-pct", type=float, default=0.25)
    ap.add_argument("--random-restart-every", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--wide-eval", action="store_true",
                    help="gate promotions on the wide universe (511-registry "
                         "generalization check, regime ON)")
    ap.add_argument("--wide-min", type=float, default=0.0,
                    help="minimum wide net_return (fraction) for promotion")
    ap.add_argument("--wide-min-trades", type=int, default=8,
                    help="minimum wide trade count for promotion (kills "
                         "'stand down' configs that pass wide by not trading)")
    ap.add_argument("--wide-max-fee-ratio", type=float, default=0.5,
                    help="reject configs whose wide fees exceed this fraction "
                         "of the account (churn degenerates like tiny trailing "
                         "stops pass wide-net by capturing daily highs)")
    ap.add_argument("--search-wide", action="store_true",
                    help="run the main evaluation on the wide universe "
                         "(implies --wide-eval); much slower per iter")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    start_wall = time.time()
    deadline = start_wall + args.max_hours * 3600

    data = load_ohlcv(args.data_period, force=args.force_data)
    syms = [s for s in data.keys() if s != REGIME_SYM]
    aligned = align(data, syms)
    n_sym = len(aligned[0])
    n_bars = len(next(iter(aligned[0].values())).index)
    print(f"[loop] data: {n_sym} tradable symbols, {n_bars} bars")

    # Wide-universe generalization set (harness 511-registry ∩ archive,
    # regime ON). Gate / main-search target when --wide-eval / --search-wide.
    wide_aligned = None
    if args.wide_eval or args.search_wide:
        wide_aligned = build_wide_aligned()
        print(f"[loop] wide set: {len(wide_aligned[0])} symbols "
              f"({len(next(iter(wide_aligned[0].values())).index)} bars)")
    if args.search_wide:
        aligned = wide_aligned
        syms = sorted(aligned[0].keys())
        n_sym = len(aligned[0])
        n_bars = len(next(iter(aligned[0].values())).index)
        print(f"[loop] SEARCH-WIDE: main evaluation on {n_sym} symbols")

    val_start = int(n_bars * (1 - args.val_pct))
    val_aligned = slice_aligned(aligned, val_start, n_bars)
    print(f"[loop] validation window: last {args.val_pct:.0%} (bars {val_start}..{n_bars})")

    history, best = load_checkpoint()

    def _is_active(metrics):
        return int(metrics.get("n_trades", 0)) >= 8

    # Only an ACTIVE config (>= 8 trades) can be the search target; a flat
    # config scoring 0.0 would otherwise collapse the search into "do nothing".
    if best and not _is_active(best.get("metrics", {})):
        best = None
    if best:
        best = {**best, "active": True}
        best_score = best["score"]
    else:
        best_score = -999.0

    iter0 = max((r["iter"] for r in history), default=-1) + 1
    if len(history) == 0:
        base = clamp_config(DEFAULT_CONFIG)
        m = run_backtest(aligned, base)
        metrics = {k: v for k, v in m.items() if k != "equity"}
        rec = {
            "iter": 0,
            "ts": _now(),
            "config": base,
            "score": objective(metrics),
            "summary": summary_bundle(metrics),
            "source": "baseline",
        }
        history.append(rec)
        with open(OUT_DIR / "ledger.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        if _is_active(metrics):
            best = {
                "config": base,
                "score": rec["score"],
                "summary": rec["summary"],
                "metrics": metrics,
                "equity": [round(x, 2) for x in m["equity"].tolist()],
                "iter": 0,
                "active": True,
            }
            _save(OUT_DIR / "best.json", best)
        print(f"[loop] baseline score={rec['score']} {rec['summary']}")

    if best is None:
        print("[loop] seeding best with a random ACTIVE config...")
        for _ in range(40):
            cfg = random_cfg(rng)
            try:
                m = run_backtest(aligned, cfg)
                metrics = {k: v for k, v in m.items() if k != "equity"}
            except Exception:
                continue
            if _is_active(metrics):
                best = {
                    "config": cfg,
                    "score": objective(metrics),
                    "summary": summary_bundle(metrics),
                    "metrics": metrics,
                    "equity": [round(x, 2) for x in m["equity"].tolist()],
                    "iter": -1,
                    "active": True,
                }
                _save(OUT_DIR / "best.json", best)
                break
    best_score = best["score"] if best else -999.0
    since_improve = 0

    # Re-validate a checkpoint best against the recent-data gate (and the
    # wide generalization gate when --wide-eval).
    target = best_score
    if best:
        try:
            vb = run_backtest(val_aligned, best["config"])
            vb_met = {k: v for k, v in vb.items() if k != "equity"}
            best["val"] = summary_bundle(vb_met)
            gate_failures = []
            if vb_met.get("net_return", 0) < 0:
                gate_failures.append(f"recent-val {summary_bundle(vb_met)}")
            if wide_aligned is not None:
                wm = wide_metrics(wide_aligned, best["config"])
                best["wide"] = summary_bundle(wm)
                best["wide_net"] = round(wm.get("net_return", 0.0), 4)
                if (wm.get("net_return", 0) < args.wide_min
                        or int(wm.get("n_trades", 0)) < args.wide_min_trades
                        or float(wm.get("fee_ratio", 0.0)) > args.wide_max_fee_ratio):
                    gate_failures.append(f"wide {summary_bundle(wm)}")
            if gate_failures:
                target = 0.0
                print(
                    f"[loop] NOTE: checkpoint best fails gate "
                    f"({' | '.join(gate_failures)}) — target lowered so "
                    f"gate-passing configs can replace it"
                )
            else:
                print(
                    f"[loop] checkpoint best passes gates: "
                    f"val={best.get('val')} wide={best.get('wide', '-')}"
                )
        except Exception as e:
            print(f"[loop] checkpoint re-validation error: {e}")

    for it in range(iter0, args.iters + 1):
        if time.time() > deadline:
            print("[loop] wall-clock budget reached — stopping")
            break
        proposals = []
        if it % args.scientist_every == 0:
            try:
                proposals = propose_configs(history, best, OBJECTIVE_NOTE)
            except Exception as e:
                print(f"[loop] scientist raised: {e}")
        for p in proposals:
            proposals.append(p)
            if len(proposals) >= 8:
                break
        for _ in range(args.mutants):
            base_cfg = best["config"] if best else random_cfg(rng)
            sigma = 0.25 if rng.random() < 0.4 else 0.15
            proposals.append(
                {"reasoning": "jitter of best", "config": jitter(base_cfg, rng, sigma)}
            )
        if args.random_restart_every > 0 and it % args.random_restart_every == 0:
            for _ in range(2):
                proposals.append(
                    {"reasoning": "random restart", "config": random_cfg(rng)}
                )
        if len(proposals) < 2:
            proposals.append({"reasoning": "random", "config": random_cfg(rng)})

        any_new_best = False
        for p in proposals:
            cfg = p.get("config")
            if not isinstance(cfg, dict):
                continue
            try:
                m = run_backtest(aligned, cfg)
                metrics = {k: v for k, v in m.items() if k != "equity"}
                score = objective(metrics)
                v = run_backtest(val_aligned, cfg)
                val_metrics = {k: vv for k, vv in v.items() if k != "equity"}
                val_net = val_metrics.get("net_return", 0.0)
            except Exception as e:
                print(f"[loop] backtest error: {e}")
                continue
            rec = {
                "iter": it,
                "ts": _now(),
                "config": cfg,
                "score": score,
                "summary": summary_bundle(metrics),
                "val": summary_bundle(val_metrics),
                "val_net": round(val_net, 4),
                "source": p.get("reasoning", "?")[:60],
            }
            # Generalization gate: a config must clear the FAST gates first
            # (active, score > target, recent-val >= 0) before the expensive
            # wide check runs. Only then can it promote.
            wide_net, wide_ok = None, True
            if wide_aligned is not None and _is_active(metrics) and score > target and val_net >= 0:
                try:
                    wm = wide_metrics(wide_aligned, cfg)
                    wide_net = wm.get("net_return", 0.0)
                    wide_trades = int(wm.get("n_trades", 0))
                    wide_fee_ratio = float(wm.get("fee_ratio", 0.0))
                    rec["wide"] = summary_bundle(wm)
                    rec["wide_net"] = round(wide_net, 4)
                    wide_ok = (
                        wide_net >= args.wide_min
                        and wide_trades >= args.wide_min_trades
                        and wide_fee_ratio <= args.wide_max_fee_ratio
                    )
                    if not wide_ok:
                        print(
                            f"[loop] iter {it}: score={score} val={val_net:+.2%} "
                            f"BUT wide={wide_net:+.2%} ({wide_trades} trd, "
                            f"fee%={wide_fee_ratio:.0%}) {rec['wide']} — "
                            f"rejected by generalization gate"
                        )
                except Exception as e:
                    print(f"[loop] iter {it}: wide eval error: {e}")
                    wide_ok = False
                    rec["wide"] = f"error:{e}"
            history.append(rec)
            with open(OUT_DIR / "ledger.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
            if _is_active(metrics) and score > target and val_net >= 0 and wide_ok:
                target = score
                best_score = score
                since_improve = 0
                best = {
                    "config": cfg,
                    "score": score,
                    "summary": rec["summary"],
                    "metrics": metrics,
                    "val": rec["val"],
                    "val_net": val_net,
                    "wide": rec.get("wide"),
                    "wide_net": rec.get("wide_net"),
                    "equity": [round(x, 2) for x in m["equity"].tolist()],
                    "iter": it,
                    "ts": _now(),
                    "active": True,
                }
                _save(OUT_DIR / "best.json", best)
                any_new_best = True
                print(
                    f"[loop] iter {it}: NEW BEST score={score} val={val_net:+.2%} "
                    f"{rec['summary']} src={rec['source']}"
                )
            elif score > target and val_net < 0:
                print(
                    f"[loop] iter {it}: score={score} but val={val_net:+.2%} "
                    f"({rec['summary']}) — rejected by recent-validation gate"
                )
            elif _is_active(metrics) and score > target and not wide_ok:
                # passed the fast gates but failed the wide generalization
                # gate — counted toward the plateau so the search stops
                # churning a neighborhood that cannot generalize.
                since_improve += 1
            elif score > target:
                print(
                    f"[loop] iter {it}: inactive config score={score} "
                    f"({rec['summary']}) — ignored (need >= 8 trades)"
                )
            else:
                since_improve += 1

        _save(
            OUT_DIR / "progress.json",
            {
                "iter": it,
                "best_score": best_score,
                "best_iter": best["iter"] if best else None,
                "n_evaluated": len(history),
                "since_improve": since_improve,
                "ts": _now(),
            },
        )
        if it % 10 == 0 or any_new_best:
            print(
                f"[loop] iter {it}/{args.iters} best={best_score} "
                f"(evaluated={len(history)}, plateau={since_improve})"
            )
        if since_improve >= args.plateau:
            print(f"[loop] plateau reached after {since_improve} iters — stopping")
            break

    print("\n[loop] DONE")
    if best:
        print(f"best score={best['score']} iter={best['iter']}")
        print(f"config={json.dumps(best['config'])}")
        print(f"metrics={best['summary']}")


if __name__ == "__main__":
    main()
