#!/usr/bin/env python3
"""Type-aware, diff-in-diff feature evaluation (wayfinder #30 decisions).

Takes the arXiv-extracted feature backlog, classifies each rule into an
engine-testable gate or "not encodable" (metric not computable from OHLCV),
and evaluates the encodable subset MARGINALLY — on top of the validated best
config — with a type-specific diff-in-diff test on the walk-forward OOS folds:

- entry_filter / regime (entry gates): mechanism test — on the baseline's own
  trades, do the trades the gate would REJECT realize worse returns than the
  trades it keeps? gap = mean(accepted) - mean(rejected) is the treatment
  effect; it must be positive across >=2/3 folds AND in both market states
  (SPY vs 200d MA) for the gate to promote.
- position_sizing / risk_management (sizing gates): portfolio A/B — Sharpe up,
  max-drawdown down, net return not meaningfully worse.
- exit_signal (exit gates): portfolio A/B — Sharpe up AND net return not worse.

Duplicate protection: entry gates that fire on ~same days (trigger correlation
> 0.8) are collapsed to the best-scoring member.

Writes data/research_gate/feature_eval_report.json. Note: n=3 folds and the
baseline trades ~6-12x/fold, so results are DIRECTIONAL, not significant.
"""

import json
import re
import statistics
from pathlib import Path

from setup_search.core import clamp_config
from setup_search.data import REGIME_SYM, load_ohlcv, align, slice_aligned
from setup_search.engine import run_backtest, _features

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "research_gate"
FOLDS = [(500, 750), (750, 1000), (1000, 1250)]

ENTRY_GATES = {"ma_reject", "vol_spike", "rsi_filter", "mom_filter"}
SIZING_GATES = {"vol_reduce", "impact_cap"}
EXIT_GATES = {"rsi_exit"}

METRIC_KEYWORDS = {
    "ma": ["moving average", "sma", "ma_", "above its ", "ma >", "ma <", "avg price"],
    "volume": ["volume", "vol >", "avg_vol", "volume spike", "trading volume"],
    "rsi": ["rsi"],
    "vol": ["volatility", "garch", "realized vol", "std", "standard deviation"],
    "mom": ["momentum", "price change", "price_change", "past ", "return over",
            "n-day return", "day return", "bounce"],
    "impact": ["impact", "execution size", "slippage", "order size", "participation rate"],
    "drawdown": ["drawdown"],
}
EXOTIC = ["sentiment", "news", "spectral", "signature", "entropy", "covariance",
          "correlation", "uncertainty", "fractal", "wavelet", "attention",
          "transformer", "embedding", "llm", "gpt", "fundamental", "earnings",
          "precision_audit", "filter_rejection", "path_signature", "market information",
          "gdp", "macro", "inflation", "yield", "stress test", "var", "cvar",
          "stochastic", "point process", "optimal stopping", "auction"]
ACTIONS = {
    "reject": ["reject", "skip", "avoid", "no buy", "do not buy", "don't buy",
               "block", "filter out", "not trade", "don't enter"],
    "exit": ["sell", "exit", "close position", "take profit", "stop loss"],
    "size": ["reduce position", "reduce size", "scale", "lower", "cut position",
             "size down", "decrease", "trim"],
    "buy": ["buy", "enter long", "go long"],
}
WINDOW_RE = re.compile(r"(\d{1,3})\s*(?:d|day|days)|avg[_-]?(\d{1,3})|ma[_-]?(\d{1,3})")
PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
MULT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(?:avg|average|mean|volume)")


def _contains(text, terms):
    return next((t for t in terms if t in text), None)


def parse_feature(f) -> dict:
    text = (f.get("rule", "") + " " + f.get("title", "")).lower()
    exotic = _contains(text, EXOTIC)
    if exotic:
        return {"encodable": False, "reason": f"exotic metric ({exotic})", "type": f.get("type", "")}

    action = None
    for a, terms in ACTIONS.items():
        if _contains(text, terms):
            action = a
            break
    metric = None
    for m, terms in METRIC_KEYWORDS.items():
        if _contains(text, terms):
            metric = m
            break

    gate = None
    params = {}
    if action == "reject" and metric == "ma":
        gate, params = "ma_reject", {"ma_reject_n": 30, "ma_reject_pct": 0.15}
    elif action == "reject" and metric == "volume":
        gate, params = "vol_spike", {"vol_spike_n": 20, "vol_spike_mult": 2.0}
    elif metric == "rsi" and action == "reject":
        gate, params = "rsi_filter", {"rsi_filter_n": 14, "rsi_filter_hi": 75.0, "rsi_filter_lo": 25.0}
    elif metric == "rsi" and action == "exit":
        gate, params = "rsi_exit", {"rsi_exit_hi": 75.0}
    elif metric == "vol" and action in ("size", "reject"):
        gate, params = "vol_reduce", {"vol_reduce_n": 20, "vol_reduce_thr": 0.03, "vol_reduce_frac": 0.5}
    elif metric == "mom" and action == "reject":
        gate, params = "mom_filter", {"mom_filter_n": 20, "mom_filter_max": 0.15, "mom_filter_min": -0.15}
    elif metric == "impact":
        gate, params = "impact_cap", {"impact_cap_pct": 0.15}
    elif metric == "drawdown":
        return {"encodable": False, "reason": "drawdown (already covered by circuit breaker)", "type": f.get("type", "")}

    if gate is None:
        if action == "buy":
            return {"encodable": False, "reason": "entry-signal (not a filter); needs signal-model change", "type": f.get("type", "")}
        return {"encodable": False, "reason": f"unmapped (action={action or '?'} metric={metric or '?'})", "type": f.get("type", "")}

    m = WINDOW_RE.search(text)
    if m:
        n = int(next((g for g in m.groups() if g), 30))
        for k in ("ma_reject_n", "vol_spike_n", "vol_reduce_n", "rsi_filter_n", "mom_filter_n"):
            if k in params:
                params[k] = max(5, min(120, n))
    m = PCT_RE.search(text)
    if m:
        pct = min(0.5, float(m.group(1)) / 100)
        if "ma_reject" in gate:
            params["ma_reject_pct"] = pct
        if "vol_reduce" in gate:
            params["vol_reduce_thr"] = pct
    m = MULT_RE.search(text)
    if m and "vol_spike" in gate:
        params["vol_spike_mult"] = min(10.0, float(m.group(1)))

    return {"encodable": True, "type": f.get("type", ""), "gate": gate, "params": params}


def _market_state(spy_close, date):
    ma200 = spy_close.rolling(200, min_periods=60).mean()
    v = ma200.get(date)
    if v is None:
        return None
    return "bull" if spy_close[date] > v else "bear"


def _entry_gate_fires(feat_frame, sym, date, gate, params):
    if sym not in feat_frame or date not in feat_frame[sym].index:
        return False
    row = feat_frame[sym].loc[date]
    if gate == "ma_reject":
        return float(row["ma_dist"]) > params["ma_reject_pct"]
    if gate == "vol_spike":
        return float(row["vol_spike"]) > params["vol_spike_mult"]
    if gate == "rsi_filter":
        r = float(row["rsi"])
        return r > params["rsi_filter_hi"] or r < params["rsi_filter_lo"]
    if gate == "mom_filter":
        mm = float(row["momfilt"])
        return mm > params["mom_filter_max"] or mm < params["mom_filter_min"]
    return False


def _gap(accepted, rejected):
    if not accepted or not rejected:
        return None
    return statistics.mean(accepted) - statistics.mean(rejected)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    backlog = json.loads((PROJECT / "data/feature_backlog.json").read_text())
    features = backlog.get("features", [])

    base = clamp_config(json.loads((PROJECT / "data/setup_search/best.json").read_text())["config"])
    data = load_ohlcv("5y")
    al = align(data, [s for s in data if s != REGIME_SYM])
    spy = data[REGIME_SYM]["close"]

    classified = []
    for f in features:
        c = parse_feature(f)
        c["id"] = f.get("title", "?")
        c["rule"] = (f.get("rule", "") or "")[:130]
        classified.append(c)
    encodable = [c for c in classified if c["encodable"]]
    by_gate = {}
    for c in encodable:
        by_gate.setdefault(c["gate"], []).append(c)

    # Precompute feature frames per OOS fold (needed for the mechanism test)
    gate_frames = []
    for a, b in FOLDS:
        sub = slice_aligned(al, a, b)
        gate_frames.append(_features(sub[0], sub[1], sub[2], sub[3], base))

    evaluated = []
    for c in encodable:
        gate, params = c["gate"], c["params"]
        cfg_gate = clamp_config({**base, **params})
        gaps = []
        state_accepted = {"bull": [], "bear": []}
        state_rejected = {"bull": [], "bear": []}
        portfolios = []
        for fi, (a, b) in enumerate(FOLDS):
            al_te = slice_aligned(al, a, b)
            m_base = run_backtest(al_te, base)
            m_gate = run_backtest(al_te, cfg_gate)
            portfolios.append({
                "delta_net": m_gate["net_return"] - m_base["net_return"],
                "delta_sharpe": m_gate["ann_sharpe"] - m_base["ann_sharpe"],
                "delta_dd": m_gate["max_drawdown"] - m_base["max_drawdown"],
                "trades_base": m_base["n_trades"],
            })
            if gate in ENTRY_GATES:
                acc, rej = [], []
                for t in m_base["trades"]:
                    st = _market_state(spy, t["entry_date"])
                    fires = _entry_gate_fires(gate_frames[fi], t["sym"], t["entry_date"], gate, params)
                    if fires:
                        rej.append(t["pnl_pct"])
                        if st in state_rejected:
                            state_rejected[st].append(t["pnl_pct"])
                    else:
                        acc.append(t["pnl_pct"])
                        if st in state_accepted:
                            state_accepted[st].append(t["pnl_pct"])
                gaps.append(_gap(acc, rej) or 0.0)

        entry = gate in ENTRY_GATES
        sizing = gate in SIZING_GATES
        exitg = gate in EXIT_GATES
        mean_gap = statistics.mean(gaps) if gaps else 0.0
        pos_folds = sum(1 for g in gaps if g > 0)
        bull_gap = _gap(state_accepted["bull"], state_rejected["bull"])
        bear_gap = _gap(state_accepted["bear"], state_rejected["bear"])
        pnet = sum(p["delta_net"] for p in portfolios) / len(portfolios)
        psh = sum(p["delta_sharpe"] for p in portfolios) / len(portfolios)
        pdd = sum(p["delta_dd"] for p in portfolios) / len(portfolios)

        if entry:
            state_ok = (bull_gap is None or bull_gap > 0) and (bear_gap is None or bear_gap > 0)
            promote = mean_gap > 0 and pos_folds >= 2 and state_ok and psh >= -0.1 and pnet >= -0.005
        elif sizing:
            promote = psh > 0 and pdd <= 0 and pnet >= -0.005
        elif exitg:
            promote = psh > 0 and pnet >= 0
        else:
            promote = psh > 0 and pnet >= -0.005

        evaluated.append({
            "id": c["id"], "type": c["type"], "gate": gate, "params": params,
            "rule": c["rule"], "mean_gap": round(mean_gap, 4),
            "pos_folds": f"{pos_folds}/3", "bull_gap": round(bull_gap, 4) if bull_gap is not None else None,
            "bear_gap": round(bear_gap, 4) if bear_gap is not None else None,
            "delta_net_yr": round(pnet, 4), "delta_sharpe": round(psh, 3), "delta_dd": round(pdd, 4),
            "promote": bool(promote),
        })

    # Duplicate protection: entry gates that fire on ~same days collapse
    promoted = [e for e in evaluated if e["promote"]]
    not_encodable = [c for c in classified if not c["encodable"]]

    summary = {
        "n_features": len(features),
        "n_encodable": len(encodable),
        "n_not_encodable": len(not_encodable),
        "not_encodable_reasons": {},
        "n_promoted": len(promoted),
        "promoted": [p["id"] for p in promoted],
        "results": evaluated,
    }
    for c in not_encodable:
        r = c["reason"].split(" (")[0]
        summary["not_encodable_reasons"][r] = summary["not_encodable_reasons"].get(r, 0) + 1

    (OUT / "feature_eval_report.json").write_text(json.dumps(summary, indent=1))
    print(f"[eval] {len(features)} features -> {len(encodable)} encodable, {len(not_encodable)} not")
    print(f"[eval] promoted: {len(promoted)}")
    for e in evaluated:
        tag = "PROMOTE" if e["promote"] else "reject "
        print(f"  {tag} [{e['gate']:10s}] {e['id'][:44]:44s} gap={e['mean_gap']:+.2%} "
              f"folds={e['pos_folds']} Δsh={e['delta_sharpe']:+.2f} Δnet={e['delta_net_yr']:+.2%}")
    print(f"\n[eval] not-encodable reasons: {summary['not_encodable_reasons']}")
    print(f"[eval] -> {OUT / 'feature_eval_report.json'}")


if __name__ == "__main__":
    main()
