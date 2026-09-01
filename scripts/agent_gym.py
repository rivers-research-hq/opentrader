#!/usr/bin/env python3
"""agent_gym — internal FX agent gate, v0 (protocol: docs/research/agent-gym-protocol-v0.md).

Any policy — rule, gym candidate, or LLM over an OpenAI-compatible endpoint —
manages a $100k book on 7 FX majors across three 60-bar episodes drawn from
the signal gym's cached candle history (2024-09-24 → 2026-08-27). The harness
owns the uniform risk shape ($10k/pos, ATR 1.5/2.5 stop/target, 14-bar hold,
max 3 positions, max 1 open/day); the policy competes on decisions only.
Point-in-time is enforced in the state builder (a policy at bar t sees only
bars ≤ t). All scoring derives from append-only episode ledgers — never from
a policy's self-report. Raw LLM completions are logged verbatim.

Policies (v0 baseline set, identical pipeline for all):
  buy_hold            basket, first 3 symbols from day 1
  random              seeded random actions (the floor)
  mom_k5              incumbent Expert #0 rule (k5 momentum top-2; converges
                      to top-2 within 2 days under the 1-open/day cap)
  <gym-candidate>     any candidate file in data/signal_gym/candidates/,
                      loaded directly (no drift from what was verified),
                      e.g. c08_mr_fade_cot (the gym survivor = rule ceiling)
  llm:TIER            OpenAI-compatible endpoint per cost tier, from
                      config/agent_gate_models.json (free = local 4B,
                      flash/pro = deepseek-v4-flash / -v4-pro by declared
                      per-M pricing; api keys come from env var names)

Usage:
  python3 scripts/agent_gym.py                       # all rule baselines
  python3 scripts/agent_gym.py --policies random,c08_mr_fade_cot
  python3 scripts/agent_gym.py --episodes 1 --policies llm:free
  python3 scripts/agent_gym.py \
      --policies buy_hold,random,mom_k5,c08_mr_fade_cot,llm:free,llm:flash,llm:pro \
      --run-label v1-tiers
"""

import json
import os
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
from strategies.fx_shadow import ShadowCtx, load_candidate  # noqa: E402  (ctx + candidate loading: single source of truth)

CANDLES = PROJECT / "data" / "signal_gym" / "candles.json"
EXOG = PROJECT / "data" / "exog_cache.json"
OUT = PROJECT / "data" / "agent_gym"

CASH0 = 100_000.0
NOTIONAL, ATR_STOP, ATR_TP, HOLD = 10_000, 1.5, 2.5, 14
MAX_POS, MAX_OPEN_PER_DAY, SPREAD = 3, 1, 0.0001
EPISODES = [(85, 145), (235, 295), (385, 445)]  # decision-bar ranges (early/mid/late)
STATE_VERSIONS = ("v0.1", "v0.2")


# bars: list aligned to alldates; entry None where a symbol lacks that date

def _atr14(bars, i):
    if i < 15 or bars[i] is None:
        return None
    trs = []
    for j in range(i - 14, i + 1):
        if bars[j] is None:
            return None
        h, l, pc = bars[j][1], bars[j][2], bars[j - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs)


def _mom(bars, i, k):
    if i < k or bars[i] is None or bars[i - k] is None:
        return None
    return bars[i][3] / bars[i - k][3] - 1


def exog_z(exog, key, ts):
    series = exog.get(key)
    if not series:
        return None
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    usable = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=3)).strftime("%Y-%m-%d")
    cands = [k for k in series if k <= usable]
    return series[max(cands)] if cands else None


def _ma20_before(bars, i):
    """Gym convention: mean of the 20 closes BEFORE bar i."""
    if i < 20 or any(bars[j] is None for j in range(i - 20, i)):
        return None
    return sum(bars[j][3] for j in range(i - 20, i)) / 20.0


def build_state(bars, alldates, i, book, cash, exog, version):
    """Point-in-time state at bar i. v0.1 = the original minimal template;
    v0.2 adds what a trader needs to manage positions: current price vs
    entry, unrealized PnL, stop/target distances, MA20 value, ret5, ATR as
    a volatility fraction, 30-day close-range position."""
    template = f"agent-gym-state-{version}"
    state = {
        "date": datetime.fromtimestamp(int(alldates[i]), tz=timezone.utc).strftime("%Y-%m-%d"),
        "equity": None, "cash": cash, "template": template,
        "positions": [], "symbols": {},
    }
    if version == "v0.1":
        state["positions"] = [{"symbol": s, "entry": round(p["entry"], 5), "bars_seen": p["bars_seen"]}
                              for s, p in book.items()]
        for sym, bl in bars.items():
            z = exog_z(exog, "COT:" + sym.split("_")[0], alldates[i])
            ma20 = _ma20_before(bl, i)
            state["symbols"][sym] = {
                "closes": [bl[j][3] for j in range(max(0, i - 9), i + 1) if bl[j]],
                "ret30": _mom(bl, i, 30) or 0.0,
                "above_ma20": bool(ma20 and bl[i][3] > ma20),
                "cot_z": z,
            }
        return state

    # v0.2
    for sym, p in book.items():
        bl = bars[sym]
        cur = bl[i][3] if bl[i] else None
        state["positions"].append({
            "symbol": sym, "entry": round(p["entry"], 5), "bars_seen": p["bars_seen"],
            "now": round(cur, 5) if cur else None,
            "unrealized_pct": round(cur / p["entry"] - 1, 4) if cur else None,
            "stop_dist_pct": round(p["sl"] / cur - 1, 4) if cur else None,
            "target_dist_pct": round(p["tp"] / cur - 1, 4) if cur else None,
        })
    for sym, bl in bars.items():
        cur = bl[i][3] if bl[i] else None
        if cur is None:
            continue
        ma20 = _ma20_before(bl, i)
        range30 = [bl[j][3] for j in range(max(0, i - 29), i + 1) if bl[j]]
        lo, hi30 = min(range30), max(range30)
        state["symbols"][sym] = {
            "closes": [round(bl[j][3], 5) for j in range(max(0, i - 14), i + 1) if bl[j]],
            "ma20": round(ma20, 5) if ma20 else None,
            "vs_ma20_pct": round(cur / ma20 - 1, 4) if ma20 else None,
            "ret5": _mom(bl, i, 5),
            "ret30": _mom(bl, i, 30) or 0.0,
            "atr_pct": round((_atr14(bl, i) or 0) / cur, 4) if _atr14(bl, i) else None,
            "pos_in_30d_range": round((cur - lo) / (hi30 - lo), 3) if hi30 > lo else None,
            "cot_z": exog_z(exog, "COT:" + sym.split("_")[0], alldates[i]),
        }
    return state


# ── policies: act(state) -> {"opens": [sym], "closes": [sym]} ─────────────

class Policy:
    name = "?"
    violations = tokens = parse_failures = 0


class BuyHold(Policy):
    name = "buy_hold"
    def __init__(self, symbols):
        self.symbols = symbols
    def act(self, state, i):
        if state["positions"]:  # episode-start detection: force-close empties the book
            return {"opens": [], "closes": []}
        return {"opens": self.symbols[:MAX_POS], "closes": []}


class RandomAction(Policy):
    name = "random"
    def __init__(self, symbols, seed=7):
        self.symbols, self.rng = symbols, random.Random(seed)
    def act(self, state, i):
        held = [p["symbol"] for p in state["positions"]]
        if self.rng.random() < 0.05 and len(held) < MAX_POS:
            pool = [s for s in self.symbols if s not in held]
            return {"opens": [self.rng.choice(pool)] if pool else [], "closes": []}
        if self.rng.random() < 0.05 and held:
            return {"opens": [], "closes": [self.rng.choice(held)]}
        return {"opens": [], "closes": []}


class MomentumK5(Policy):
    """Incumbent Expert #0 rule: long top-2 by 5d return, positive only."""
    name = "mom_k5"
    def __init__(self, symbols, bars):
        self.symbols, self.bars = symbols, bars
    def act(self, state, i):
        ranked = sorted(((s, _mom(self.bars[s], i, 5)) for s in self.symbols),
                        key=lambda kv: -(kv[1] if kv[1] is not None else -9))
        target = [s for s, m in ranked if m is not None and m > 0][:2]
        held = [p["symbol"] for p in state["positions"]]
        return {"opens": [s for s in target if s not in held][:MAX_OPEN_PER_DAY],
                "closes": [s for s in held if s not in target]}


class GymCandidate(Policy):
    """Any gym candidate file (loaded directly — no drift from what was verified)."""
    def __init__(self, cand_name, series, alldates, exog):
        self.cand = load_candidate(cand_name)
        self.name = self.cand.NAME
        self.series, self.alldates, self.exog = series, alldates, exog
    def act(self, state, i):
        ordered = candidate_opens(self.cand, self.series, self.alldates, i, self.exog)
        held = [p["symbol"] for p in state["positions"]]
        return {"opens": [s for s in ordered if s not in held][:MAX_OPEN_PER_DAY], "closes": []}


def candidate_opens(cand, series, alldates, i, exog):
    """Run a gym candidate's entry() over the point-in-time ctx; return its
    proposed symbols in stable weight order (the rule's opportunity set)."""
    ctx = ShadowCtx(series, alldates, i, list(series), exog_series=exog)
    picks = cand.entry(ctx)
    assert isinstance(picks, dict)
    return [s for s, _w in sorted(picks.items(), key=lambda kv: -kv[1])]


class HybridVeto(Policy):
    """v0.3a hybrid mode: a rule proposes entries; the LLM sees each proposal
    with the rule's rationale and may approve or veto it. Opens come ONLY
    from the rule's opportunity set (attribution stays clean); exits remain
    with the engine. On unparseable LLM output the rule's proposal is
    approved as-is (fail-open to the verified rule) and the violation is
    counted. Days with no proposal make no LLM call."""
    def __init__(self, cand_name, llm, series, alldates, exog):
        self.cand = load_candidate(cand_name)
        self.llm = llm
        self.name = f"hybrid:{cand_name}:{llm.tier}"
        self.series, self.alldates, self.exog = series, alldates, exog
        self.violations = self.approved = self.vetoed = 0
        self.tokens = self.cost = 0.0  # proxied from llm at report time

    def act(self, state, i):
        try:
            ordered = candidate_opens(self.cand, self.series, self.alldates, i, self.exog)
        except Exception as e:
            print(f"    ! candidate entry failed on bar {i}: {e}")
            return {"opens": [], "closes": []}
        held = [p["symbol"] for p in state["positions"]]
        proposals = [s for s in ordered if s not in held][:MAX_OPEN_PER_DAY]
        if not proposals:
            return {"opens": [], "closes": []}

        lines = []
        for sym in proposals:
            d = state["symbols"][sym]
            lines.append(f"{sym}: fade {d['vs_ma20_pct']:+.2%} vs ma20 {d['ma20']} "
                         f"(close {d['closes'][-1]}), ret5 {d['ret5']:+.2%}, ret30 {d['ret30']:+.2%}, "
                         f"atr {d['atr_pct']:.2%}, 30d-range-pos {d['pos_in_30d_range']:.2f}, cot_z {d['cot_z']}")
        prompt = (
            "You are reviewing entry signals for a $100,000 FX book (7 majors). A systematic "
            "mean-reversion rule proposes to OPEN these positions today ($10,000 notional each, "
            "ATR 1.5/2.5 stop/target auto-attached, long only, max 3 positions, one open per day):\n"
            + "\n".join(lines)
            + f"\n\nBook context — date {state['date']}, equity ${state['equity']:,.0f}, "
            f"cash ${state['cash']:,.0f}, held: {state['positions'] or 'none'}.\n"
            "Market snapshot (all majors):\n"
            + "\n".join(f"{s}: close {d['closes'][-1]} vs ma20 {d['ma20']} ({d['vs_ma20_pct']:+.2%}), "
                        f"ret5 {d['ret5']:+.2%}, atr {d['atr_pct']:.2%}, cot_z {d['cot_z']}"
                        for s, d in state["symbols"].items())
            + "\n\nFor EACH proposal decide approve or veto. Respond with ONLY JSON, every "
              'proposed symbol in exactly one list:\n{"approve": ["SYMBOL"], "veto": ["SYMBOL"]}')
        try:
            msg, _u = self.llm._chat(prompt, log_ctx={"mode": "veto", "bar": i, "date": state["date"],
                                                       "proposals": proposals})
        except Exception as e:
            self.violations += 1
            return {"opens": proposals, "closes": [], "_violation": f"endpoint: {e} — fail-open to rule"}
        try:
            j = msg[msg.index("{"): msg.rindex("}") + 1]
            out = json.loads(j)
            approve = [str(s).upper() for s in out.get("approve", [])]
            veto = [str(s).upper() for s in out.get("veto", [])]
            approved = [s for s in proposals if s in approve and s not in veto]
            missing = [s for s in proposals if s not in approve and s not in veto]
            if missing:
                self.violations += 1
                approved = list(proposals)  # fail-open
            self.approved += len(approved)
            self.vetoed += len(proposals) - len(approved)
            return {"opens": approved, "closes": []}
        except Exception:
            self.violations += 1
            return {"opens": proposals, "closes": [], "_violation": "unparseable veto — fail-open to rule"}


class LLM(Policy):
    """One OpenAI-compatible endpoint per cost tier (free/flash/pro).
    Cost accounting is derived from provider-reported token usage × declared
    per-M pricing in the tier config — declared, never measured from the
    provider's billing, and labeled as such in the config."""
    name = "llm"
    def __init__(self, tier, base_url, model, api_key="", price_in=0.0, price_out=0.0,
                 extras=None, log=None):
        self.tier = tier
        self.name = f"llm:{tier}"
        self.base_url, self.model, self.api_key = base_url, model, api_key
        self.price_in, self.price_out = price_in, price_out  # USD per 1M tokens
        self.extras = extras or {}  # recorded serving config (e.g. thinking disabled)
        self.log = log
        self.violations = self.tokens = self.parse_failures = 0
        self.prompt_tokens = self.completion_tokens = self.cost = 0.0

    def _prompt(self, state):
        if state["template"].endswith("v0.1"):
            syms = []
            for s, d in state["symbols"].items():
                syms.append(f"{s}: closes={['%.5f' % c for c in d['closes'][-8:]]} "
                            f"ret30={d['ret30']:+.2%} vs_ma20={'above' if d['above_ma20'] else 'below'} "
                            f"cot_z={d['cot_z']}")
            pos = state["positions"] or "none"
        else:  # v0.2
            pos_rows = []
            for p in state["positions"]:
                pos_rows.append(f"{p['symbol']}: entry {p['entry']} now {p['now']} "
                                f"unrealized {p['unrealized_pct']:+.2%} held {p['bars_seen']}d "
                                f"stop {p['stop_dist_pct']:+.2%} target {p['target_dist_pct']:+.2%}")
            pos = "; ".join(pos_rows) or "none"
            syms = []
            for s, d in state["symbols"].items():
                syms.append(
                    f"{s}: close {d['closes'][-1]} ma20 {d['ma20']} ({d['vs_ma20_pct']:+.2%}) "
                    f"ret5 {d['ret5']:+.2%} ret30 {d['ret30']:+.2%} atr {d['atr_pct']:.2%} "
                    f"30d-range-pos {d['pos_in_30d_range']:.2f} cot_z {d['cot_z']}")
        return (
            "You are the sole decision-maker of a $100,000 FX book (7 majors). "
            "Once per trading day you may OPEN one new position ($10,000 notional, "
            "ATR stop/target attached automatically, max 3 positions), CLOSE any "
            "held positions, or HOLD. Respond with ONLY JSON:\n"
            '{"opens": ["SYMBOL"], "closes": ["SYMBOL"]}\n\n'
            f"Date: {state['date']}  Equity: ${state['equity']:,.0f}  Cash: ${state['cash']:,.0f}\n"
            f"Open positions: {pos}\n" + "\n".join(syms))

    def _chat(self, prompt, log_ctx=None):
        """Low-level OpenAI-compatible call; logs the raw completion verbatim.
        Raises on endpoint failure (caller counts the violation)."""
        body = {"model": self.model, "temperature": 0, **self.extras,
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
        msg = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = resp.get("usage", {})
        pt, ct = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        self.prompt_tokens += pt
        self.completion_tokens += ct
        self.tokens += usage.get("total_tokens", pt + ct)
        self.cost += (pt * self.price_in + ct * self.price_out) / 1e6
        if self.log:
            row = {"ts": datetime.now(timezone.utc).isoformat(),
                   "latency_s": round(time.time() - t0, 2), "usage": usage, "raw": msg}
            if log_ctx:
                row.update(log_ctx)
            self.log.write(json.dumps(row, default=str) + "\n")
            self.log.flush()
        return msg, usage

    def act(self, state, i):
        try:
            msg, _u = self._chat(self._prompt(state), log_ctx={"bar": i, "date": state["date"]})
        except Exception as e:
            self.violations += 1
            return {"opens": [], "closes": [], "_violation": f"endpoint: {e}"}
        try:
            j = msg[msg.index("{"): msg.rindex("}") + 1]
            out = json.loads(j)
            opens = [str(s).upper() for s in out.get("opens", [])][:MAX_OPEN_PER_DAY]
            closes = [str(s).upper() for s in out.get("closes", [])]
            return {"opens": opens, "closes": closes}
        except Exception:
            self.violations += 1
            self.parse_failures += 1
            return {"opens": [], "closes": [], "_violation": "unparseable response"}


# ── engine ────────────────────────────────────────────────────────────────

def run_episode(policy, bars, alldates, lo, hi, exog, fills_out, state_version="v0.1"):
    cash, book, curve = CASH0, {}, []

    def mark(i):
        eq = cash
        for sym, p in book.items():
            px = bars[sym][i]
            if px:
                eq += (px[3] - p["entry"]) * p["units"]
        return eq

    def close_pos(sym, i, reason):
        nonlocal cash
        p = book.pop(sym)
        px = bars[sym][i]
        pnl = (px[3] - p["entry"]) * p["units"] - SPREAD * p["units"]
        cash += pnl
        fills_out.append({"ts": alldates[i], "symbol": sym, "side": "SELL", "price": px[3],
                          "reason": reason, "pnl": round(pnl, 2), "paper": True})

    for i in range(lo, hi):
        # 1. exits: stop before target (pessimistic), then hold — gym convention
        for sym in list(book):
            p = book[sym]
            px = bars[sym][i]
            if px is None:
                continue
            p["bars_seen"] += 1
            if px[2] <= p["sl"]:
                close_pos(sym, i, "stop")
            elif px[1] >= p["tp"]:
                close_pos(sym, i, "target")
            elif p["bars_seen"] >= HOLD:
                close_pos(sym, i, "hold")

        # 2. policy decides (state strictly ≤ bar i)
        state = build_state(bars, alldates, i, book, cash, exog, state_version)
        state["equity"] = mark(i)
        act = policy.act(state, i)
        if act.get("_violation"):
            fills_out.append({"ts": alldates[i], "symbol": "-", "side": "VIOLATION",
                              "reason": act["_violation"], "pnl": None, "paper": True})

        # 3. closes first, then at most MAX_OPEN_PER_DAY opens (harness caps)
        for sym in act.get("closes", []):
            if sym in book and bars[sym][i] is not None:
                close_pos(sym, i, "policy-close")
        for sym in act.get("opens", []):
            if sym in book or len(book) >= MAX_POS or sym not in bars:
                continue
            px, atr = bars[sym][i], _atr14(bars[sym], i)
            if px is None or not atr or atr <= 0 or px[3] <= 0:
                continue
            units = int(NOTIONAL / px[3])
            book[sym] = {"units": units, "entry": px[3], "sl": px[3] - ATR_STOP * atr,
                         "tp": px[3] + ATR_TP * atr, "bars_seen": 0}
            fills_out.append({"ts": alldates[i], "symbol": sym, "side": "BUY", "price": px[3],
                              "reason": "policy-open", "pnl": None, "paper": True})
        curve.append(mark(i))

    i = hi - 1
    for sym in list(book):
        close_pos(sym, i, "episode-end")
    curve.append(cash)
    return {"cash": cash, "curve": curve}


def stats(fills, curve):
    pnls = [f["pnl"] for f in fills if f.get("pnl") is not None]
    wins = [p for p in pnls if p > 0]
    gl = abs(sum(p for p in pnls if p <= 0))
    peak, mdd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak)
    return {"n": len(pnls), "wr": round(len(wins) / len(pnls) * 100, 1) if pnls else None,
            "pf": round(sum(wins) / gl, 2) if gl else (float("inf") if wins else None),
            "pnl": round(sum(pnls), 2), "ret_pct": round((curve[-1] / CASH0 - 1) * 100, 2),
            "maxdd_pct": round(mdd * 100, 2)}


def _make_llm(tier, run_dir, log_suffix="", cfg_path=None):
    cfg_path = cfg_path or (PROJECT / "config" / "agent_gate_models.json")
    cfg = json.load(open(cfg_path))["tiers"][tier]
    api_key = os.environ.get(cfg["api_key_env"], "") if cfg.get("api_key_env") else ""
    return LLM(tier, cfg["base_url"], cfg["model"], api_key,
               cfg.get("price_in_per_m", 0.0), cfg.get("price_out_per_m", 0.0),
               extras=cfg.get("request_extras"),
               log=(run_dir / f"llm_responses_{tier}{log_suffix}.jsonl").open("a"))


def main():
    argv = sys.argv
    pol_names = (argv[argv.index("--policies") + 1].split(",")
                 if "--policies" in argv else ["buy_hold", "random", "mom_k5", "c08_mr_fade_cot"])
    run_label = (argv[argv.index("--run-label") + 1] if "--run-label" in argv
                 else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    episodes = EPISODES[:int(argv[argv.index("--episodes") + 1])] if "--episodes" in argv else EPISODES
    state_version = (argv[argv.index("--state") + 1] if "--state" in argv else "v0.1")
    if state_version not in STATE_VERSIONS:
        raise SystemExit(f"state must be one of {STATE_VERSIONS}")

    series = {s: {int(ts): tuple(px) for ts, px in d.items()}
              for s, d in json.load(open(CANDLES)).items()}
    alldates = sorted({ts for ss in series.values() for ts in ss})
    bars = {s: [series[s].get(ts) for ts in alldates] for s in series}
    exog = json.load(open(EXOG)) if EXOG.exists() else {}
    symbols = list(series)

    run_dir = OUT / run_label
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"agent_gym v0 — {len(symbols)} majors, episodes {EPISODES}, cash ${CASH0:,.0f}, "
          f"risk {NOTIONAL}/pos {ATR_STOP}/{ATR_TP} ATR, hold {HOLD}d, max {MAX_POS} pos")
    print(f"run dir: {run_dir}\n")

    policies = []
    for name in pol_names:
        if name == "buy_hold":
            policies.append(BuyHold(symbols))
        elif name == "random":
            policies.append(RandomAction(symbols))
        elif name == "mom_k5":
            policies.append(MomentumK5(symbols, bars))
        elif name.startswith("llm:"):
            tier = name.split(":", 1)[1]
            cfg_path = Path(argv[argv.index("--llm-config") + 1]) if "--llm-config" in argv else None
            policies.append(_make_llm(tier, run_dir, cfg_path=cfg_path))
        elif name.startswith("hybrid:"):
            _, cand_name, tier = name.split(":", 2)
            cfg_path = Path(argv[argv.index("--llm-config") + 1]) if "--llm-config" in argv else None
            llm = _make_llm(tier, run_dir, log_suffix=f"_{cand_name}", cfg_path=cfg_path)
            policies.append(HybridVeto(cand_name, llm, series, alldates, exog))
        else:
            policies.append(GymCandidate(name, series, alldates, exog))

    if any(isinstance(p, HybridVeto) for p in policies) and state_version != "v0.2":
        raise SystemExit("hybrid mode requires --state v0.2 (proposal lines use v0.2 fields)")

    meta = {"run": run_label, "template": f"agent-gym-state-{state_version}", "episodes": episodes,
            "cash0": CASH0,
            "notional": NOTIONAL, "atr": [ATR_STOP, ATR_TP], "hold": HOLD,
            "max_positions": MAX_POS, "max_open_per_day": MAX_OPEN_PER_DAY,
            "spread": SPREAD, "window": [alldates[0], alldates[-1]], "policies": pol_names}
    (run_dir / "config.json").write_text(json.dumps(meta, indent=2))

    scoreboard, all_fills = {}, []
    for pol in policies:
        eps, pol_fills, curves = [], [], []
        for k, (lo, hi) in enumerate(episodes):
            ep_fills = []
            r = run_episode(pol, bars, alldates, lo, hi, exog, ep_fills, state_version)
            for f in ep_fills:
                f["ep"] = k
            pol_fills.extend(ep_fills)
            curves.extend(r["curve"])
            eps.append(stats(ep_fills, r["curve"]))
        all_fills.extend([{**f, "policy": pol.name} for f in pol_fills])
        pooled = stats(pol_fills, curves)
        if isinstance(pol, HybridVeto):
            pol.tokens, pol.cost = pol.llm.tokens, pol.llm.cost
        scoreboard[pol.name] = {"episodes": eps, "pooled": pooled,
                                "violations": getattr(pol, "violations", 0),
                                "tokens": getattr(pol, "tokens", 0),
                                "prompt_tokens": getattr(pol, "prompt_tokens", 0) or getattr(getattr(pol, "llm", None), "prompt_tokens", 0),
                                "completion_tokens": getattr(pol, "completion_tokens", 0) or getattr(getattr(pol, "llm", None), "completion_tokens", 0),
                                "declared_cost_usd": round(getattr(pol, "cost", 0.0), 4),
                                "request_extras": getattr(pol, "extras", None) or getattr(getattr(pol, "llm", None), "extras", None),
                                "approved": getattr(pol, "approved", None),
                                "vetoed": getattr(pol, "vetoed", None),
                                "parse_failures": getattr(pol, "parse_failures", 0)}
        if isinstance(pol, HybridVeto):
            tail = f" viol={pol.violations} appr={pol.approved} veto={pol.vetoed} cost=${pol.cost:.4f}"
        elif isinstance(pol, LLM):
            tail = f" viol={pol.violations} tokens={pol.tokens} cost=${pol.cost:.4f}"
        else:
            tail = ""
        print(f"  {pol.name:<26} " + "  ".join(
            f"ep{k}[n={e['n']} PF {e['pf']} ret {e['ret_pct']:+.2f}% dd {e['maxdd_pct']:.2f}%]"
            for k, e in enumerate(eps))
            + f"  pooled[n={pooled['n']} PF {pooled['pf']} PnL {pooled['pnl']:+,.0f}]" + tail)

    (run_dir / "scoreboard.json").write_text(json.dumps(
        {"meta": meta, "scoreboard": scoreboard, "fills": all_fills}, indent=1, default=str))
    print(f"\nscoreboard: {run_dir / 'scoreboard.json'}")


if __name__ == "__main__":
    main()
