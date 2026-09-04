#!/usr/bin/env python3
"""proposal_loop — the strategy-discovery lane (the self-improvement loop's
propose -> falsify -> register pipeline).

An LLM proposes candidate signals (sandbox-safe: no imports, no loops, no
I/O — the gym's AST check plus stricter proposal rules); each proposal is
trial-loaded, falsified by the gym walkforward (survival bar: IS n>=10
PF>=1.2 AND OOS n>=5 PF>=1.0), and gym survivors face the 1000-worlds
robustness bar (>=70% of worlds PF>1, real path in the 25th-90th percentile,
per protocol §5d). Only double survivors surface for human review — registry
registration stays human-gated, always.

Proposer: deepseek-v4-flash, thinking disabled, temperature 0.9 (diversity).
Cost per batch: ~$0.01. Cron: weekly Sunday 09:30.

Usage:
  python3 scripts/proposal_loop.py --n 5          # validate / weekly batch
  python3 scripts/proposal_loop.py --n 10 --tier flash
"""

import ast
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "scripts"))
from signal_gym import CAND_DIR, Ctx, load_candidate, simulate, stats  # noqa: E402
from agent_gym import LLM  # noqa: E402

CANDLES = PROJECT / "data" / "signal_gym" / "candles.json"
EXOG = PROJECT / "data" / "exog_cache.json"
OUT = PROJECT / "data" / "agent_gym" / "proposals"

PROMPT = """You are a quantitative strategist proposing ONE new FX trading signal as a Python file.

INSTRUMENTS: EUR_USD, GBP_USD, USD_JPY, USD_CHF, GBP_JPY, AUD_USD, USD_CAD.
Once per completed daily bar the engine hands you a read-only context `ctx`:
  ctx.symbols            # the 7 instruments
  ctx.close(sym)         # today's close (float or None)
  ctx.ma(sym, n)         # mean of the n closes BEFORE today (None if insufficient history)
  ctx.atr(sym, n)        # ATR over the n bars before today
  ctx.mom(sym, k)        # k-day return
  ctx.exog("COT:EUR")    # CFTC leveraged-money positioning z-score (3-day publication lag); keys: EUR JPY GBP CHF CAD AUD NZD
  ctx.exog("CARRY:EUR_USD")  # annualized carry of a LONG in the pair (base minus quote policy rate); None if unknown
  ctx.exog("RATE:US")    # US policy rate level in percent

RISK SHAPE (fixed by the engine, not your concern): long-only, top-2 picks by
weight, $10k per position, 1.5x/2.5x ATR-14 stop/target attached, 14-day max hold.

ALREADY PROPOSED (do NOT re-propose, including simple variations of them):
{catalog}

REQUIREMENTS:
1. Exactly one Python file in this format:
NAME = "unique_snake_case_name"
def entry(ctx):
    # no imports, no while-loops, no file/network access, <= 30 lines
    return {{sym: weight}}   # ONLY instruments to long; 1.0 typical
2. Ground the hypothesis in something observable via ctx — price structure,
   positioning (COT), carry, or rate levels. State the hypothesis in a comment.
3. It must be meaningfully DIFFERENT from everything in the already-proposed list.
4. Guard every lookup: ctx.close/ma/atr/exog can return None.

Respond with ONLY the Python code in one fenced block."""


def extended_safety(path):
    """Gym check + stricter proposal rules: no while-loops (bounded for only),
    no attribute access to dunder names."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("imports are not allowed")
        if isinstance(node, ast.While):
            raise ValueError("while-loops are not allowed in proposals")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("open", "exec", "eval", "compile", "__import__"):
                raise ValueError(f"{node.func.id}() is not allowed")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("dunder attribute access is not allowed")
    return True


def extract_code(msg):
    fence = re.search(r"```(?:python)?\s*(.*?)```", msg, re.S)
    code = fence.group(1) if fence else msg
    i = code.find("NAME")
    if i < 0:
        raise ValueError("no NAME assignment found")
    return code[i:].rstrip() + "\n"


def next_proposal_index():
    nums = [int(m.group(1)) for f in CAND_DIR.glob("p*.py")
            if (m := re.match(r"p(\d+)_", f.name))]
    return (max(nums) + 1) if nums else 1


def main():
    argv = sys.argv
    n_target = int(argv[argv.index("--n") + 1]) if "--n" in argv else 5
    tier = argv[argv.index("--tier") + 1] if "--tier" in argv else "flash"
    n_worlds = int(argv[argv.index("--worlds") + 1]) if "--worlds" in argv else 1000

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = OUT / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = json.load(open(PROJECT / "config" / "agent_gate_models.json"))["tiers"][tier]
    api_key = __import__("os").environ.get(cfg.get("api_key_env") or "", "")
    llm = LLM(tier, cfg["base_url"], cfg["model"], api_key,
              extras={**cfg.get("request_extras", {}), "temperature": 0.9},
              log=(run_dir / "proposer_raw.jsonl").open("a"))

    catalog = []
    for f in sorted(CAND_DIR.glob("*.py")):
        try:
            head = f.read_text().splitlines()
            name = next((l for l in head if l.startswith("NAME")), f"name = '{f.stem}'")
            doc = next((l.strip("# ").strip() for l in head
                        if l.strip().startswith("#") and len(l.strip()) > 10), "")
            catalog.append(f"- {f.stem} ({name.strip()}): {doc[:90]}")
        except Exception:
            continue

    # real-path context for trial runs
    raw = json.load(open(CANDLES))
    series = {s: {int(ts): tuple(px) for ts, px in d.items()} for s, d in raw.items()}
    dates = sorted({ts for s in series.values() for ts in s})
    symbols = list(series)
    exog = json.load(open(EXOG)) if EXOG.exists() else {}
    trial_ctx = Ctx(series, dates, 300, symbols, exog_series=exog)

    accepted, rejected = [], []
    attempts, max_attempts = 0, n_target * 4
    while len(accepted) < n_target and attempts < max_attempts:
        attempts += 1
        idea_line = f"proposal attempt {attempts} of {max_attempts}"
        accepted_lines = [f"- {a['file'].stem} ({a['name']}): already proposed this batch"
                          for a in accepted]
        prompt = PROMPT.format(catalog="\n".join(catalog + accepted_lines)) + \
            f"\n\n(Attempt {idea_line} — propose something NEW.)"
        try:
            msg, _u = llm._chat(prompt, log_ctx={"attempt": attempts})
        except Exception as e:
            rejected.append({"error": f"endpoint: {e}"})
            continue
        try:
            code = extract_code(msg)
            tmp = run_dir / f"attempt_{attempts}.py"
            tmp.write_text(code)
            extended_safety(tmp)
            cand = load_candidate(tmp)  # gym safety + NAME/entry assertion
            test = cand.entry(trial_ctx)  # trial run on a real bar
            assert isinstance(test, dict)
        except Exception as e:
            rejected.append({"error": f"{type(e).__name__}: {e}",
                             "raw_tail": msg[-200:] if msg else ""})
            continue
        idx = next_proposal_index()
        final = CAND_DIR / f"p{idx:02d}_{cand.NAME}.py"
        tmp.rename(final)
        catalog.append(f"- {final.stem} ({cand.NAME}): just proposed this batch")
        accepted.append({"file": final, "name": cand.NAME, "idx": idx})
        print(f"  accepted p{idx:02d}_{cand.NAME}")

    # falsification: gym walkforward first
    results = []
    for a in accepted:
        cand = load_candidate(a["file"])
        trades, _ = simulate(cand, series, dates, symbols, int(len(dates) * 0.6), exog=exog)
        s_is, s_oos = stats(trades["is"]), stats(trades["oos"])
        survives = bool(s_is and s_oos and s_is["n"] >= 10 and s_is["pf"] >= 1.2
                        and s_oos["n"] >= 5 and s_oos["pf"] >= 1.0)
        a.update({"gym": {"is": s_is, "oos": s_oos, "survives": survives}})
        if survives:
            subprocess = __import__("subprocess")
            r = subprocess.run(
                [sys.executable, str(PROJECT / "scripts" / "worlds.py"), "--worlds",
                 str(n_worlds), "--block-mean", "21", "--candidates", a["file"].stem],
                capture_output=True, text=True, timeout=1800)
            wj = Path(PROJECT / "data" / "agent_gym" / "worlds" /
                      f"w{n_worlds}-b21-s20260901" / "worlds.json")
            w = json.loads(wj.read_text())["candidates"].get(cand.NAME, {}) if wj.exists() else {}
            a["worlds"] = w
            a["robust"] = bool(w and w.get("worlds_pf_pct_gt1", 0) >= 70
                               and 25 <= (w.get("real_pf_percentile") or 0) <= 90)
        results.append(a)

    # report
    lines = [f"# proposal loop — {stamp}", "",
             f"{len(accepted)} accepted of {attempts} attempts ({n_target} target); "
             f"{len(rejected)} rejected at validation", ""]
    for a in results:
        g = a.get("gym", {})
        gi, go = g.get("is") or {}, g.get("oos") or {}
        gym_s = (f"IS n={gi.get('n')} PF {gi.get('pf')} / OOS n={go.get('n')} PF {go.get('pf')}"
                 if (gi or go) else "no trades")
        w = a.get("worlds") or {}
        w_s = (f"PF>1 {w.get('worlds_pf_pct_gt1')}% of worlds, real p{w.get('real_pf_percentile')}"
               if w else "—")
        status = ("SURVIVOR — human review" if a.get("robust")
                  else ("gym survivor, worlds-failed" if a.get("gym", {}).get("survives")
                        else "gym-dead"))
        lines.append(f"## {a['file'].stem} — {status}")
        lines.append(f"- gym: {gym_s}")
        if w_s != "—":
            lines.append(f"- worlds: {w_s}")
        lines.append("")
    if rejected:
        lines.append("## rejected at validation")
        for r in rejected[:10]:
            lines.append(f"- {r.get('error')}")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")
    (run_dir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    print(f"\nproposals: {len(accepted)} accepted, {len(rejected)} rejected "
          f"(validation) | report: {run_dir / 'report.md'}")
    for a in results:
        status = ("SURVIVOR — human review" if a.get("robust")
                  else ("gym survivor, worlds-failed" if a.get("gym", {}).get("survives")
                        else "gym-dead"))
        print(f"  {a['file'].stem:<28} {status}")


if __name__ == "__main__":
    main()
