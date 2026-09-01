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
  llm                 OpenAI-compatible endpoint (--llm-base-url/--llm-model)

Usage:
  python3 scripts/agent_gym.py                       # all rule baselines
  python3 scripts/agent_gym.py --policies random,c08_mr_fade_cot
  python3 scripts/agent_gym.py --policies llm \
      --llm-base-url http://127.0.0.1:5802/v1 --llm-model qwen38-4b [--run-label smoke]
"""

import json
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
TEMPLATE = "agent-gym-state-v0.1"


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
        ctx = ShadowCtx(self.series, self.alldates, i, list(self.series), exog_series=self.exog)
        try:
            picks = self.cand.entry(ctx)
            assert isinstance(picks, dict)
        except Exception as e:
            print(f"    ! candidate entry failed on bar {i}: {e}")
            return {"opens": [], "closes": []}
        ordered = [s for s, _w in sorted(picks.items(), key=lambda kv: -kv[1])]
        held = [p["symbol"] for p in state["positions"]]
        return {"opens": [s for s in ordered if s not in held][:MAX_OPEN_PER_DAY], "closes": []}


class LLM(Policy):
    name = "llm"
    def __init__(self, base_url, model, api_key="", log=None):
        self.base_url, self.model, self.api_key, self.log = base_url, model, api_key, log
        self.violations = self.tokens = self.parse_failures = 0

    def _prompt(self, state):
        syms = []
        for s, d in state["symbols"].items():
            syms.append(f"{s}: closes={['%.5f' % c for c in d['closes'][-8:]]} "
                        f"ret30={d['ret30']:+.2%} vs_ma20={'above' if d['above_ma20'] else 'below'} "
                        f"cot_z={d['cot_z']}")
        return (
            "You are the sole decision-maker of a $100,000 FX book (7 majors). "
            "Once per trading day you may OPEN one new position ($10,000 notional, "
            "ATR stop/target attached automatically, max 3 positions), CLOSE any "
            "held positions, or HOLD. Respond with ONLY JSON:\n"
            '{"opens": ["SYMBOL"], "closes": ["SYMBOL"]}\n\n'
            f"Date: {state['date']}  Equity: ${state['equity']:,.0f}  Cash: ${state['cash']:,.0f}\n"
            f"Open positions: {state['positions'] or 'none'}\n" + "\n".join(syms))

    def act(self, state, i):
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "user", "content": self._prompt(state)}]}
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.load(r)
        except Exception as e:
            self.violations += 1
            return {"opens": [], "closes": [], "_violation": f"endpoint: {e}"}
        msg = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = resp.get("usage", {})
        self.tokens += usage.get("total_tokens", 0)
        if self.log:
            self.log.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                       "bar": i, "date": state["date"],
                                       "latency_s": round(time.time() - t0, 2),
                                       "usage": usage, "raw": msg}, default=str) + "\n")
            self.log.flush()
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

def run_episode(policy, bars, alldates, lo, hi, exog, fills_out):
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
        state = {
            "date": datetime.fromtimestamp(int(alldates[i]), tz=timezone.utc).strftime("%Y-%m-%d"),
            "equity": mark(i), "cash": cash, "template": TEMPLATE,
            "positions": [{"symbol": s, "entry": round(p["entry"], 5), "bars_seen": p["bars_seen"]}
                          for s, p in book.items()],
            "symbols": {},
        }
        for sym, bl in bars.items():
            z = exog_z(exog, "COT:" + sym.split("_")[0], alldates[i])
            ma20 = (sum(bl[j][3] for j in range(i - 20, i)) / 20.0) if i >= 20 and all(
                bl[j] is not None for j in range(i - 20, i)) else None
            state["symbols"][sym] = {
                "closes": [bl[j][3] for j in range(max(0, i - 9), i + 1) if bl[j]],
                "ret30": _mom(bl, i, 30) or 0.0,
                "above_ma20": bool(ma20 and bl[i][3] > ma20),
                "cot_z": z,
            }
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


def main():
    argv = sys.argv
    pol_names = (argv[argv.index("--policies") + 1].split(",")
                 if "--policies" in argv else ["buy_hold", "random", "mom_k5", "c08_mr_fade_cot"])
    run_label = (argv[argv.index("--run-label") + 1] if "--run-label" in argv
                 else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    episodes = EPISODES[:int(argv[argv.index("--episodes") + 1])] if "--episodes" in argv else EPISODES

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
        elif name == "llm":
            base_url = (argv[argv.index("--llm-base-url") + 1] if "--llm-base-url" in argv
                        else "http://127.0.0.1:5802/v1")
            model = (argv[argv.index("--llm-model") + 1] if "--llm-model" in argv
                     else "qwen38-4b")
            api_key = (argv[argv.index("--llm-api-key") + 1] if "--llm-api-key" in argv else "")
            p = LLM(base_url, model, api_key, log=(run_dir / "llm_responses.jsonl").open("a"))
            p.name = f"llm({model})"
            policies.append(p)
        else:
            policies.append(GymCandidate(name, series, alldates, exog))

    meta = {"run": run_label, "template": TEMPLATE, "episodes": episodes, "cash0": CASH0,
            "notional": NOTIONAL, "atr": [ATR_STOP, ATR_TP], "hold": HOLD,
            "max_positions": MAX_POS, "max_open_per_day": MAX_OPEN_PER_DAY,
            "spread": SPREAD, "window": [alldates[0], alldates[-1]], "policies": pol_names}
    (run_dir / "config.json").write_text(json.dumps(meta, indent=2))

    scoreboard, all_fills = {}, []
    for pol in policies:
        eps, pol_fills, curves = [], [], []
        for k, (lo, hi) in enumerate(episodes):
            ep_fills = []
            r = run_episode(pol, bars, alldates, lo, hi, exog, ep_fills)
            for f in ep_fills:
                f["ep"] = k
            pol_fills.extend(ep_fills)
            curves.extend(r["curve"])
            eps.append(stats(ep_fills, r["curve"]))
        all_fills.extend([{**f, "policy": pol.name} for f in pol_fills])
        pooled = stats(pol_fills, curves)
        scoreboard[pol.name] = {"episodes": eps, "pooled": pooled,
                                "violations": getattr(pol, "violations", 0),
                                "tokens": getattr(pol, "tokens", 0),
                                "parse_failures": getattr(pol, "parse_failures", 0)}
        print(f"  {pol.name:<20} " + "  ".join(
            f"ep{k}[n={e['n']} PF {e['pf']} ret {e['ret_pct']:+.2f}% dd {e['maxdd_pct']:.2f}%]"
            for k, e in enumerate(eps))
            + f"  pooled[n={pooled['n']} PF {pooled['pf']} PnL {pooled['pnl']:+,.0f}]"
            + (f" viol={pol.violations} tokens={pol.tokens}" if isinstance(pol, LLM) else ""))

    (run_dir / "scoreboard.json").write_text(json.dumps(
        {"meta": meta, "scoreboard": scoreboard, "fills": all_fills}, indent=1, default=str))
    print(f"\nscoreboard: {run_dir / 'scoreboard.json'}")


if __name__ == "__main__":
    main()
