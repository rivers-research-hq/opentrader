#!/usr/bin/env python3
"""Legacy cycle-history training data builder.

Converts the 7049 historical cycle_*.json files into ShareGPT training
examples for LoRA fine-tuning, by linking each completed trade outcome
back to the market context that was visible at the decision moment.

Pipeline:
    cycle_*.json  ─┐
                   ├─→ legacy_data_builder
    trades[]      ─┤    │
                   │    ├─ entry-side example (BUY/HOLD verdict)
                   │    └─ exit-side example  (SELL/HOLD verdict)
    signals[]     ─┤
                   │    └─ counterfactual HOLD reinforcement
                   └─→ training_data_legacy.jsonl (balanced, ShareGPT)

Each conversation:

    system: ADIR-style Bull/Bear/Risk agent system prompt
    user:   market context (prices, regime, portfolio, symbol_regimes)
    assistant: Action: BUY/SELL/HOLD. <outcome-aware reasoning>

Balancing strategy:
    - The raw history biases heavily toward HOLD (57% of signals, and
      most trades are SELL-closes of prior BUY positions). Without balancing
      the LoRA would overfit to "always HOLD".
    - We downsample HOLD entries to match the size of the BUY and SELL
      pools (or the smallest non-HOLD pool) so all three actions get
      approximately equal representation.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Make project root importable so we can reuse the ADIR system prompts
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mot.agents.adir_debate import (
    BEAR_SYSTEM_ADIR,
    BULL_SYSTEM_ADIR,
    RISK_SYSTEM_ADIR,
)

logger = logging.getLogger("opentrader.legacy_data_builder")

# Default tuning
DEFAULT_MAX_PER_CYCLE_TRADES = 50      # cycle files cap trades at 50 already
DEFAULT_MAX_HOLDS_PER_CYCLE = 4        # cap HOLD counterfactuals per cycle
DEFAULT_BALANCE_TARGET = "equal"       # match BUY/SELL sizes to each other


# ── System prompt (ADIR house style) ───────────────────────────────────────
SYSTEM_PROMPT = (
    "You are a crypto trading agent that decides BUY / SELL / HOLD via an "
    "adversarial debate. Three independent roles — Bull Analyst, Bear "
    "Auditor (Risk Auditor), and Risk Synthesizer — each produce a "
    "Claim-Evidence-Warrant argument grounded in specific indicator "
    "values; the Risk agent then scores both sides on evidence quality "
    "and issues the final action.\n\n"
    "Your job: read the market context, and output a single line —\n"
    "  Action: BUY | SELL | HOLD\n"
    "followed by a one-sentence evidence-grounded rationale that cites "
    "specific price, regime, or indicator data. Never invent facts not "
    "present in the context. When evidence is mixed or weak, HOLD is the "
    "default conservative answer."
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _cycle_num(fp: Path) -> int:
    try:
        return int(fp.stem.split("_")[1])
    except Exception:
        return 0


def _regime_label(cycle_data: dict, symbol: Optional[str] = None) -> str:
    """Best-effort human-readable regime label for the assistant template."""
    sr = cycle_data.get("symbol_regimes") or {}
    if symbol and symbol in sr:
        r = sr[symbol].get("regime")
        if r:
            return r
    # Fallback: scan any symbol regime
    for v in sr.values():
        if isinstance(v, dict) and v.get("regime"):
            return v["regime"]
    # final fallback: top-level regime dict has no direct label; use 'mixed'
    return "mixed"


def _format_positions(positions: list) -> str:
    """Match the style of harness._debate_one_symbol portfolio_json."""
    if not positions:
        return "no open positions"
    parts = []
    for p in positions:
        sym = p.get("symbol", "?")
        qty = float(p.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        entry = float(p.get("entry_price", 0) or 0)
        cur = float(p.get("current_price", entry) or entry)
        pnl_pct = ((cur - entry) / entry * 100) if entry > 0 else 0.0
        parts.append(
            f"{sym}: qty={qty:.6f} entry=${entry:.2f} "
            f"now=${cur:.2f} ({pnl_pct:+.2f}%)"
        )
    return "; ".join(parts) if parts else "no open positions"


def _format_symbol_regimes(symbol_regimes: dict, limit: int = 3) -> str:
    """Render per-symbol regime classification as compact JSON-ish text."""
    if not symbol_regimes:
        return "none"
    items = []
    for sym, info in list(symbol_regimes.items())[:limit]:
        if not isinstance(info, dict):
            continue
        regime = info.get("regime", "unknown")
        conf = info.get("confidence", 0)
        ind = info.get("indicators", {}) or {}
        adx = ind.get("adx")
        rsi = ind.get("rsi")
        bb = ind.get("bb_width")
        bits = [f"regime={regime}"]
        if conf is not None:
            bits.append(f"conf={float(conf):.2f}")
        if adx is not None:
            bits.append(f"ADX={float(adx):.1f}")
        if rsi is not None:
            bits.append(f"RSI={float(rsi):.1f}")
        if bb is not None:
            bits.append(f"BBw={float(bb):.3f}")
        items.append(f"{sym}({', '.join(bits)})")
    return " | ".join(items)


def _build_user_prompt(cycle_data: dict, symbol: Optional[str] = None) -> str:
    """Build the user-side market context in harness._debate_one_symbol
    style (prices + portfolio + regime + symbol_regimes).
    """
    prices = cycle_data.get("prices") or {}
    cash = cycle_data.get("cash", 0)
    pv = cycle_data.get("portfolio_value", 0)
    initial = cycle_data.get("initial_cash", 100_000)
    positions = cycle_data.get("positions") or []
    symbol_regimes = cycle_data.get("symbol_regimes") or {}
    metrics = cycle_data.get("metrics") or {}
    fg = metrics.get("fear_greed") or {}

    price_lines = []
    for sym, p in sorted(prices.items()):
        try:
            price_lines.append(f"  {sym}: ${float(p):,.2f}")
        except Exception:
            continue
    price_block = "\n".join(price_lines) if price_lines else "  unavailable"

    porfolio_block = (
        f"  cash: ${float(cash):,.2f}\n"
        f"  total_value: ${float(pv):,.2f} "
        f"(vs initial ${float(initial):,.2f})\n"
        f"  positions: {_format_positions(positions)}"
    )

    regime_block = (
        f"  fear_greed: {fg.get('value', 'N/A')} "
        f"({fg.get('classification', 'N/A')})\n"
        f"  symbol_regimes: {_format_symbol_regimes(symbol_regimes)}"
    )

    focus = f"  focus: {symbol}\n" if symbol else ""

    return (
        "Market Analysis Request:\n"
        f"{focus}"
        "prices:\n"
        f"{price_block}\n"
        "portfolio:\n"
        f"{porfolio_block}\n"
        "regime:\n"
        f"{regime_block}\n"
        "Decide the next action for the focus symbol above. "
        "If no focus is specified, decide the overall posture."
    )


# ── Assistant templates ─────────────────────────────────────────────────

def _tmpl_buy_correct(sym: str, regime: str, entry: float, exit_: float,
                      pnl_pct: float) -> str:
    return (
        f"Action: BUY. This was correct. The {regime} market conditions "
        f"supported this BUY decision. Evidence: {sym} moved from "
        f"${entry:.2f} \u2192 ${exit_:.2f} (+{pnl_pct:.2%}). "
        f"The trend aligned with entry timing, validating the bullish thesis."
    )


def _tmpl_buy_wrong(sym: str, regime: str, entry: float, exit_: float,
                    pnl_pct: float) -> str:
    return (
        f"Action: HOLD. The original BUY was incorrect in {regime} "
        f"conditions. A more conservative stance would have avoided the "
        f"{pnl_pct:.2%} loss. Counter-evidence: {sym} moved against the "
        f"position from ${entry:.2f} \u2192 ${exit_:.2f}. Wait for a "
        f"better entry signal."
    )


def _tmpl_sell_profit(sym: str, regime: str, pnl_pct: float) -> str:
    return (
        f"Action: SELL. Taking profits at {pnl_pct:.2%} was the right "
        f"risk management decision in {regime} conditions. The {sym} "
        f"position had reached target; locking in gains prevents giving "
        f"them back to a regime-shift."
    )


def _tmpl_sell_loss(sym: str, regime: str, pnl_pct: float) -> str:
    return (
        f"Action: HOLD. The forced sell at {pnl_pct:.2%} loss on {sym} "
        f"suggests poor entry timing. In {regime} conditions, waiting for "
        f"a better entry rather than chasing the move would have preserved "
        f"capital. Counter-evidence: price moved against the position."
    )


def _tmpl_hold_correct(sym: str, regime: str) -> str:
    return (
        f"Action: HOLD. Holding {sym} was correct in {regime} conditions. "
        f"Insufficient bullish or bearish evidence warranted no new trade; "
        f"avoiding noise preserved capital. Counter-evidence: absence of "
        f"a clear breakout signal."
    )


def _tmpl_cycle_dominant_correct(action: str, regime: str, ret_pct: float) -> str:
    return (
        f"Action: {action}. The {regime} conditions favored {action} this "
        f"cycle and the portfolio outperformed by {ret_pct:.2%}. The "
        f"debate correctly identified the dominant risk posture."
    )


def _tmpl_cycle_dominant_wrong(action: str, regime: str, ret_pct: float) -> str:
    return (
        f"Action: HOLD. The {action} stance was incorrect in {regime} "
        f"conditions; the portfolio returned {ret_pct:.2%}. A more "
        f"conservative posture would have limited drawdown."
    )


# ── Example construction ────────────────────────────────────────────────

def _build_example(user: str, assistant: str, label: str) -> dict:
    return {
        "label": label,
        "conversations": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }


def _build_trade_examples(
    cycle_exit: dict,
    cycle_map: Dict[int, dict],
    seen_trade_ids: set,
) -> List[dict]:
    """Build entry-side and exit-side examples for each non-zero-PnL trade."""
    out: List[dict] = []
    exit_cycle_num = cycle_exit.get("cycle")
    for t in cycle_exit.get("trades", []):
        pnl_pct = float(t.get("pnl_pct", 0) or 0)
        if pnl_pct == 0:
            continue
        entry_cycle = t.get("entry_cycle")
        exit_cycle = t.get("exit_cycle", exit_cycle_num)
        if entry_cycle is None:
            continue
        # Deduplicate across cycle files that may overlap
        tid = (t.get("symbol"), entry_cycle, exit_cycle, t.get("timestamp"))
        if tid in seen_trade_ids:
            continue
        seen_trade_ids.add(tid)

        sym = t.get("symbol", "?")
        entry_price = float(t.get("entry_price", 0) or 0)
        exit_price = float(t.get("exit_price", 0) or 0)

        # ── Entry-side example (use entry-cycle file's market context) ─
        entry_data = cycle_map.get(entry_cycle)
        if entry_data is not None:
            regime = _regime_label(entry_data, sym)
            user_entry = _build_user_prompt(entry_data, symbol=sym)
            if pnl_pct > 0:
                assistant_entry = _tmpl_buy_correct(
                    sym, regime, entry_price, exit_price, pnl_pct
                )
                label_entry = "BUY"
            else:
                assistant_entry = _tmpl_buy_wrong(
                    sym, regime, entry_price, exit_price, pnl_pct
                )
                label_entry = "HOLD"   # verdict is "should have held"
            out.append(_build_example(user_entry, assistant_entry, label_entry))

        # ── Exit-side example (use exit-cycle file's market context) ────
        regime_exit = _regime_label(cycle_exit, sym)
        user_exit = _build_user_prompt(cycle_exit, symbol=sym)
        if pnl_pct > 0:
            assistant_exit = _tmpl_sell_profit(sym, regime_exit, pnl_pct)
            label_exit = "SELL"
        else:
            assistant_exit = _tmpl_sell_loss(sym, regime_exit, pnl_pct)
            label_exit = "HOLD"   # "should have held onto it longer"
        out.append(_build_example(user_exit, assistant_exit, label_exit))

    return out


def _build_hold_counterfactuals(
    cycle_data: dict,
    max_holds: int = DEFAULT_MAX_HOLDS_PER_CYCLE,
) -> List[dict]:
    """Reinforce correct HOLD signals — pick HOLD signals whose symbol did
    not move violently (no breakout) during this cycle.
    """
    out: List[dict] = []
    prices = cycle_data.get("prices") or {}
    if not prices:
        return out

    hold_sigs = [
        s for s in (cycle_data.get("signals") or [])
        if s.get("action") == "HOLD"
    ]
    if not hold_sigs:
        return out

    # Group by symbol; take at most a couple per symbol
    by_sym: Dict[str, List[dict]] = {}
    for s in hold_sigs:
        by_sym.setdefault(s.get("symbol", "?"), []).append(s)

    chosen: List[dict] = []
    for sym, sigs in by_sym.items():
        # Pick the first HOLD per symbol (they're all similar in a cycle)
        chosen.append(sigs[0])
        if len(chosen) >= max_holds:
            break

    for s in chosen:
        sym = s.get("symbol", "?")
        regime = _regime_label(cycle_data, sym)
        user = _build_user_prompt(cycle_data, symbol=sym)
        assistant = _tmpl_hold_correct(sym, regime)
        out.append(_build_example(user, assistant, "HOLD"))

    return out


def _build_cycle_level_examples(cycle_data: dict) -> List[dict]:
    """At the cycle level: if the portfolio grew over the cycle, reinforce
    the dominant action; if it shrank, label it as a HOLD-missed case.
    """
    out: List[dict] = []
    initial = float(cycle_data.get("initial_cash", 0) or 0)
    pv = float(cycle_data.get("portfolio_value", 0) or 0)
    if initial <= 0:
        return out

    ret_pct = (pv - initial) / initial
    if abs(ret_pct) < 1e-6:
        return out

    # Determine this cycle's dominant signal action
    counts: Dict[str, int] = {}
    for s in cycle_data.get("signals") or []:
        a = s.get("action", "HOLD")
        counts[a] = counts.get(a, 0) + 1
    if not counts:
        return out
    dominant = max(counts, key=counts.get)
    if dominant == "HOLD":
        # The cycle already leans conservative; not useful as a strong signal
        return out

    regime = _regime_label(cycle_data)
    user = _build_user_prompt(cycle_data)
    if ret_pct > 0:
        assistant = _tmpl_cycle_dominant_correct(dominant, regime, ret_pct)
        label = dominant
    else:
        assistant = _tmpl_cycle_dominant_wrong(dominant, regime, ret_pct)
        label = "HOLD"
    out.append(_build_example(user, assistant, label))
    return out


# ── Balance / Output ────────────────────────────────────────────────────

def _balance_examples(examples: List[dict], balance_mode: str,
                      seed: int = 42) -> List[dict]:
    """Downsample to roughly equal BUY/SELL/HOLD counts.

    Modes:
      none       — no balancing
      equal      — match all three pools to the smallest non-HOLD size
      match_buy  — match all three to the BUY pool (maximises SELL  
                   utility even when SELL is the smallest pool)
      match_min  — match all three to the overall smallest pool
    """
    if balance_mode == "none":
        return examples

    rng = random.Random(seed)
    by_label: Dict[str, List[dict]] = {"BUY": [], "SELL": [], "HOLD": []}
    for ex in examples:
        lab = ex.get("label", "HOLD")
        if lab not in by_label:
            continue
        by_label[lab].append(ex)

    sizes = {k: len(v) for k, v in by_label.items()}
    logger.info(f"Pre-balance counts: {sizes}")

    if balance_mode == "match_min":
        target = min(sizes.values())
    elif balance_mode == "match_buy":
        target = sizes["BUY"]
    elif balance_mode == "match_sell":
        target = sizes["SELL"]
    else:  # "equal"
        non_hold = [v for k, v in sizes.items() if k != "HOLD"]
        target = min(non_hold) if non_hold else min(sizes.values())
        # Don't oversample HOLD — cap at target
        target = max(min(target, sizes["HOLD"]),
                     min(non_hold + [sizes["HOLD"]]))

    if target <= 0:
        return examples

    balanced: List[dict] = []
    for lab, pool in by_label.items():
        if len(pool) <= target:
            balanced.extend(pool)
        else:
            balanced.extend(rng.sample(pool, target))
    rng.shuffle(balanced)

    post = {"BUY": 0, "SELL": 0, "HOLD": 0}
    for ex in balanced:
        post[ex.get("label", "HOLD")] = post.get(ex.get("label", "HOLD"), 0) + 1
    logger.info(f"Post-balance counts: {post} (total={len(balanced)})")
    return balanced


def _write_jsonl(examples: List[dict], output_path: str) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for ex in examples:
            # Strip the internal 'label' key before writing
            conv = ex.get("conversations", ex)
            if isinstance(conv, list):
                f.write(json.dumps({"conversations": conv}) + "\n")
            else:
                f.write(json.dumps(ex) + "\n")


# ── Main driver ─────────────────────────────────────────────────────────

def build_legacy_training_data(
    state_dir: str,
    output_path: str = None,
    max_cycles: int = 0,
    balance: str = "equal",
    max_per_cycle_trades: int = DEFAULT_MAX_PER_CYCLE_TRADES,
    max_holds_per_cycle: int = DEFAULT_MAX_HOLDS_PER_CYCLE,
    include_counterfactuals: bool = True,
    include_cycle_level: bool = True,
    seed: int = 42,
) -> Tuple[str, int]:
    """Build ShareGPT training data from all cycle_*.json files.

    Args:
        state_dir: directory containing data/history/cycle_*.json
        output_path: where to write JSONL (default <state_dir>/training/
                     training_data_legacy.jsonl)
        max_cycles: cap on number of cycle files to process (0 = all)
        balance: balancing mode (none/equal/match_buy/match_min)
        max_per_cycle_trades: max trades-per-cycle to convert
        max_holds_per_cycle: max HOLD counterfactuals per cycle
        include_counterfactuals: build HOLD-reinforcing examples
        include_cycle_level: build cycle-level dominant-action examples

    Returns:
        (output_path, num_examples)
    """
    history_dir = Path(state_dir) / "history"
    if not history_dir.exists():
        logger.error("no history dir at %s", history_dir)
        return "", 0

    all_files = sorted(
        history_dir.glob("cycle_*.json"),
        key=_cycle_num,
    )
    if max_cycles > 0 and len(all_files) > max_cycles:
        rng = random.Random(seed)
        all_files = rng.sample(all_files, max_cycles)
        all_files.sort(key=_cycle_num)
    logger.info("processing %d cycle files", len(all_files))

    # Pre-load all cycle files into a cycle-number → data map; this is what
    # lets us look up the entry-cycle context for any trade.
    cycle_map: Dict[int, dict] = {}
    parse_fail = 0
    for fp in all_files:
        try:
            d = json.loads(fp.read_text())
            cn = d.get("cycle")
            if cn is not None:
                cycle_map[int(cn)] = d
        except Exception:
            parse_fail += 1
    logger.info(
        "loaded %d cycle dicts (%d parse failures)",
        len(cycle_map), parse_fail,
    )

    seen_trade_ids: set = set()
    all_examples: List[dict] = []
    trade_examples = 0
    hold_examples = 0
    cycle_examples = 0
    for fp in all_files:
        try:
            cycle_exit = json.loads(fp.read_text())
        except Exception:
            continue

        # Per-cycle caps
        exit_trades = cycle_exit.get("trades") or []
        if len(exit_trades) > max_per_cycle_trades:
            exit_trades = exit_trades[:max_per_cycle_trades]
        capped = dict(cycle_exit)
        capped["trades"] = exit_trades

        trade_exs = _build_trade_examples(capped, cycle_map, seen_trade_ids)
        if trade_exs:
            all_examples.extend(trade_exs)
            trade_examples += len(trade_exs)

        if include_counterfactuals:
            cf = _build_hold_counterfactuals(
                cycle_exit, max_holds=max_holds_per_cycle
            )
            if cf:
                all_examples.extend(cf)
                hold_examples += len(cf)

        if include_cycle_level:
            cl = _build_cycle_level_examples(cycle_exit)
            if cl:
                all_examples.extend(cl)
                cycle_examples += len(cl)

    logger.info(
        "raw examples: %d (trade-derived=%d, hold-counterfactuals=%d, "
        "cycle-level=%d)",
        len(all_examples), trade_examples, hold_examples, cycle_examples,
    )

    # Balance BUY/SELL/HOLD
    balanced = _balance_examples(all_examples, balance, seed=seed)

    if not balanced:
        logger.warning("no training examples produced")
        return "", 0

    if output_path is None:
        out_dir = Path(state_dir) / "training"
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / "training_data_legacy.jsonl")
    _write_jsonl(balanced, output_path)
    logger.info("wrote %d examples → %s", len(balanced), output_path)
    return output_path, len(balanced)


# ── CLI ────────────────────────────────────────────────────────────────

def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", default="/home/mrc/opentrader/data",
                   help="data dir containing history/cycle_*.json")
    p.add_argument("--output", default=None,
                   help="output JSONL path (default: <state-dir>/training/"
                        "training_data_legacy.jsonl)")
    p.add_argument("--max-cycles", type=int, default=0,
                   help="cap on number of cycle files to process (0=all)")
    p.add_argument("--balance", default="equal",
                   choices=["none", "equal", "match_buy", "match_min",
                            "match_sell"],
                   help="action-balancing strategy")
    p.add_argument("--max-per-cycle-trades", type=int,
                   default=DEFAULT_MAX_PER_CYCLE_TRADES)
    p.add_argument("--max-holds-per-cycle", type=int,
                   default=DEFAULT_MAX_HOLDS_PER_CYCLE)
    p.add_argument("--no-counterfactuals", action="store_true",
                   help="skip HOLD counterfactual generation")
    p.add_argument("--no-cycle-level", action="store_true",
                   help="skip cycle-level dominant-action examples")
    p.add_argument("--print-samples", type=int, default=0,
                   help="print N sample conversations to stdout for debug")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    out, n = build_legacy_training_data(
        state_dir=args.state_dir,
        output_path=args.output,
        max_cycles=args.max_cycles,
        balance=args.balance,
        max_per_cycle_trades=args.max_per_cycle_trades,
        max_holds_per_cycle=args.max_holds_per_cycle,
        include_counterfactuals=not args.no_counterfactuals,
        include_cycle_level=not args.no_cycle_level,
        seed=args.seed,
    )

    print(f"\n---- Result ----")
    print(f"output: {out}")
    print(f"examples: {n}")

    if args.print_samples > 0 and out and Path(out).exists():
        print(f"\n---- Sample conversations ({args.print_samples}) ----")
        with open(out) as f:
            lines = f.readlines()
        import random as _r
        rng = _r.Random(args.seed)
        for line in rng.sample(lines, min(args.print_samples, len(lines))):
            ex = json.loads(line)
            conv = ex.get("conversations", [])
            print("\n" + "=" * 60)
            for msg in conv:
                role = msg.get("role", "?")
                content = msg.get("content", "")
                # Truncate long content for readability
                if len(content) > 800:
                    content = content[:800] + " ..."
                print(f"[{role}]\n{content}")
            print("=" * 60)


if __name__ == "__main__":
    _cli()